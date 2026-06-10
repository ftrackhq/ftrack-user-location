# ftrack user location

Welcome to the ftrack-user-location. Please read below how to build ,
install and setup, before start using it.

## What is it for

(ftrack) User location allows artists to publish to their local
machine's file system rather than to other central storage scenario,
opening up the ability to work from remote or deatached locations.

The plugin provides a sync action to allow transfer between any
available locations (including ftrack.server), providing a way to exchange or deliver any
published material with other users or the studio storage.

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

## Recent Improvements

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

For technical details, see `JOB_LIFECYCLE_FIX.md` and `CRITICAL_PERMISSION_FIX.md`.

---

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

-   **FTRACK_USER_LOCATION_NAME**

If this environment variable is set, the user location will pick the
value set to it. Otherwise the location name will be generated based on
the user logged into ftrack and the hostname

#### Optional

By default the location will try to create a folder under:

*\<user\>/Document/local_ftrack_projects*

In case you prefer having the folder set somewhere else, please ensure
to set the following environment variable to an existing folder.

**FTRACK_USER_LOCATION_PATH**

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
