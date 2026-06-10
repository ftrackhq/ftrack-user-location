# Event Routing Fix - Cross-User Sync Architecture

**Issue Date**: 2026-06-10  
**Root Cause**: Event actionIdentifier used wrong location  
**Status**: ✅ FIXED

---

## Problem

When User A (loren) tried to sync FROM User B's location (dennis.weil@backlight.co.BL3079) to ftrack.server:

```
❌ Event published: loren.local-to-ftrack
❌ Picked up by: loren's machine
❌ Tries to sync FROM: dennis.weil@backlight.co.BL3079 (no accessor!)
❌ Result: LocationError - "No accessor defined for source location"
```

**Root Cause**: The event actionIdentifier always used the **triggering user's location** (`self.location['name']`), not the **source location** selected in the form.

---

## Architecture: How Event-Driven Cross-User Sync Works

### Correct Flow

**User A wants files from User B's machine:**

```
1. User A (loren) opens ftrack UI
   ↓
2. Selects AssetVersion, launches "ftrack sync tool" action
   ↓
3. Fills form:
   - Source: dennis.weil@backlight.co.BL3079
   - Destination: ftrack.server
   ↓
4. Clicks "Sync" button
   ↓
5. loren's Connect publishes event:
   topic: (action event)
   actionIdentifier: "dennis.weil@backlight.co.BL3079-to-ftrack"
   ↓
6. Event hub broadcasts to ALL Connect instances
   ↓
7. Dennis's Connect instance picks it up (subscribed to that identifier)
   ↓
8. Dennis's machine executes sync:
   on_sync_to_remote(source="dennis.weil@backlight.co.BL3079", dest="ftrack.server")
   ↓
9. Success! Dennis's local files → ftrack.server
   ↓
10. Dennis's machine publishes completion event:
    topic: "ftrack.sync"
    actionIdentifier: "ftrack-to-loren.local"
    ↓
11. loren's Connect picks it up
    ↓
12. loren's machine executes sync:
    on_sync_to_destination(source=ftrack.server, dest=loren.local)
    ↓
13. Success! ftrack.server → loren's local
```

**Key Principle**: The machine that OWNS the source location must be the one executing the upload.

---

## The Fix

### File: resource/hook/sync_action.py

**Before (WRONG)**:
```python
def launch(self, session, entities, event):
    # ... form handling ...
    
    # BUG: Always uses self.location (the triggering user's location)
    event['data']['actionIdentifier'] = '{}-to-ftrack'.format(self.location['name'])
    self.session.event_hub.publish(event)
```

**After (CORRECT)**:
```python
def launch(self, session, entities, event):
    # ... form handling ...
    
    # FIX: Use SOURCE location from form, not self.location
    source_location = event['data']['values']['source_location']
    event['data']['actionIdentifier'] = '{}-to-ftrack'.format(source_location)
    
    self.logger.info(
        f"Publishing sync event: {source_location} → ftrack.server "
        f"(triggered by {self.location['name']})"
    )
    self.session.event_hub.publish(event)
    
    return {
        'success': True,
        'message': f'Sync request published: {source_location} → ftrack.server (will be executed by remote machine)'
    }
```

### What Changed

1. **Event actionIdentifier**: Now uses `source_location` from form values, not `self.location['name']`
2. **Logging**: Added context showing who triggered it vs. who will execute it
3. **User message**: Clarifies that remote machine will execute (user doesn't need to be at that machine)

---

## Event Subscription Pattern

Each Connect instance subscribes to events for locations it has accessors for:

```python
# In sync_action.py _register()
for location in self.get_locations():
    if location.accessor:  # Only subscribe if we have local access
        # Subscribe to: "this-location-to-ftrack" events
        self.session.event_hub.subscribe(
            'data.actionIdentifier={0}-to-ftrack'.format(location['name']),
            self.sync_there  # Uploads FROM local TO ftrack.server
        )
        
        # Subscribe to: "ftrack-to-this-location" events
        self.session.event_hub.subscribe(
            'topic=ftrack.sync and data.actionIdentifier=ftrack-to-{0}'.format(location['name']),
            self.sync_here  # Downloads FROM ftrack.server TO local
        )
```

**Example Subscriptions**:

**Dennis's machine**:
- `dennis.weil@backlight.co.BL3079-to-ftrack` → uploads his files
- `ftrack-to-dennis.weil@backlight.co.BL3079` → downloads to his machine

**Loren's machine**:
- `loren.local-to-ftrack` → uploads his files
- `ftrack-to-loren.local` → downloads to his machine

---

## Two-Step Sync Process

### Step 1: Upload to ftrack.server (Event-Driven)

**Triggered by**: Any user via ftrack UI  
**Executed by**: Machine that owns the source location  
**Event**: `{source_location}-to-ftrack`  
**Function**: `sync_there()` → `on_sync_to_remote()`

```python
# Dennis's machine receives event and executes:
sync.on_sync_to_remote(
    session=session,
    source='dennis.weil@backlight.co.BL3079',  # Has accessor locally!
    destination='ftrack.server',
    requesting_user_id='loren-user-id',
    selection=[...]
)
```

### Step 2: Download from ftrack.server (Auto-Triggered)

**Triggered by**: Completion of Step 1 (event published by source machine)  
**Executed by**: Destination machine  
**Event**: `ftrack.sync` with actionIdentifier=`ftrack-to-{destination_location}`  
**Function**: `sync_here()` → `on_sync_to_destination()`

```python
# Loren's machine receives event and executes:
sync.on_sync_to_destination(
    session=session,
    source_id='ftrack.server-id',
    destination_id='loren.local-id',
    components=[...],
    requesting_user_id='loren-user-id'
)
```

---

## Validation & Error Handling

### In on_sync_to_remote()

Added validation that should only trigger if event routing fails:

```python
if not source_location.accessor:
    error_msg = (
        f'ERROR: Source location "{source_name}" is not accessible on this machine. '
        f'This sync event was delivered to the wrong machine! '
        f'The event should have been picked up by the machine running Connect '
        f'for location "{source_name}". '
        f'Please ensure ftrack Connect is running on the machine that owns this location.'
    )
    # Create failed Job with explanation
    # ...
```

This catches:
- Connect not running on source machine
- Event hub delivery issues
- Location name mismatches

---

## User Experience

### Before Fix

```
User A: Selects source=User B's location, destination=ftrack.server
User A: Clicks "Sync"
System: ✅ Message: "Sync launched"
User A's Machine: ❌ ERROR: No accessor for User B's location
Job Status: No job created, or crashes
User Experience: Confusing - looks successful but fails
```

### After Fix

```
User A: Selects source=User B's location, destination=ftrack.server
User A: Clicks "Sync"
System: ✅ Message: "Sync request published: User B's location → ftrack.server 
                     (will be executed by remote machine)"
User B's Machine: 📡 Receives event
User B's Machine: ✅ Executes sync (files uploaded)
User B's Machine: 📡 Publishes completion event
User A's Machine: 📡 Receives completion event
User A's Machine: ✅ Downloads from ftrack.server
Job Status: Two jobs created (upload + download), both visible in ftrack UI
User Experience: Clear - sees sync request sent, waits for completion
```

---

## Requirements for Cross-User Sync

1. **Both machines must be running ftrack Connect** with the user-location plugin installed
2. **Both machines must be connected** to the same ftrack server
3. **Event hub connectivity** - both machines subscribing to events
4. **Source machine must be online** when upload is triggered (User B's machine, in our example)

**Important**: The user (Dennis) does NOT need to be at his machine or interacting with it. As long as:
- His machine is powered on
- ftrack Connect is running
- Network connectivity is good

...the sync will execute automatically via the event system.

---

## Testing Scenarios

### Scenario 1: Normal Cross-User Sync

**Setup**:
- Dennis's machine: Online, Connect running
- Loren's machine: Online, Connect running

**Steps**:
1. Loren selects source=dennis.weil@backlight.co.BL3079, dest=ftrack.server
2. Clicks Sync

**Expected**:
- ✅ Event published with actionIdentifier=`dennis.weil@backlight.co.BL3079-to-ftrack`
- ✅ Dennis's machine picks up event
- ✅ Dennis's machine syncs files to ftrack.server
- ✅ Upload Job created and visible in ftrack UI
- ✅ Completion event published
- ✅ Loren's machine downloads from ftrack.server (if destination was loren.local)

### Scenario 2: Source Machine Offline

**Setup**:
- Dennis's machine: Offline or Connect not running
- Loren's machine: Online, Connect running

**Steps**:
1. Loren selects source=dennis.weil@backlight.co.BL3079, dest=ftrack.server
2. Clicks Sync

**Expected**:
- ✅ Event published successfully
- ⏳ Event waits in hub (no subscriber)
- ⏰ Eventually times out (no response)
- ❌ No Job created (source machine never received event)

**User Experience**: Request sent but nothing happens (Dennis's machine must be online)

### Scenario 3: Wrong Event Routing (Pre-Fix Behavior)

**Setup**:
- Event published with actionIdentifier=`loren.local-to-ftrack` (WRONG)
- Loren's machine picks it up instead of Dennis's

**Steps**:
1. on_sync_to_remote() called on loren's machine
2. Tries to access dennis.weil@backlight.co.BL3079
3. Validation: `if not source_location.accessor`

**Expected**:
- ✅ Validation catches the error
- ✅ Failed Job created with clear explanation
- ✅ Error message explains event routing issue

---

## Files Modified

### 1. resource/hook/sync_action.py

**Function**: `launch()`  
**Lines**: ~252-258  
**Change**: Use source_location in actionIdentifier instead of self.location

### 2. source/ftrack_user_location/sync.py

**Function**: `on_sync_to_remote()`  
**Lines**: ~451-478  
**Change**: Enhanced error message for event routing failures

---

## Benefits

1. **Cross-user sync works correctly** - Event routed to machine with accessor
2. **No user intervention required** - Dennis doesn't need to be at his machine
3. **Clear user feedback** - Message explains remote execution
4. **Error detection** - Catches event routing failures
5. **Audit trail** - Both upload and download Jobs visible in ftrack UI

---

## Related Documentation

- **REMOTE_LOCATION_ERROR_FIX.md**: Original error analysis (now outdated - this doc supersedes it)
- **ARCHITECTURE.md**: Event hub and location architecture
- **AGENTS.md**: Sync flow diagrams

---

## Technical Notes

### Why Event Hub?

ftrack's event hub allows **distributed execution** where:
- Multiple Connect instances run on different machines
- Each subscribes to events relevant to its location
- Events broadcast to all subscribers
- The right machine picks up the work

This is essential for:
- Remote workflows (users at different locations)
- Unattended execution (user doesn't need to be at machine)
- Background processing (Connect runs as service)

### Event Delivery Guarantees

ftrack event hub provides:
- **At-least-once delivery** - Events may be redelivered
- **No ordering guarantee** - Events may arrive out of order
- **Subscription filtering** - Only matching subscribers receive events

This means:
- Sync operations must be **idempotent** (safe to retry)
- Use Job status to track completion (not event order)
- Handle "already exists" gracefully (component already synced)

---

**Status**: ✅ FIXED - Event routing corrected
**Version**: v0.3.3 (unreleased)
**Commit**: (pending)
