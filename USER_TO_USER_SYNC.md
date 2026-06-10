# User-to-User Sync Architecture

## Overview

The ftrack User Location plugin **fully supports syncing between user machines** through an event-driven two-hop architecture that uses ftrack.server as a secure bridge.

## How It Works

### Example: User A → User B

**Scenario**: Lorenzo wants to send assets to Dennis's machine

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│  Lorenzo's  │         │   ftrack     │         │   Dennis's  │
│   Machine   │────────▶│   .server    │────────▶│   Machine   │
│ (source)    │  Hop 1  │  (bridge)    │  Hop 2  │ (dest)      │
└─────────────┘         └──────────────┘         └─────────────┘
```

### Step-by-Step Flow

1. **User Initiates Sync**
   - Lorenzo selects assets in ftrack UI
   - Lorenzo launches sync action
   - Selects: Source = `lorenzo.angeli@backlight.co.BL4006`
   - Selects: Destination = `dennis.weil@backlight.co.BL3079`

2. **Event Published (Hop 1 Request)**
   ```python
   # In sync_action.py launch() method (line 482)
   event['data']['actionIdentifier'] = 'lorenzo.angeli@backlight.co.BL3079-to-ftrack'
   session.event_hub.publish(event)
   ```
   - Event topic: `{source_location}-to-ftrack`
   - Lorenzo's machine subscribed to this pattern picks it up

3. **Source Machine Uploads (Hop 1 Execution)**
   ```python
   # Lorenzo's machine handles sync_there() event
   # Calls sync.on_sync_to_remote()
   results['sync'].add_component(component, results['input'])
   ```
   - Lorenzo's ftrack Connect processes the event
   - Uploads components from local → ftrack.server
   - Creates Job owned by Lorenzo (executor)

4. **Bridge Event Published (Hop 2 Request)**
   ```python
   # In sync.py on_sync_to_remote() after upload completes (line 677-691)
   event = ftrack_api.event.base.Event(
       topic='ftrack.sync',
       data={
           'actionIdentifier': 'ftrack-to-dennis.weil@backlight.co.BL3079',
           'components': components,
           'locations': {
               'sync': ftrack_server_id,
               'source': lorenzo_location_id,
               'destination': dennis_location_id
           }
       }
   )
   session.event_hub.publish(event)
   ```
   - Event topic: `ftrack-to-{destination_location}`
   - Dennis's machine subscribed to this pattern picks it up

5. **Destination Machine Downloads (Hop 2 Execution)**
   ```python
   # Dennis's machine handles sync_here() event
   # Calls sync.on_sync_to_destination()
   destination.add_component(component, source)
   ```
   - Dennis's ftrack Connect processes the event
   - Downloads components from ftrack.server → local
   - Creates Job owned by Dennis (executor)

## Event Subscriptions

Each machine running ftrack Connect subscribes to:

### Upload Events (Hop 1)
```python
# sync_action.py _register() (line 533)
upload_topic = 'data.actionIdentifier={location}-to-ftrack'
session.event_hub.subscribe(upload_topic, self.sync_there)
```

Examples:
- Lorenzo's machine: `lorenzo.angeli@backlight.co.BL4006-to-ftrack`
- Dennis's machine: `dennis.weil@backlight.co.BL3079-to-ftrack`

### Download Events (Hop 2)
```python
# sync_action.py _register() (line 541)
download_topic = 'topic=ftrack.sync and data.actionIdentifier=ftrack-to-{location}'
session.event_hub.subscribe(download_topic, self.sync_here)
```

Examples:
- Lorenzo's machine: `ftrack-to-lorenzo.angeli@backlight.co.BL4006`
- Dennis's machine: `ftrack-to-dennis.weil@backlight.co.BL3079`

## Why Two Hops?

### Security Benefits
- **No Direct Access**: Users never access each other's filesystems directly
- **Audit Trail**: All transfers logged through ftrack.server
- **Access Control**: ftrack.server enforces permissions

### Reliability Benefits
- **Async Operation**: Source machine doesn't need to wait for destination
- **Offline Tolerance**: If destination offline, components stay in ftrack.server
- **Cloud Backup**: ftrack.server becomes cloud backup automatically

### Operational Benefits
- **Network Firewall Friendly**: Only need outbound connections to ftrack.server
- **No VPN Required**: Users on different networks can sync
- **Bandwidth Optimization**: Smart sync checks ftrack.server first (avoids double upload)

## Smart Sync Optimization

The plugin includes smart sync logic to avoid unnecessary uploads:

```python
# In sync_action.py launch() (lines 399-492)
if source_location != 'ftrack.server' and source_location != self.location['name']:
    # Check if components already in ftrack.server
    available, total, available_ids = self.check_components_availability(
        selection, 'ftrack.server'
    )
    
    if available == total and total > 0:
        # ALL components available - skip Hop 1!
        sync.on_sync_to_destination(...)  # Direct to Hop 2
    elif available > 0:
        # PARTIAL - sync available now, request missing
        sync.on_sync_to_destination(...)  # Hop 2 for available
        event['data']['actionIdentifier'] = f'{source_location}-to-ftrack'
        session.event_hub.publish(event)  # Hop 1 for missing
```

**Benefits**:
- If assets already backed up to ftrack.server, Hop 1 skipped
- Destination can pull immediately from cloud
- Works even if source machine offline

## UI Experience

### Source Location Dropdown
Shows ALL locations including:
- ✅ `ftrack.server` (cloud backup)
- ✅ All user locations (e.g., `lorenzo.angeli@backlight.co.BL4006`)
- ❌ Excluded: `ftrack.origin`, `ftrack.unmanaged`, `ftrack.connect`, `ftrack.review`

### Destination Location Dropdown
Shows ALL locations including:
- ✅ `ftrack.server` (backup to cloud)
- ✅ All user locations (push to other users)
- ❌ Excluded: `ftrack.origin`, `ftrack.unmanaged`, `ftrack.connect`, `ftrack.review`

### Example Workflows

**Workflow 1: Backup to Cloud**
- Source: `lorenzo.angeli@backlight.co.BL4006` (local)
- Destination: `ftrack.server` (cloud)
- Result: Single hop upload

**Workflow 2: Restore from Cloud**
- Source: `ftrack.server` (cloud)
- Destination: `lorenzo.angeli@backlight.co.BL4006` (local)
- Result: Single hop download

**Workflow 3: Send to Colleague** (Two Hops)
- Source: `lorenzo.angeli@backlight.co.BL4006` (Lorenzo's local)
- Destination: `dennis.weil@backlight.co.BL3079` (Dennis's local)
- Result: Hop 1 (Lorenzo → ftrack.server) + Hop 2 (ftrack.server → Dennis)

**Workflow 4: Pull from Colleague** (Smart Sync)
- Source: `dennis.weil@backlight.co.BL3079` (Dennis's local)
- Destination: `lorenzo.angeli@backlight.co.BL4006` (Lorenzo's local)
- Smart Sync checks ftrack.server first:
  - If available: Direct download (Hop 2 only)
  - If not available: Request from Dennis (Hop 1) then download (Hop 2)

## Logging

Each hop creates separate logs on the executing machine:

### Hop 1 Logs (Source Machine)
```
[sync_there] Received sync event [actionIdentifier=lorenzo.angeli@backlight.co.BL4006-to-ftrack]
Starting remote sync operation [executor=lorenzo.angeli, source=lorenzo.angeli@backlight.co.BL4006, destination=dennis.weil@backlight.co.BL3079]
Job created for remote sync [job_id=xxx, job_owner=lorenzo.angeli]
Processing component [component=scene.ma]
Publishing sync event for remote destination [destination=dennis.weil@backlight.co.BL3079]
```

### Hop 2 Logs (Destination Machine)
```
[sync_here] Received ftrack.sync event [actionIdentifier=ftrack-to-dennis.weil@backlight.co.BL3079]
Starting sync operation [executor=dennis.weil, destination=dennis.weil@backlight.co.BL3079]
Job created [job_id=yyy, job_owner=dennis.weil]
Processing component [component=scene.ma]
Component synced successfully [component=scene.ma]
```

## Job Ownership

Critical for multi-user workflows:

### Hop 1 Job
- **Owner**: Source user (Lorenzo)
- **Created by**: Lorenzo's session
- **Visible to**: Lorenzo in ftrack UI
- **Reports**: Upload success/failure

### Hop 2 Job
- **Owner**: Destination user (Dennis)
- **Created by**: Dennis's session
- **Visible to**: Dennis in ftrack UI
- **Reports**: Download success/failure

Both users see their own Job showing their part of the operation.

## Troubleshooting

### Components Not Arriving at Destination

**Check Hop 1 Succeeded**:
1. Check source user's Job in ftrack UI
2. Verify status = 'done'
3. Check components uploaded to ftrack.server:
   ```python
   location = session.query('Location where name is "ftrack.server"').first()
   availability = location.get_component_availability(component)
   # Should be 100.0
   ```

**Check Hop 2 Triggered**:
1. Check source machine logs for:
   ```
   Publishing sync event for remote destination [destination=dennis.weil@backlight.co.BL3079]
   ```
2. Check destination machine logs for:
   ```
   [sync_here] Received ftrack.sync event
   ```

**Check Destination Machine Running**:
- ftrack Connect must be running on destination machine
- Check destination user logged in and Connect active

### Event Not Picked Up

**Wrong Machine Handling Event**:
```
[sync_there] Event routing mismatch! This machine has location 'lorenzo.angeli@backlight.co.BL4006' 
but event is for 'dennis.weil@backlight.co.BL3079'
```
- Event delivered to wrong machine
- Ensure ftrack Connect running on **source** machine

**No Accessor Error**:
```
ERROR: Source location "dennis.weil@backlight.co.BL3079" is not accessible on this machine
```
- Event routed to wrong machine
- Check actionIdentifier matches location name

## Architecture Summary

✅ **Fully Supports User-to-User Sync**
✅ **Two-Hop Architecture** (Source → ftrack.server → Destination)
✅ **Event-Driven** (async, reliable, offline-tolerant)
✅ **Smart Sync** (checks cloud first, avoids unnecessary uploads)
✅ **Secure** (no direct user-to-user access)
✅ **Per-Hop Jobs** (each user sees their own Job)
✅ **Cloud Backup** (ftrack.server automatically becomes backup)

The system is **production-ready** for user-to-user workflows! 🎯
