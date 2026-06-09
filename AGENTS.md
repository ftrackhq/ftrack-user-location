# Agents

## Overview

This document describes the ftrack Connect plugin architecture and how it operates as an agent within the ftrack ecosystem.

## Plugin Agent Role

The ftrack User Location plugin acts as a **location registration agent** and **sync orchestration agent** within ftrack Connect. It does not run as a standalone service but integrates into ftrack Connect's plugin system.

## Agent Types

### 1. Location Registration Agent

**Purpose**: Automatically registers user-specific locations when ftrack Connect starts.

**Lifecycle**:
- Activated on `ftrack.api.session.configure-location` event
- Runs once per ftrack session initialization
- Registers location for current user/hostname combination

**Behavior**:
- Checks `FTRACK_USER_MAIN_LOCATION` environment variable
- If **not set**: Registers user location (`{username}.{hostname}`)
- If **set**: Skips registration (allows central storage to take precedence)

**Location Properties**:
```python
{
    'name': '{api_user}.{hostname}',
    'priority': 1 - sys.maxsize,  # Highest priority
    'accessor': DiskAccessor(prefix=local_path),
    'structure': StandardStructure()
}
```

### 2. Sync Action Agent

**Purpose**: Provides interactive sync capabilities through ftrack UI.

**Lifecycle**:
- Registered on `ftrack.api.session.ready` event
- Listens for action discovery and launch events
- Remains active throughout ftrack Connect session

**Discovery Phase**:
- Subscribes to: `topic=ftrack.action.discover`
- Discovers on: AssetVersion entities only
- Returns action variant per location: `Sync @ {location_name}`

**Launch Phase**:
- Subscribes to: `topic=ftrack.action.launch and data.actionIdentifier=ftrack.fsync`
- Presents UI form with source/destination location dropdowns
- Publishes sync event to event hub

### 3. Sync Execution Agent

**Purpose**: Executes component transfers between locations.

**Lifecycle**:
- Subscribes to sync events: `data.actionIdentifier={location}-to-ftrack`
- Runs asynchronously via event hub
- Creates ftrack Job to track progress

**Sync Algorithm**:
```
1. Validate source and destination locations exist
2. Create Job entity (status='running')
3. For each component:
   a. Check availability in source (skip if 0%)
   b. Check availability in destination (skip if 100%)
   c. Copy component: destination.add_component(component, source)
   d. Update Job status
4. Set Job status='done' or 'failed'
5. Publish completion event
```

**Event Flow**:
```
User Action → Launch Event → Build Sync Event → 
Publish {location}-to-ftrack → Sync Agent → 
Copy Components → Publish ftrack.sync → 
Destination Agent → Complete
```

## Agent Configuration

### Environment Variables

Agents respect the following configuration:

| Variable | Effect | Default |
|----------|--------|---------|
| `FTRACK_USER_MAIN_LOCATION` | When set, location registration agent is **disabled** | Not set (agent enabled) |
| `FTRACK_USER_LOCTION_NAME` | Overrides location name | `{api_user}.{hostname}` |
| `FTRACK_USER_LOCTION_PATH` | Overrides storage path | `~/Documents/local_ftrack_projects/{server}/` |

### Deployment Modes

**Mode 1: Remote Worker**
- User working remotely with local storage
- Configuration: No environment variables needed
- Result: Location registered, sync enabled

**Mode 2: Studio Worker**
- User in main studio with central storage
- Configuration: `FTRACK_USER_MAIN_LOCATION=1`
- Result: Location NOT registered, central storage takes priority

**Mode 3: Custom Location**
- User with custom location name/path
- Configuration:
  ```bash
  FTRACK_USER_LOCTION_NAME=custom-location
  FTRACK_USER_LOCTION_PATH=/mnt/custom/path
  ```
- Result: Location registered with custom settings

## Agent Communication

### Event Hub Integration

All agents communicate via ftrack's event hub (WebSocket-based):

**Published Events**:
- `{location}-to-ftrack` - Triggers sync from location to ftrack.server
- `ftrack.sync` - Signals sync completion with component metadata

**Subscribed Events**:
- `ftrack.api.session.configure-location` - Location registration
- `ftrack.api.session.ready` - Action registration
- `ftrack.action.discover` - Action UI discovery
- `ftrack.action.launch` - Action execution
- `ftrack.connect.application.launch` - DCC environment modification

### DCC Integration

Agents modify launched DCC application environments:

```python
# Injects location plugin paths into:
environment['FTRACK_EVENT_PLUGIN_PATH'] += location_directory
environment['PYTHONPATH'] += location_directory
```

This allows DCCs to discover and use the registered locations.

## Agent Behavior

### Ignored Locations

Sync agents skip these built-in ftrack locations:
- `ftrack.origin`
- `ftrack.server`
- `ftrack.unmanaged`
- `ftrack.connect`
- `ftrack.review`

### Component Filtering

Sync agents filter out components with names containing:
- `ftrackreview` - Review proxies (managed separately)

### Error Handling

Agents use Job entities for user-visible error reporting:

```python
job['status'] = 'failed'
job['data'] = json.dumps({
    'description': 'Component not available in source'
})
```

## Multi-Agent Scenarios

### Scenario 1: Two Remote Users Syncing

```
User A (remote) → ftrack.server → User B (remote)
```

1. User A publishes to `userA.laptop` location
2. User A runs sync action: `userA.laptop → ftrack.server`
3. Sync agent uploads to ftrack.server
4. User B runs sync action: `ftrack.server → userB.desktop`
5. Sync agent downloads from ftrack.server

### Scenario 2: Remote to Studio

```
User A (remote) → ftrack.server ← Studio (central storage)
```

1. User A publishes to `userA.home` location
2. User A runs sync action: `userA.home → ftrack.server`
3. Studio Connect (with `FTRACK_USER_MAIN_LOCATION=1`) accesses ftrack.server directly
4. No location agent registered on studio machines

## Monitoring and Debugging

### Job Tracking

All sync operations create Job entities visible in ftrack UI:
- Real-time progress updates
- Component-level status messages
- Success/failure indicators

### Logging

Agents log to ftrack Connect logs:
```python
logger = logging.getLogger('ftrack_user_location')
logger.info('Registering location: {}'.format(location_name))
```

### Event Inspection

Monitor event hub traffic using ftrack Connect's event debugging tools or subscribe to all events:

```python
session.event_hub.subscribe('topic=*', lambda event: print(event))
```

## Agent Limitations

1. **No Direct Location-to-Location Sync**: Always goes through ftrack.server as intermediate
2. **Sequential Component Processing**: Components sync one at a time (no parallelization)
3. **No Delta Sync**: Always copies full components (no incremental updates)
4. **Single Session**: Each ftrack Connect instance runs independent agents (no coordination)

## Future Enhancements

Potential agent improvements:
- Parallel component transfers
- Direct peer-to-peer location sync
- Delta/incremental sync for large files
- Automatic sync based on availability rules
- Multi-location redundancy
