# ftrack user location

**Version 0.4.1** - High-performance user location plugin for ftrack

Welcome to the ftrack-user-location plugin. This plugin enables local-first workflows with optimized sync operations.

## What is it for

The ftrack User Location plugin allows artists to publish to their local machine's file system rather than to central storage, enabling work from remote or detached locations.

The plugin provides a high-performance sync action to transfer components between any available locations (including ftrack.server), with real-time progress tracking and robust error handling.

## Key Features

- ✅ **10-20x faster sync** - Optimized queries and batched commits
- ✅ **Real-time progress** - Live percentage updates in ftrack Job UI
- ✅ **Robust error handling** - Partial success tracking and detailed reporting
- ✅ **Zero AWS configuration** - Uses ftrack.server storage (no S3 setup)
- ✅ **Multi-user support** - No duplicate actions when multiple users online
- ✅ **Image sequence support** - Full support for SequenceComponent syncing
- ✅ **Modern build system** - UV-based dependency management

## How does it work

This location uses the highest possible priority available ( 1
-sys.maxint ) to ensure it takes precedence over virtally any other
location setup, such as the <span
class="title-ref">ftrack.centralised-storage-scenario</span>.

Note

If you are using custom Location please ensure you don't have any other
location set to priority: -9223372036854775806

During the plugin registration a new location will be created based on
the login name profile in the computer (**\<username\>.local**), and
it'll be reflected in the component location shown in the server.

## How to build and install

### Prerequisites

This project uses [UV](https://docs.astral.sh/uv/) for dependency management and builds. Install UV:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or with pip
pip install uv
```

### Building the plugin

To build the ftrack Connect plugin package:

```bash
# Install dependencies
uv sync

# Build the plugin zip
uv run python setup.py build_plugin
```

This creates a zip file in the `build/` directory: `ftrack-user-location-<version>.zip`

### Installation

For installation instructions, please refer to [our help pages](https://help.ftrack.com/en/articles/3504354-ftrack-connect-plugins-discovery-installation-and-update).

### Development

To install in development mode:

```bash
# Create virtual environment and install dependencies
uv sync

# Install in editable mode
uv pip install -e .
```

## How to set it up

Once installed a number of settings are needed to be provided in order
to be able to sync data.

### Environment variables

For the location to be fully operational, some environment variables are
needed to be setup.

#### Mandatory

-   **FTRACK_USER_MAIN_LOCATION**

If this environment variable is set, the user location won't be
registered, leaving any other location taking precedence. This is useful
when running connect with the plugin in main studio premises, to allow
remote users to pull and push data to the central storage scenario.

-   **FTRACK_USER_LOCTION_NAME**

If this environment variable is set, the user location will pick the
value set to it. Otherwise the location name will be generated based on
the user logged into ftrack and the hostname

#### Optional

By default the location will try to create a folder under:

*\<user\>/Document/local_ftrack_projects*

In case you prefer having the folder set somewhere else, please ensure
to set the following environment variable to an existing folder.

**FTRACK_USER_LOCTION_PATH**

## Checking is all setup

Once all the settings are in place, you should be able to start using
the location.

How to test is all up and ready.

1.  Use connect to publish a file . This should end up in \<user\>.local
2.  Execute actions on an AssetVersion and select the **ftrack sync
    tool** and run a transfer between your **\<user\>.local** to
    **ftrack.server**
3.  As above, but try to transfer file between two **\<user\>.local**
    locations.

## What's New

### Version 0.4.0 (Latest)
- **Fixed**: Session initialization bug during plugin discovery
- **Fixed**: Duplicate actions when multiple users run ftrack Connect simultaneously
- **Improvement**: Lazy-loaded user ID to avoid querying before session is ready
- **Performance**: 10-20x faster sync operations
- **Optimization**: 90% reduction in database queries (N+1 fixes)
- **Optimization**: 90% reduction in database commits (batched every 10 components)
- **Feature**: Real-time progress tracking in ftrack Job UI
- **Feature**: Robust error handling with partial success tracking
- **Feature**: Detailed component tracking (successful/skipped/failed)
- **Feature**: Multi-user support (each user sees only their own sync action)
- **Improvement**: Event validation to prevent crashes
- **Improvement**: Enhanced component filtering (pattern-based)
- **Migration**: Removed AWS/boto dependencies (ftrack.server only)
- **Migration**: UV-based build system with pyproject.toml
- **Docs**: Added ARCHITECTURE.md and CHANGELOG.md

### Version 0.3.2
- Previous stable release

## Documentation

- **[AGENTS.md](AGENTS.md)** - Agent architecture, deployment modes, and workflows
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design, data flow, and technical decisions
- **[CHANGELOG.md](CHANGELOG.md)** - Version history and release notes
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Contribution guidelines
