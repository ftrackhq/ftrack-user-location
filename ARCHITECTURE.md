# Architecture

## Overview

The ftrack User Location plugin enables artists to publish assets to their local file system and sync them with ftrack.server storage, supporting remote and detached workflow scenarios.

## System Design

### Core Components

1. **User Location** (`resource/location/user_location.py`)
   - Creates per-user local storage locations
   - Location naming: `{username}.{hostname}` (e.g., `john.workstation-01`)
   - Uses highest priority (-sys.maxsize) to override centralized storage
   - Stores files in `~/Documents/local_ftrack_projects/{server}/` by default

2. **Sync Engine** (`source/ftrack_user_location/sync.py`)
   - Bidirectional sync between locations
   - Syncs components from user locations to ftrack.server
   - Creates ftrack Jobs to track sync progress
   - Filters out ftrackreview components

3. **Sync Action** (`resource/hook/sync_action.py`)
   - ftrack Connect action UI for sync operations
   - Provides source/destination location selection
   - Triggers sync events via ftrack event hub

4. **Connect Plugin Hook** (`resource/hook/connect_plugin_hook.py`)
   - Registers location plugins with ftrack session
   - Injects location paths into DCC application environments
   - Controlled by `FTRACK_USER_MAIN_LOCATION` environment variable

## Data Flow

### Publish Flow
```
DCC Application → User Location (local disk) → ftrack.server
```

1. Artist publishes asset from DCC
2. Component stored in user location (`{username}.{hostname}`)
3. ftrack registers component availability in local location

### Sync Flow
```
User Location → Sync Action → ftrack.server → Remote User Location
```

1. User selects AssetVersion in ftrack UI
2. Launches "ftrack sync tool" action
3. Selects source and destination locations
4. Sync engine copies components between locations
5. Job entity tracks progress and completion

## Key Integration Points

### ftrack API Integration
- Uses `ftrack_api.Session` for all operations
- Subscribes to `ftrack.api.session.configure-location` events
- Publishes `ftrack.sync` events for async operations
- Uses `ftrack.action.discover` and `ftrack.action.launch` for UI

### Storage Layer
- User location: `ftrack_api.accessor.disk.DiskAccessor`
- ftrack.server: Built-in server accessor
- Standard structure: `ftrack_api.structure.standard.StandardStructure`

### Event Hub
- **Topic**: `ftrack.api.session.configure-location` - Registers locations
- **Topic**: `ftrack.action.discover` - Exposes sync action
- **Topic**: `ftrack.action.launch` - Executes sync
- **Topic**: `ftrack.sync` - Async sync coordination

## Technical Decisions

### Why Highest Priority?
User location uses priority `1 - sys.maxsize` to ensure it takes precedence over centralized storage scenarios, enabling "local-first" workflows.

### Why ftrack.server Instead of S3?
Previous versions used AWS S3 (`ftrack.sync` location). The current implementation uses ftrack.server for:
- Zero AWS configuration required
- Simpler authentication (uses ftrack credentials)
- Native integration with ftrack storage
- Eliminates boto3 dependency

### Location Discovery
Locations are discovered per-session via the `configure-location` event, ensuring each ftrack Connect session registers its own user location based on the logged-in user and hostname.

## Build System

### UV-based Build
The project uses [UV](https://docs.astral.sh/uv/) for modern Python dependency management:
- **pyproject.toml**: Package metadata and dependencies
- **setup.py**: Minimal shim for custom `build_plugin` command
- **Hatchling**: Build backend for wheel/sdist generation

### Plugin Packaging
The `build_plugin` command creates a Connect-compatible zip:
```
ftrack-user-location-{version}.zip
├── hook/              # Connect plugin hooks
├── location/          # Location implementations
└── dependencies/      # Vendored Python packages
```

## Configuration

### Environment Variables

**Mandatory:**
- `FTRACK_USER_MAIN_LOCATION`: When set, disables user location (for main studio)
- `FTRACK_USER_LOCTION_NAME`: Override default location name
- `FTRACK_USER_LOCTION_PATH`: Override default storage path

**Optional:**
- None (AWS variables removed in current version)

### Default Behavior
- **Storage path**: `~/Documents/local_ftrack_projects/{server}/`
- **Location name**: `{api_user}.{hostname}` (`.local` suffix removed on macOS)
- **Priority**: `-9223372036854775806` (highest possible)

## Deployment

1. Build plugin: `uv run python setup.py build_plugin`
2. Install zip in ftrack Connect plugins directory
3. Restart ftrack Connect
4. Location appears automatically per user/machine
