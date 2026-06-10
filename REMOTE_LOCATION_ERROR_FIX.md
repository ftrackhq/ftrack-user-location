# Remote Location Error Fix

**Issue Date**: 2026-06-10  
**Error**: `LocationError: No accessor defined for source location`

---

## Problem

When User A (loren) tries to sync FROM User B's location (dennis.weil@backlight.co.BL3079), the sync fails with:

```
ftrack_api.exception.LocationError: No accessor defined for source location <Location("dennis.weil@backlight.co.BL3079", ead0a071-ebb1-437e-bbe8-0ec1b98e7321)>.
```

###Root Cause

**User locations are machine-specific** - they only have accessors on the machine where they're registered. When loren's machine tries to sync FROM dennis's location, dennis's location accessor is **not available** in loren's session.

This is by architectural design - user machines cannot access each other's file systems directly. All cross-user transfers MUST route through `ftrack.server` as a bridge location.

---

## Architecture: How Cross-User Sync Should Work

### ❌ WRONG (What was attempted):
```
User A Machine (loren)
  ↓
Tries to read from: User B Location (dennis.weil@backlight.co.BL3079)
  ↓
ERROR: No accessor available!
```

### ✅ CORRECT (Two-step process):
```
Step 1: User B's machine syncs TO ftrack.server
  User B Machine (dennis) → ftrack.server
  
Step 2: User A's machine syncs FROM ftrack.server
  ftrack.server → User A Machine (loren)
```

**Key principle**: 
- Each machine can **only READ from locations with accessors available locally**
- User locations are **only accessible on their own machine**
- `ftrack.server` is accessible from **all machines** (cloud storage)

---

## Solution Implemented

### 1. Early Validation in `on_sync_to_remote()`

Added accessor validation before attempting sync:

```python
# Validate that source location has an accessor on this machine
if not source_location.accessor:
    error_msg = (
        f'Source location "{source_name}" is not accessible on this machine. '
        f'Remote-to-remote transfers are not supported. '
        f'To transfer from a remote user location, that user must initiate '
        f'the sync to ftrack.server first, then you can sync from ftrack.server '
        f'to your local location.'
    )
    logger.error(error_msg)
    
    # Create failed Job with clear explanation
    job = session.create('Job', {
        'data': json.dumps({
            'description': error_msg,
            'requested_by': requesting_user_id
        }),
        'user': session_user,
        'status': 'failed'
    })
    session.commit()
    return
```

### 2. Enhanced Error Messages in `on_sync_to_destination()`

Improved error messages to explain the two-step process:

```python
if not source_accessor:
    message = f'Source location is not accessible: {source_name}'
    hint = (
        f'The source location "{source_name}" is not available on this machine. '
        f'For remote-to-local transfers, use a two-step process: '
        f'1) Remote machine syncs to ftrack.server, then '
        f'2) Local machine syncs from ftrack.server to local'
    )
```

---

## User Workflow Guide

### Scenario: Transfer asset from User B to User A

**Goal**: User A wants to get components published by User B

**Steps**:

1. **User B syncs to ftrack.server** (on User B's machine):
   - Select asset version in ftrack UI
   - Launch "ftrack sync tool" action
   - Source: `dennis.weil@backlight.co.BL3079` (local)
   - Destination: `ftrack.server`
   - Click "Sync"
   - Wait for Job to complete (status: done)

2. **User A syncs from ftrack.server** (on User A's machine):
   - Select the SAME asset version in ftrack UI
   - Launch "ftrack sync tool" action
   - Source: `ftrack.server`
   - Destination: `loren.local` (or whatever User A's location name is)
   - Click "Sync"
   - Wait for Job to complete (status: done)

**Result**: Components are now available in User A's local location

---

## Sync Matrix

| From ↓ / To → | Local Location | ftrack.server | Remote User Location |
|---------------|----------------|---------------|----------------------|
| **Local Location** | ✅ (same machine) | ✅ Supported | ❌ Not supported |
| **ftrack.server** | ✅ Supported | ✅ (same location) | ✅ Supported (but must run on remote machine) |
| **Remote User Location** | ❌ Not supported | Must run on remote machine | ❌ Not supported |

**Legend**:
- ✅ Supported: Sync can be performed directly
- ❌ Not supported: Use two-step process through ftrack.server

---

## Technical Details

### Location Accessor Availability

**ftrack.server**:
- Always has accessor available (ServerLocation)
- Accessible from all machines
- Acts as cloud bridge storage

**User Locations** (e.g., `loren.local`, `dennis.weil@backlight.co.BL3079`):
- Accessor only available on the machine where registered
- Uses DiskAccessor pointing to local file path
- Cannot be accessed from other machines

### Event-Driven Coordination

The sync action publishes events that are picked up by the appropriate machine's Connect instance:

```python
# On User B's machine (source), after syncing to ftrack.server
session.event_hub.publish(ftrack_api.event.base.Event(
    topic='ftrack.sync',
    data={
        'actionIdentifier': 'ftrack-to-{destination_location}',
        'components': [...],
        'locations': {
            'sync': ftrack_server_id,
            'source': source_location_id,
            'destination': destination_location_id
        }
    }
))
```

The destination machine's Connect instance listens for `ftrack.sync` events matching its location name and automatically triggers the pull from ftrack.server.

---

## Files Modified

### source/ftrack_user_location/sync.py

**Changes in `on_sync_to_destination()`**:
- Enhanced error messages when source/destination accessors missing
- Added architectural explanation in error hints
- Lines: ~105-145

**Changes in `on_sync_to_remote()`**:
- Added early validation for source location accessor
- Clear error message explaining two-step process
- Job created with failure status instead of crashing
- Lines: ~455-495

---

## Testing Checklist

- [x] Source location validation catches missing accessor
- [x] Clear error message explains two-step process
- [x] Failed Job created instead of unhandled exception
- [ ] Test with actual remote user scenario:
  - [ ] User B syncs local → ftrack.server (should succeed)
  - [ ] User A syncs ftrack.server → local (should succeed)
  - [ ] User A tries to sync from User B's location directly (should fail with clear message)

---

## Future Enhancements

### Option 1: Auto-Cascade Sync (Complex)

Automatically trigger two-step sync:
1. Detect source is remote location
2. Publish event to remote machine's Connect instance
3. Remote machine syncs to ftrack.server
4. Wait for completion event
5. Local machine pulls from ftrack.server

**Challenges**:
- Requires remote machine to be online and running Connect
- Complex event choreography and timeout handling
- User has no visibility into multi-stage process

### Option 2: UI Improvement (Simpler)

Update sync action UI to prevent selecting incompatible source/destination pairs:
- Detect when source location has no local accessor
- Gray out or hide incompatible locations
- Show tooltip: "Location not available on this machine - use ftrack.server as intermediate"

**Benefits**:
- Prevents user error before it happens
- Clearer UI guidance
- Maintains simple architecture

**Recommendation**: Implement Option 2 first - preventing the error is better than handling it gracefully.

---

## Related Documentation

- **ARCHITECTURE.md**: Section "Technical Decisions → Why ftrack.server Instead of S3?"
- **PLAN.md**: Phase 5 - Future Enhancements (transparent access pattern)
- **AGENTS.md**: Section "Sync Architecture → Location Priority System"

---

## Error Message for Users

When this error occurs, users now see:

```
Job Status: Failed
Description: Source location "dennis.weil@backlight.co.BL3079" is not accessible on this machine. Remote-to-remote transfers are not supported. To transfer from a remote user location, that user must initiate the sync to ftrack.server first, then you can sync from ftrack.server to your local location.
```

**Clear, actionable, and explains the correct workflow.**

---

**Status**: ✅ FIXED - Validation added, error messages improved
**Version**: v0.3.3 (unreleased)
