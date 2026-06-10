# README.md Update Draft for v0.5.0

## Section: "Recent Improvements" - Replace entire section

### Version 0.5.0 - Single Unified Sync Action

**Major UX Improvement**:
- Single "ftrack sync tool" action for all users (no more per-machine duplicates)
- Event-based remote commanding: any user can command any location
- Clean UI: all locations visible in source/destination dropdowns
- Real-time online status: `[ONLINE]` / `[OFFLINE]` indicators via ping/pong

**How It Works**:
```
User Flow:
1. Click "ftrack sync tool" (single action in UI)
2. Select source location (e.g., dennis.weil@... [ONLINE])
3. Select destination location (e.g., your local machine)
4. Click Sync

Event System:
- Your Connect publishes event to Dennis's location
- Dennis's Connect receives and executes (already subscribed)
- Dennis uploads to ftrack.server
- Your Connect downloads from ftrack.server
→ Remote commanding via events - no direct file access needed!
```

**Architecture**:
- Each Connect subscribes to `{location_name}-to-ftrack` events at startup
- Any Connect can publish to any location's event topic
- Two-hop sync pattern: Remote → ftrack.server → Requester (mandatory)
- Security maintained: each machine uses its own file permissions

**Previous Versions**:

### Version 0.4.0 - Presence Detection
- Ping/pong event system checks if remote locations are online
- 2-second timeout for status checks
- Shows real-time availability in sync UI

### Version 0.3.2 - Critical Bug Fixes
**Multi-User Support** (Critical Fix):
- Fixed cross-user permission errors that blocked all remote collaboration workflows
- Jobs now owned by executor (machine performing the work), not the requester
- Enables User A to trigger syncs on User B's machine without permission errors

**Performance** (5-10x Improvement):
- Batch database commits: 2 commits per sync operation (previously 200+)
- 100 components now sync in <2 minutes (previously 5-10 minutes)
- Optimized for large asset versions with many components

**Reliability**:
- Fixed "job has to be committed first" errors during Job updates
- Proper Job lifecycle management following official ftrack patterns
- Failed components tracked separately from successful ones
- Job status accurately reflects sync results

---

## Section: "How to set it up" - Add before "Environment variables"

### Multi-User Collaboration Setup

**For Remote Teams**:
1. Install plugin on **all** team members' machines
2. Each machine registers its own location: `{username}.{hostname}`
3. All team members see the **same single action**: "ftrack sync tool"
4. Source/destination dropdowns show all available locations
5. Online status indicators show which remote machines are available

**Two-Hop Sync Pattern**:
- All user-to-user transfers go through ftrack.server (cloud storage)
- Example: User A → ftrack.server → User B (two steps, mandatory)
- No direct filesystem access between machines
- Firewall-friendly: only event system + HTTPS to ftrack server

**Studio vs Remote**:
- **Studio machines**: Set `FTRACK_USER_MAIN_LOCATION` to disable plugin
- **Remote artists**: Leave unset to enable user location
- Studio central storage takes priority when plugin is disabled

---

## Section: "Checking is all setup" - Update step 2

2.  Execute actions on an AssetVersion and select the **ftrack sync
    tool** (single action, no machine name in variant)
3.  **Check online status**: Remote locations show `[ONLINE]` if Connect is running
4.  **Test remote commanding**: Select a remote location as source, your location as destination
5.  Sync executes on remote machine automatically via events

---

## New Section: "Troubleshooting" - Add at end

## Troubleshooting

### Remote Location Shows [OFFLINE] but Connect is Running

**Solution**: Ensure both machines have v0.4.0+ installed for ping/pong support.

**Check**:
- Both machines running ftrack Connect
- Plugin version 0.4.0 or higher on both machines
- Network allows WebSocket connections to ftrack server

### Sync Fails with "No components available"

**Cause**: Source location doesn't have the components locally.

**Solution**:
1. Check source location has published the asset version
2. Verify component availability with ftrack UI (component tab)
3. Try syncing from ftrack.server if available there

### Action Appears Multiple Times (Pre-v0.5.0)

**Fixed in v0.5.0**: Single unified action for all users.

**Workaround for older versions**: Each action variant represents a different machine. Click the action for the machine you want to execute on.

### Permission Errors (Pre-v0.3.2)

**Fixed in v0.3.2**: Jobs owned by executor, not requester.

**Update to v0.3.2+** to resolve cross-user permission errors.

---

## New Section: "Architecture" - Add before "Troubleshooting"

## Architecture

### Event-Driven Design

The plugin uses ftrack's event system for all inter-machine communication:

**Event Topics**:
- `ftrack.location.ping.{location}` - Presence detection request
- `ftrack.location.ping.response.{location}` - Presence detection response
- `{location}-to-ftrack` - Upload request from location to ftrack.server
- `ftrack-to-{location}` - Download request from ftrack.server to location

**Lifecycle**:
1. **Registration**: Each Connect subscribes to events at startup
2. **Discovery**: Single action shows for all users (session user filter prevents duplicates)
3. **Interface**: UI displays all locations with online status
4. **Launch**: Event published to source location for upload
5. **Execution**: Remote machine uploads to ftrack.server
6. **Completion**: Requesting machine downloads from ftrack.server

### Location Priority

User locations use priority `-sys.maxsize` (highest possible) to override central storage.

**Priority Order** (lowest number = highest priority):
1. User locations: `-9223372036854775806`
2. Central storage: `1-100` (typical)
3. ftrack.server: `100` (default)
4. ftrack.origin: `200` (lowest)

### Security Model

- **No direct P2P access**: All transfers go through ftrack.server
- **Permission isolation**: Each machine uses its own OS-level file permissions
- **Job ownership**: Executor owns the Job (not the requester)
- **Event routing**: ftrack server routes events between Connects
- **Authentication**: Each Connect uses its own API credentials

---

## End of Draft
