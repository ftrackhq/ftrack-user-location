# Logging Guide - ftrack User Location v0.3.4

**Log File Location**: `%APPDATA%\Local\ftrack\ftrack-connect\log\ftrack_user_location.log`

---

## What You'll See in the Logs

### 1. Plugin Initialization

```
[register] User location plugin initializing
[register] Subscribing to ftrack.api.session.configure-location event
[register] User location plugin registered successfully
```

**If disabled** (FTRACK_USER_MAIN_LOCATION set):
```
[register] FTRACK_USER_MAIN_LOCATION is set - User location disabled (main studio mode)
```

---

### 2. Location Configuration

```
[configure_location] Starting location configuration
[configure_location] Session user: loren
[configure_location] Server URL: https://backlight.ftrackapp.com
[configure_location] Server folder name: backlight
[configure_location] Location path: C:\Users\loren\Documents\local_ftrack_projects\backlight
[configure_location] Location name: loren.BL3079
[configure_location] Found existing location: abc-123-def
[configure_location] ✅ Registered location: loren.BL3079 @ C:\Users\loren\Documents\local_ftrack_projects\backlight with priority -9223372036854775805
[configure_location] Location configuration complete [name=loren.BL3079, id=abc-123-def, accessor=DiskAccessor, structure=StandardStructure]
```

**Custom Environment Variables**:
```
[configure_location] Using custom path from FTRACK_USER_LOCATION_PATH: D:\ftrack_projects
[configure_location] Using custom location name from FTRACK_USER_LOCATION_NAME: custom.location
```

---

### 3. Action Registration

```
[_register] Registering sync action for location: loren.BL3079
[_register] Subscribed to: topic=ftrack.action.discover
[_register] Subscribed to: topic=ftrack.action.launch and data.actionIdentifier=ftrack-sync-action and data.location="loren.BL3079"
[_register] Found 2 accessible locations on this machine: ['loren.BL3079', 'ftrack.server']
[_register] Subscribed to UPLOAD events: data.actionIdentifier=loren.BL3079-to-ftrack (will handle uploads from loren.BL3079)
[_register] Subscribed to DOWNLOAD events: topic=ftrack.sync and data.actionIdentifier=ftrack-to-loren.BL3079 (will handle downloads to loren.BL3079)
[_register] Subscribed to UPLOAD events: data.actionIdentifier=ftrack.server-to-ftrack (will handle uploads from ftrack.server)
[_register] Subscribed to DOWNLOAD events: topic=ftrack.sync and data.actionIdentifier=ftrack-to-ftrack.server (will handle downloads to ftrack.server)
```

**Key Information**:
- See which locations have accessors on this machine
- See exact event subscription patterns
- Verify event routing will work correctly

---

### 4. Action Launch (User Triggers Sync)

```
Sync action launched from location loren.BL3079
Publishing sync event: dennis.weil@backlight.co.BL3079 → ftrack.server (triggered by loren.BL3079)
```

**What This Tells You**:
- User (loren) triggered sync FROM dennis's location
- Event will be published with actionIdentifier: `dennis.weil@backlight.co.BL3079-to-ftrack`
- Dennis's machine should pick it up (not loren's)

---

### 5. Upload Event Received (sync_there)

```
[sync_there] Received sync event [actionIdentifier=dennis.weil@backlight.co.BL3079-to-ftrack, location=dennis.weil@backlight.co.BL3079]
[sync_there] Starting sync: dennis.weil@backlight.co.BL3079 → ftrack.server [asset_versions=3, user=loren-user-id]
```

**From sync.py**:
```
Starting remote sync operation [executor=dennis, requesting_user=loren, source=dennis.weil@backlight.co.BL3079, destination=ftrack.server, asset_version_count=3]
Job created for remote sync [job_id=job-123, job_owner=dennis, source=dennis.weil@backlight.co.BL3079, destination=ftrack.server]
Processing component [job_id=job-123, component=scene_v001.ma, component_id=comp-123]
Component synced successfully [job_id=job-123, component=scene_v001.ma, component_id=comp-123, destination=ftrack.server]
Generating sync report [job_id=job-123, synced=19, skipped=5, failed=1]
Remote sync operation completed [job_id=job-123, status=done, total_components=25, succeeded=19, skipped=5, failed=1, duration_seconds=45.23, components_per_second=0.55]
```

**If Event Routing Error** (event delivered to wrong machine):
```
[sync_there] Event routing mismatch! This machine has location 'loren.BL3079' but event is for 'dennis.weil@backlight.co.BL3079'. This should not happen!
ERROR: Source location "dennis.weil@backlight.co.BL3079" is not accessible on this machine (loren). This sync event was delivered to the wrong machine!
```

---

### 6. Download Event Received (sync_here)

```
[sync_here] Received ftrack.sync event [actionIdentifier=ftrack-to-loren.BL3079, location=loren.BL3079]
[sync_here] Starting sync: ftrack.server → loren.BL3079 [components=25, user=loren-user-id]
```

**From sync.py**:
```
Starting sync operation [executor=loren, requesting_user_id=loren-user-id, source=ftrack.server, destination=loren.BL3079, component_count=25]
Job created [job_id=job-456, job_owner=loren]
Checking component availability [job_id=job-456, component=scene_v001.ma, source_avail=100%, dest_avail=0%]
Copying component [job_id=job-456, component=scene_v001.ma, source=ftrack.server, destination=loren.BL3079]
Component synced successfully [job_id=job-456, component=scene_v001.ma, component_id=comp-123]
Generating sync report [job_id=job-456, synced=25, skipped=0, failed=0]
Sync operation completed [job_id=job-456, status=done, total_components=25, succeeded=25, skipped=0, failed=0, duration_seconds=23.45, components_per_second=1.07, report_attached=True]
```

---

### 7. Success Messages

```
[sync_there] Sync completed successfully
[sync_here] Sync completed successfully
```

---

### 8. Error Messages

**Upload Failed**:
```
[sync_there] Sync failed: Failed to transfer component
ERROR: Component sync failed [job_id=job-123, component=scene_v001.ma, component_id=comp-123, error_type=LocationError, error=No accessor defined for source location]
Traceback (most recent call last):
  File "...", line 426, in on_sync_to_remote
    ...
```

**Download Failed**:
```
[sync_here] Sync failed: Connection timeout
ERROR: Component sync failed [job_id=job-456, component=texture_01.png, component_id=comp-456, error_type=TimeoutError, error=Request timed out after 60s]
```

---

## Debugging Common Issues

### Issue: Cross-User Sync Not Working

**Check:**
1. Both machines show location registration:
   ```
   [configure_location] ✅ Registered location: user.machine
   ```

2. Both machines subscribed to correct events:
   ```
   [_register] Subscribed to UPLOAD events: data.actionIdentifier=user.machine-to-ftrack
   ```

3. Event published with correct actionIdentifier:
   ```
   Publishing sync event: dennis.weil@backlight.co.BL3079 → ftrack.server
   ```

4. Correct machine received the event:
   ```
   [sync_there] Received sync event [actionIdentifier=dennis.weil@backlight.co.BL3079-to-ftrack, location=dennis.weil@backlight.co.BL3079]
   ```

**If Event Routing Mismatch**:
```
[sync_there] Event routing mismatch! This machine has location 'loren.BL3079' but event is for 'dennis.weil@backlight.co.BL3079'
```
→ Event delivered to wrong machine. Check ftrack Connect is running on source machine.

---

### Issue: No Logs Being Written

**Check:**
1. Log file location:
   ```
   %LOCALAPPDATA%\ftrack\ftrack-connect\log\ftrack_user_location.log
   ```

2. Plugin initialized:
   ```
   [register] User location plugin initializing
   ```

3. If nothing logged, plugin may not be installed correctly or Connect not loading it.

---

### Issue: Location Not Accessible

**Check:**
1. Location registered:
   ```
   [configure_location] ✅ Registered location: name @ path
   ```

2. Accessible locations on machine:
   ```
   [_register] Found 2 accessible locations on this machine: ['user.local', 'ftrack.server']
   ```

3. If location missing from list, it doesn't have an accessor on this machine.

---

### Issue: Components Failing to Sync

**Check:**
1. Component availability:
   ```
   Checking component availability [component=scene.ma, source_avail=100%, dest_avail=0%]
   ```

2. If source_avail=0%:
   ```
   Component not available in source [component=scene.ma, source=user.local]
   ```
   → Component not published to source location

3. If sync fails:
   ```
   Component sync failed [component=scene.ma, error_type=IOError, error=No space left on device]
   ```
   → Check disk space, permissions, network

---

### Issue: Slow Sync Performance

**Check:**
1. Duration metrics:
   ```
   Sync operation completed [duration_seconds=180.45, components_per_second=0.55]
   ```

2. If components_per_second < 0.5, investigate:
   - Network speed
   - Component sizes
   - Disk performance

3. Expected performance:
   - 100 components in <2 minutes = 0.83 components/sec

---

## Log File Management

**Location**: `%LOCALAPPDATA%\ftrack\ftrack-connect\log\ftrack_user_location.log`

**Rotation**:
- Max size: 10 MB
- Backup count: 5
- Old logs: `ftrack_user_location.log.1`, `.2`, `.3`, etc.

**Manual Cleanup**:
```powershell
# View current log
Get-Content "$env:LOCALAPPDATA\ftrack\ftrack-connect\log\ftrack_user_location.log" -Tail 50

# Delete old logs
Remove-Item "$env:LOCALAPPDATA\ftrack\ftrack-connect\log\ftrack_user_location.log.*"
```

---

## Log Levels

**DEBUG**: Detailed technical information
- Event data payloads
- Environment variable checks
- Hostname adjustments

**INFO**: Normal operations
- Plugin initialization
- Location registration
- Event subscriptions
- Sync operations
- Component processing

**WARNING**: Unexpected but handled situations
- Configuration overrides
- Event routing mismatches
- Components already exist

**ERROR**: Failures requiring attention
- Sync failures
- Component errors
- Location not accessible
- Full stack traces

---

## Quick Reference: Log Prefixes

| Prefix | Source | What It Logs |
|--------|--------|--------------|
| `[register]` | user_location.py | Plugin initialization |
| `[configure_location]` | user_location.py | Location setup |
| `[_register]` | sync_action.py | Action registration |
| `[sync_there]` | sync_action.py | Upload events |
| `[sync_here]` | sync_action.py | Download events |
| (no prefix) | sync.py | Sync engine operations |

**Filter by prefix**:
```powershell
# Show only event routing logs
Select-String "\[sync_there\]|\[sync_here\]" "$env:LOCALAPPDATA\ftrack\ftrack-connect\log\ftrack_user_location.log"

# Show only registration
Select-String "\[register\]|\[_register\]" "$env:LOCALAPPDATA\ftrack\ftrack-connect\log\ftrack_user_location.log"
```

---

**Now you have complete visibility into everything the plugin does!** 🎯
