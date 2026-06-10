# Phased Evolution Plan: ftrack-user-location
## From Basic to Complete Bridge Architecture

**Version:** 2.0  
**Date:** 2026-06-09  
**Status:** Draft - Ready for Review

---

## Executive Summary

This plan outlines a 6-phase evolution to transform the ftrack-user-location plugin from its current "basic" state to a "complete" enterprise-grade transparent data transfer solution using **ftrack.server as a bridge/backup site**.

**Core Vision:** Users transparently access files across geographically distributed sites using **ftrack.server as mandatory intermediary** (users cannot access each other's filesystems over internet).

The system:
- Serves files from local cache when available (instant)
- Automatically syncs local files to ftrack.server (background backup)
- Transparently downloads from ftrack.server when requested by other users
- All site-to-site transfers route through ftrack.server (only shared access point)

**Current State:** Sequential transfers, manual source/destination selection, basic error handling, blocking event hub thread  
**Target State:** Transparent access, automatic bridge backup, on-demand download from bridge, parallel transfers, retry/resume

**Critical Constraint:** User locations are NOT directly accessible to each other (firewalls, NAT, internet separation). ftrack.server is the ONLY shared location all users can reach.

---

## Current Architecture Overview

### Key Components

| File | Purpose |
|------|---------|
| `resource/location/user_location.py` | Location registration with DiskAccessor + StandardStructure, priority `1 - sys.maxsize` |
| `resource/hook/sync_action.py` | SyncAction (BaseAction subclass) - discovery, UI forms, event routing |
| `source/ftrack_user_location/sync.py` | Transfer logic: `on_sync_to_remote()` and `on_sync_to_destination()` |
| `resource/hook/connect_plugin_hook.py` | Plugin entry point, DCC environment injection |

### Current Transfer Pattern

```
User A Location → (manual sync) → ftrack.server → (event trigger) → User B Location
```

**Problems with Current Pattern:**
- Users must manually trigger "sync to remote" then "sync to destination"
- No automatic bridge backup (files stay local until manually synced)
- No on-demand download (User B must wait for User A to manually sync first)
- Users see implementation details ("sync from X to Y")
- Sequential processing blocks event hub

### Target Architecture: Transparent Bridge (ftrack.server as Mandatory Intermediary)

```
┌──────────────────┐                    ┌──────────────────┐
│  User A Site     │                    │  User B Site     │
│  (Tokyo)         │                    │  (London)        │
│                  │                    │                  │
│  Local Storage   │                    │  Local Storage   │
│  - Fast access   │                    │  - Fast access   │
│  - Isolated      │                    │  - Isolated      │
└────────┬─────────┘                    └────────┬─────────┘
         │                                       │
         │ Auto Upload                           │ Auto Download
         │ (background)                          │ (on-demand)
         │                                       │
         ▼                                       ▼
    ┌────────────────────────────────────────────────┐
    │         ftrack.server (Shared Bridge)          │
    │                                                 │
    │  - Only location accessible to all users       │
    │  - Persistent backup/storage                   │
    │  - Enables site-to-site transfer               │
    │  - No direct User A ↔ User B connection        │
    └────────────────────────────────────────────────┘

Transfer Flow:
1. User A publishes asset → Local storage (instant)
2. Background: User A local → ftrack.server (auto backup)
3. User B requests asset → Check local first
4. If not local: ftrack.server → User B local (transparent download)
5. User B now has local cached copy (fast subsequent access)

User Experience:
- User A publishes: "Done" (files backed up in background)
- User B accesses: "Opening..." (downloads from bridge if needed, transparent)
- NO manual sync actions
- NO location selection
- NO waiting for other users to sync
```

**Key Principles:**
1. **Mandatory Bridge**: ftrack.server is the ONLY shared location (users can't reach each other)
2. **Automatic Backup**: Local writes auto-sync to bridge in background
3. **On-Demand Download**: Files downloaded from bridge when accessed (lazy evaluation)
4. **Local Caching**: Once downloaded, subsequent access is instant (from local cache)
5. **Transparent**: Users never see "sync" or "location"—just access files normally

---

## Phase 0 — Bridge Architecture: Mandatory Intermediary Pattern

**Timeline:** Week 0 (Before other phases)  
**Effort:** Medium (1-2 days)  
**Risk:** Medium  
**User Impact:** Critical (establishes foundation for transparency)

### Goal
Establish ftrack.server as **mandatory intermediary** for all site-to-site transfers. Users cannot access each other's locations directly (internet/firewall constraints), so ftrack.server is the only shared access point.

### Why This First
This is the architectural foundation:
- Users are geographically distributed (cannot access each other's filesystems)
- ftrack.server is the only location accessible to all users
- All transfers MUST route through ftrack.server (not optional)
- Local caching makes subsequent access fast
- Background uploads keep bridge in sync

### Technical Approach

#### 0.1 Location Priority Configuration

Configure location priorities to prefer local cache, but understand that **other user locations are inaccessible**:

```python
# In resource/location/user_location.py

def configure_location(session, event):
    '''Configure user location with proper priority.'''
    
    # ... existing setup code ...
    
    # CRITICAL: User locations are NOT accessible to each other
    # - User A location is only accessible to User A (local filesystem)
    # - User B location is only accessible to User B (local filesystem)
    # - ftrack.server (priority ~50) is accessible to EVERYONE
    
    # Priority determines read preference for THIS user:
    # - Lower number = try first
    # - User's OWN location: priority 1 (check local cache first - fastest)
    # - ftrack.server: priority ~50 (shared bridge - accessible to all)
    # - OTHER user locations: priority 100 (not directly accessible anyway)
    
    location.priority = 1  # THIS user's local location = highest priority for reads
    
    # This means when THIS user requests a file:
    # 1. Check my local cache (priority 1) - instant if cached
    # 2. If not cached, download from ftrack.server (priority ~50)
    # 3. Never try to read from other users' locations (they're unreachable)
    
    logger.info(
        'Registered location {0} @ {1} with priority {2} '
        '(local-first, bridge-fallback)'.format(
            USER_LOCATION_NAME, USER_DISK_PREFIX, location.priority
        )
    )
```

**Important:** Priority doesn't matter for cross-user access since users CAN'T reach each other. The priority system just ensures each user checks their own local cache before hitting ftrack.server.

#### 0.2 Bridge Manager Component

Create bridge manager that handles mandatory intermediary pattern:

```python
# source/ftrack_user_location/bridge_manager.py

import logging
import ftrack_api

logger = logging.getLogger(__name__)


class LocationBridge:
    """
    Manages transparent access with ftrack.server as mandatory intermediary.
    
    KEY CONSTRAINT: Users cannot access each other's locations directly.
    ftrack.server is the ONLY shared location accessible to all users.
    
    Pattern:
    - Local cache: Check here first (instant if available)
    - ftrack.server: Shared bridge (download if not cached locally)
    - Other user locations: NOT ACCESSIBLE (internet/firewall constraints)
    
    Automatically:
    - Serves from local cache when available
    - Downloads from ftrack.server when not cached
    - Uploads local files to ftrack.server in background
    - Never tries to access other users' locations (impossible)
    """
    
    def __init__(self, session, local_location_name=None):
        self.session = session
        
        # Resolve locations
        self.local_location = self._get_local_location(local_location_name)
        self.bridge_location = session.query(
            'Location where name is "ftrack.server"'
        ).one()
        
        logger.info(
            'Bridge initialized: local={}, bridge={}'.format(
                self.local_location['name'],
                self.bridge_location['name']
            )
        )
    
    def _get_local_location(self, name=None):
        """Get user's local location."""
        if name:
            return self.session.query(
                'Location where name is "{}"'.format(name)
            ).one()
        
        # Auto-detect current user location
        user = self.session.query(
            'User where username is "{}"'.format(self.session.api_user)
        ).one()
        
        # Find location matching user.hostname pattern
        import platform
        hostname = platform.node()
        if platform.system() == 'Darwin' and hostname.endswith('.local'):
            hostname = hostname[:hostname.find('.local')]
        
        expected_name = '{}.{}'.format(self.session.api_user, hostname)
        return self.session.query(
            'Location where name is "{}"'.format(expected_name)
        ).first()
    
    def get_component(self, component, dest_path=None):
        """
        Transparently get component from best available location.
        
        User never knows if it came from local, bridge, or remote origin.
        
        Fallback chain:
        1. Local cache (fastest)
        2. Bridge (ftrack.server backup)
        3. Origin location via bridge (site-to-site)
        
        Args:
            component: Component entity
            dest_path: Optional destination path (default: local location)
        
        Returns:
            str: Path to component file
        """
        component_name = component['name']
        
        # Try local first (fastest - no network)
        local_avail = self.local_location.get_component_availability(component)
        if local_avail > 0:
            logger.debug(
                'Component {} available locally ({:.0f}%)'.format(
                    component_name, local_avail * 100
                )
            )
            return self.local_location.get_component(
                component, dest_path or self.local_location.accessor.prefix
            )
        
        # Try bridge (shared backup - single hop)
        bridge_avail = self.bridge_location.get_component_availability(component)
        if bridge_avail > 0:
            logger.info(
                'Component {} fetching from bridge ({:.0f}%)'.format(
                    component_name, bridge_avail * 100
                )
            )
            
            # Download from bridge and cache locally
            local_path = self.bridge_location.get_component(
                component, dest_path or self.local_location.accessor.prefix
            )
            
            # Cache locally for next time (async)
            self._cache_locally(component, local_path)
            
            return local_path
        
        # Trigger site-to-site via bridge (origin → bridge → local)
        logger.info(
            'Component {} not in bridge, requesting from origin'.format(
                component_name
            )
        )
        return self._request_from_origin(component, dest_path)
    
    def put_component(self, component, source_path):
        """
        Store component locally AND queue bridge backup.
        
        Returns immediately after local write.
        Bridge backup happens asynchronously in background.
        
        Args:
            component: Component entity
            source_path: Path to source file
        """
        component_name = component['name']
        
        # Immediate: write locally (user doesn't wait)
        logger.debug(
            'Storing component {} locally'.format(component_name)
        )
        self.local_location.add_component(component, source_path)
        
        # Async: queue bridge backup (transparent to user)
        logger.debug(
            'Queuing component {} for bridge backup'.format(component_name)
        )
        self._queue_bridge_backup(component)
    
    def _cache_locally(self, component, source_path):
        """Cache component from bridge to local (async)."""
        # TODO: Implement in Phase 4 with cache manager
        # For now, just add to local location
        try:
            self.local_location.add_component(component, source_path)
            logger.debug(
                'Cached {} locally from bridge'.format(component['name'])
            )
        except ftrack_api.exception.ComponentInLocationError:
            # Already cached
            pass
        except Exception as e:
            logger.warning(
                'Failed to cache {} locally: {}'.format(
                    component['name'], e
                )
            )
    
    def _queue_bridge_backup(self, component):
        """Queue component for async backup to bridge."""
        # TODO: Implement in Phase 1 with background executor
        # For now, synchronous backup
        try:
            bridge_avail = self.bridge_location.get_component_availability(
                component
            )
            if bridge_avail < 100.0:
                self.bridge_location.add_component(
                    component, self.local_location
                )
                logger.info(
                    'Backed up {} to bridge'.format(component['name'])
                )
        except ftrack_api.exception.ComponentInLocationError:
            logger.debug(
                'Component {} already in bridge'.format(component['name'])
            )
        except Exception as e:
            logger.error(
                'Failed to backup {} to bridge: {}'.format(
                    component['name'], e
                )
            )
    
    def ensure_in_bridge(self, component):
        """
        Ensure component exists in bridge (uploaded from local).
        
        Call this after local file creation to back up to bridge.
        This enables other users to access the file.
        
        Args:
            component: Component entity
        """
        component_name = component['name']
        
        # Check if already in bridge
        bridge_avail = self.bridge_location.get_component_availability(component)
        if bridge_avail >= 100.0:
            logger.debug(
                'Component {} already in bridge'.format(component_name)
            )
            return
        
        # Upload from local to bridge
        logger.info(
            'Uploading {} to bridge (making available to other users)'.format(
                component_name
            )
        )
        
        try:
            self.bridge_location.add_component(component, self.local_location)
            logger.info(
                'Component {} uploaded to bridge successfully'.format(component_name)
            )
        except ftrack_api.exception.ComponentInLocationError:
            # Already exists (race condition with another upload)
            logger.debug(
                'Component {} already in bridge (concurrent upload)'.format(
                    component_name
                )
            )
        except Exception as e:
            logger.error(
                'Failed to upload {} to bridge: {}'.format(component_name, e)
            )
            raise


class ComponentNotFoundError(Exception):
    """Component not available in any accessible location."""
    pass
```

#### 0.3 Update Location Registration

Modify location registration to use bridge-aware priority:

```python
# In resource/location/user_location.py

def configure_location(session, event):
    '''Configure location with bridge-aware settings.'''
    
    # ... existing path and name setup ...
    
    location = session.query(
        'Location where name is "{}"'.format(USER_LOCATION_NAME)
    ).first()
    
    if not location:
        location = session.ensure(
            'Location', 
            {
                'name': USER_LOCATION_NAME,
                'description': 'User location for {}, host {}, path: {} '
                              '(bridge-aware)'.format(
                    session.api_user, 
                    hostname,
                    os.path.abspath(USER_DISK_PREFIX)
                )
            }
        )
    
    location.accessor = _disk.DiskAccessor(prefix=USER_DISK_PREFIX)
    location.structure = _standard.StandardStructure()
    
    # Bridge-aware priority: 100 (lower than ftrack.server's ~50)
    # This means ftrack.server is checked before user locations on reads
    location.priority = 100
    
    logger.info(
        'Registered location {0} @ {1} with priority {2} '
        '(bridge-fallback enabled)'.format(
            USER_LOCATION_NAME, USER_DISK_PREFIX, location.priority
        )
    )
```

### Files Changed

| File | Change |
|------|--------|
| `source/ftrack_user_location/bridge_manager.py` | **NEW** - Bridge abstraction layer |
| `resource/location/user_location.py` | Update priority from `1-sys.maxsize` to `100` |
| `resource/location/user_location.py` | Update description to indicate bridge-aware |

### Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| Priority change breaks existing behavior | Test fallback chain; document that ftrack.server now checked first on reads |
| Bridge not accessible | Validation checks in Phase 3; fallback to direct location access |
| Origin location detection fails | Timeout and clear error message; manual fallback option |

### Success Criteria

- [ ] User locations have priority 100 (bridge-aware)
- [ ] Bridge manager can get components transparently
- [ ] Local cache preferred over bridge (performance)
- [ ] Bridge preferred over remote locations (single hop vs two)
- [ ] Bridge backup queued for local writes

---

## Phase 1 — Foundation: Service Architecture & Background Execution

**Timeline:** Week 1  
**Effort:** Medium (2-3 days)  
**Risk:** Low-Medium  
**User Impact:** High (non-blocking operations, real progress tracking)

### Goal
Build long-running sync service with proper session management, background execution, and real progress tracking. Transform from blocking event handlers to service-based architecture.

### Why After Phase 0
Phase 0 establishes WHAT (bridge architecture). Phase 1 establishes HOW (service that manages it).

### Technical Approach

#### 1.1 Service Lifecycle Management

Create long-running service with proper session handling:

```python
# source/ftrack_user_location/sync_service.py

import logging
import threading
import ftrack_api
from concurrent.futures import ThreadPoolExecutor
from .bridge_manager import LocationBridge

logger = logging.getLogger(__name__)


class SyncService:
    """
    Long-running sync service with bridge management.
    
    Handles:
    - Session lifecycle (main + worker sessions)
    - Event subscriptions
    - Background transfer execution
    - Connection health monitoring
    """
    
    def __init__(self, max_workers=4):
        """
        Args:
            max_workers: Number of parallel transfer workers
        """
        # Main session for event hub (never closes)
        self._main_session = ftrack_api.Session(
            auto_connect_event_hub=True
        )
        
        # Worker thread pool for background transfers
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # Thread-local session cache for workers
        self._session_cache = threading.local()
        
        # Bridge manager (uses main session)
        self._bridge = LocationBridge(self._main_session)
        
        # Active transfers tracking
        self._active_transfers = {}
        self._transfers_lock = threading.Lock()
        
        logger.info(
            'SyncService initialized: workers={}, bridge={}'.format(
                max_workers, self._bridge.bridge_location['name']
            )
        )
    
    def start(self):
        """
        Start service and subscribe to sync events.
        Blocks forever (call in main thread).
        """
        logger.info('Starting SyncService...')
        
        # Subscribe to sync requests
        self._main_session.event_hub.subscribe(
            'topic=ftrack.sync',
            self._handle_sync_request
        )
        
        # Subscribe to disconnection events
        self._main_session.event_hub.subscribe(
            'topic=ftrack.meta.disconnected',
            self._handle_disconnect
        )
        
        # Monitor connection health
        self._main_session.event_hub.subscribe(
            'topic=ftrack.meta.connected',
            self._handle_reconnect
        )
        
        logger.info('SyncService started, waiting for events...')
        
        # Block forever (event hub loop)
        self._main_session.event_hub.wait()
    
    def stop(self):
        """Gracefully shutdown service."""
        logger.info('Stopping SyncService...')
        
        # Wait for active transfers
        self._executor.shutdown(wait=True)
        
        # Close main session
        self._main_session.close()
        
        logger.info('SyncService stopped')
    
    def get_worker_session(self):
        """
        Get thread-local session for worker.
        
        Each worker thread gets its own session (no event hub).
        Sessions are reused within the same thread.
        """
        if not hasattr(self._session_cache, 'session'):
            self._session_cache.session = ftrack_api.Session(
                auto_connect_event_hub=False,  # Workers don't need event hub
                server_url=self._main_session.server_url,
                api_key=self._main_session.api_key,
                api_user=self._main_session.api_user
            )
            logger.debug('Created worker session for thread')
        
        return self._session_cache.session
    
    def _handle_sync_request(self, event):
        """
        Handle sync request event (non-blocking).
        
        Submits transfer to background executor.
        """
        data = event['data']
        source = event.get('source', {})
        user_id = source.get('user', {}).get('id')
        
        logger.info(
            'Received sync request: user={}, data={}'.format(
                user_id, data
            )
        )
        
        # Submit to background executor (returns immediately)
        future = self._executor.submit(
            self._execute_sync,
            data,
            user_id
        )
        
        # Track active transfer
        transfer_id = id(future)
        with self._transfers_lock:
            self._active_transfers[transfer_id] = {
                'future': future,
                'data': data,
                'user_id': user_id
            }
        
        # Cleanup when done
        future.add_done_callback(
            lambda f: self._cleanup_transfer(transfer_id)
        )
    
    def _execute_sync(self, data, user_id):
        """
        Execute sync in background worker thread.
        
        Uses worker session (not main session).
        """
        session = self.get_worker_session()
        
        try:
            # Import here to avoid circular dependency
            from .sync_engine import SyncEngine
            
            # Create engine with worker session
            engine = SyncEngine(session)
            
            # Execute sync
            engine.sync_from_event_data(data, user_id)
            
        except Exception as e:
            logger.error('Sync failed: {}'.format(e))
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    def _cleanup_transfer(self, transfer_id):
        """Remove completed transfer from tracking."""
        with self._transfers_lock:
            if transfer_id in self._active_transfers:
                transfer = self._active_transfers.pop(transfer_id)
                logger.debug(
                    'Transfer completed: {}'.format(transfer['data'])
                )
    
    def _handle_disconnect(self, event):
        """Handle session disconnection."""
        logger.warning('Session disconnected, will auto-reconnect...')
        # ftrack_api.Session auto-reconnects, just log
    
    def _handle_reconnect(self, event):
        """Handle session reconnection."""
        logger.info('Session reconnected')
```

#### 1.2 Extract Sync Engine

Refactor sync logic into testable engine class:

```python
# source/ftrack_user_location/sync_engine.py

import logging
import json
import ftrack_api
from .bridge_manager import LocationBridge

logger = logging.getLogger(__name__)


class SyncEngine:
    """
    Core sync logic, decoupled from event handlers.
    
    Testable, reusable transfer engine that works with bridge manager.
    """
    
    def __init__(self, session, progress_callback=None):
        """
        Args:
            session: ftrack_api.Session
            progress_callback: Optional callback(phase, pct, message)
        """
        self.session = session
        self._progress_callback = progress_callback
        self._bridge = LocationBridge(session)
    
    def sync_from_event_data(self, event_data, user_id):
        """
        Execute sync from event data.
        
        Args:
            event_data: Event data dict with components and locations
            user_id: ID of user who requested sync
        """
        # Extract event data
        action_id = event_data.get('actionIdentifier', '')
        components_data = event_data.get('components', [])
        locations = event_data.get('locations', {})
        
        # Resolve locations
        source_id = locations.get('source') or locations.get('sync')
        dest_id = locations.get('destination')
        
        if not (source_id and dest_id):
            raise ValueError('Missing source or destination location in event')
        
        source_location = self.session.get('Location', source_id)
        dest_location = self.session.get('Location', dest_id)
        
        # Resolve components
        components = [
            self.session.get('Component', cdata['id'])
            for cdata in components_data
        ]
        
        # Execute sync
        self.sync_components(
            source_location,
            dest_location,
            components,
            user_id
        )
    
    def sync_components(self, source_location, dest_location, components,
                        user_id, max_workers=1):
        """
        Sync components from source to destination.
        
        Uses bridge manager for transparent location resolution.
        
        Args:
            source_location: Source Location entity
            dest_location: Destination Location entity
            components: List of Component entities
            user_id: User ID for job tracking
            max_workers: Number of parallel workers (1 for Phase 1)
        """
        user = self.session.get('User', user_id)
        
        # Create job for progress tracking
        job = self.session.create('Job', {
            'data': json.dumps({
                'phase': 'initializing',
                'progress_pct': 0.0,
                'description': 'Initializing sync: {} components'.format(
                    len(components)
                )
            }),
            'user': user,
            'status': 'running'
        })
        self.session.commit()
        
        try:
            # Calculate total size for progress
            total_bytes = sum(
                c.get('size', 0) for c in components
            )
            transferred_bytes = 0
            
            # Sequential transfer (Phase 1)
            for idx, component in enumerate(components):
                component_name = component['name']
                component_size = component.get('size', 0)
                
                # Skip ftrackreview components
                if 'ftrackreview' in component_name.lower():
                    continue
                
                # Update job status
                progress_pct = (idx / len(components)) * 100
                self._update_job(
                    job, 'transferring', component_name, progress_pct
                )
                
                # Check if already in destination
                dest_avail = dest_location.get_component_availability(component)
                if dest_avail == 100.0:
                    logger.debug(
                        'Component {} already in {}'.format(
                            component_name, dest_location['name']
                        )
                    )
                    transferred_bytes += component_size
                    continue
                
                # Transfer component
                logger.info(
                    'Transferring {} from {} to {}'.format(
                        component_name,
                        source_location['name'],
                        dest_location['name']
                    )
                )
                
                self._transfer_component(
                    component, source_location, dest_location
                )
                
                transferred_bytes += component_size
            
            # Complete
            job['status'] = 'done'
            self._update_job(job, 'complete', '', 100.0)
            
            logger.info(
                'Sync complete: {} components, {} bytes'.format(
                    len(components), transferred_bytes
                )
            )
            
        except Exception as e:
            job['status'] = 'failed'
            self._update_job(job, 'failed', str(e), 0)
            raise
    
    def _transfer_component(self, component, source_location, dest_location):
        """Transfer single component with basic error handling."""
        try:
            dest_location.add_component(component, source_location)
        except ftrack_api.exception.ComponentInLocationError:
            # Already exists, not an error
            logger.debug(
                'Component {} already in {}'.format(
                    component['name'], dest_location['name']
                )
            )
        except Exception as e:
            logger.error(
                'Failed to transfer {}: {}'.format(component['name'], e)
            )
            raise
    
    def _update_job(self, job, phase, current_component, progress_pct):
        """Update job with structured progress data."""
        job['data'] = json.dumps({
            'phase': phase,  # 'initializing' | 'transferring' | 'complete' | 'failed'
            'current_component': current_component,
            'progress_pct': round(progress_pct, 1),
            'description': '{}: {} ({:.1f}%)'.format(
                phase, current_component, progress_pct
            )
        })
        self.session.commit()
        
        # Call progress callback if provided
        if self._progress_callback:
            self._progress_callback(phase, progress_pct, current_component)
```

#### 1.3 Update Existing Sync Functions

Keep backward compatibility by wrapping new engine:

```python
# source/ftrack_user_location/sync.py

import logging
from .sync_engine import SyncEngine

logger = logging.getLogger(__name__)


def on_sync_to_destination(session, source_id, destination_id, components, user_id):
    """
    DEPRECATED: Legacy wrapper for backward compatibility.
    
    Use SyncEngine directly in new code.
    """
    logger.warning(
        'on_sync_to_destination is deprecated, use SyncEngine'
    )
    
    # Build event data format
    event_data = {
        'components': components,
        'locations': {
            'source': source_id,
            'destination': destination_id
        }
    }
    
    # Use new engine
    engine = SyncEngine(session)
    engine.sync_from_event_data(event_data, user_id)


def on_sync_to_remote(session, source, destination, user_id, selection):
    """
    DEPRECATED: Legacy wrapper for backward compatibility.
    
    Use SyncEngine directly in new code.
    """
    logger.warning(
        'on_sync_to_remote is deprecated, use SyncEngine'
    )
    
    # Get locations
    source_location = session.query(
        'Location where name is "{}"'.format(source)
    ).one()
    dest_location = session.query(
        'Location where name is "{}"'.format(destination)
    ).one()
    bridge_location = session.query(
        'Location where name is "ftrack.server"'
    ).one()
    
    # Get components from selection
    components = []
    for s in selection:
        version = session.get('AssetVersion', s['entityId'])
        for component in version['components']:
            components.append(component)
    
    # Two-hop transfer via bridge
    # Step 1: source → bridge
    engine = SyncEngine(session)
    engine.sync_components(
        source_location, bridge_location, components, user_id
    )
    
    # Step 2: bridge → destination (via event)
    import ftrack_api.event.base
    event = ftrack_api.event.base.Event(
        topic='ftrack.sync',
        data={
            'actionIdentifier': 'ftrack-to-{}'.format(dest_location['name']),
            'components': [{'id': c['id'], 'name': c['name']} for c in components],
            'locations': {
                'sync': bridge_location['id'],
                'source': source_location['id'],
                'destination': dest_location['id']
            }
        },
        source={'user': {'id': user_id}}
    )
    session.event_hub.publish(event)
```

### Files Changed

| File | Change |
|------|--------|
| `source/ftrack_user_location/sync_service.py` | **NEW** - Service lifecycle management |
| `source/ftrack_user_location/sync_engine.py` | **NEW** - Core sync engine |
| `source/ftrack_user_location/sync.py` | Refactor to wrappers around SyncEngine |
| `resource/hook/connect_plugin_hook.py` | Update to start SyncService |

### Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| Session thread-safety bugs | Use per-worker sessions, never share sessions across threads |
| Service crashes kill all transfers | Graceful shutdown, transfer tracking, resume in Phase 3 |
| Memory leak from unclosed sessions | Cleanup in thread-local storage, monitor with logging |

### Success Criteria

- [ ] Sync operations don't block event hub
- [ ] Job shows real progress percentage (e.g., "transferring: render.ma (45.2%)")
- [ ] Service runs continuously without crashes
- [ ] Worker sessions isolated per thread
- [ ] All existing functionality still works (backward compatibility)

---

## Phase 2 — Performance: Smart Source Resolution & Parallel Transfers

**Timeline:** Week 2  
**Effort:** Short (4-8 hours)  
**Risk:** Low  
**User Impact:** High (faster transfers, intelligent routing)

### Goal
Add intelligent source location resolution (each component from best location) and parallel transfers for multiple components.

### Technical Approach

#### 2.1 Smart Source Resolution

Resolve best source location per component:

```python
# In source/ftrack_user_location/sync_engine.py

class SyncEngine:
    def resolve_best_source(self, component, preferred_locations=None):
        """
        Find best location to source component from.
        
        Considers:
        - Availability (must be > 0)
        - Priority (lower number = higher priority)
        - Latency (prefer local > bridge > remote)
        
        Args:
            component: Component entity
            preferred_locations: Optional list of Location entities to check
                                 (default: all accessible locations)
        
        Returns:
            Location entity with best availability/priority
        
        Raises:
            ComponentNotFoundError: Component not available anywhere
        """
        # Default: check all locations
        if preferred_locations is None:
            preferred_locations = [
                self._bridge.local_location,
                self._bridge.bridge_location
            ]
            # Add other accessible locations
            all_locations = self.session.query('select name from Location').all()
            for loc in all_locations:
                if loc not in preferred_locations:
                    preferred_locations.append(loc)
        
        # Check availability in each location
        available_locations = []
        for location in preferred_locations:
            try:
                availability = location.get_component_availability(component)
                if availability > 0:
                    available_locations.append({
                        'location': location,
                        'availability': availability,
                        'priority': location.get('priority', 50)
                    })
            except Exception as e:
                logger.debug(
                    'Cannot check location {}: {}'.format(
                        location.get('name', 'unknown'), e
                    )
                )
                continue
        
        if not available_locations:
            from .bridge_manager import ComponentNotFoundError
            raise ComponentNotFoundError(
                'Component {} not available in any location'.format(
                    component['name']
                )
            )
        
        # Sort by priority (lower = better), then availability (higher = better)
        best = sorted(
            available_locations,
            key=lambda x: (x['priority'], -x['availability'])
        )[0]
        
        logger.debug(
            'Best source for {}: {} (priority={}, avail={:.0f}%)'.format(
                component['name'],
                best['location']['name'],
                best['priority'],
                best['availability'] * 100
            )
        )
        
        return best['location']
```

#### 2.2 Parallel Transfer Engine

Add multi-worker parallel transfers:

```python
# In source/ftrack_user_location/sync_engine.py

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

class SyncEngine:
    def sync_components_parallel(self, dest_location, components, user_id,
                                  max_workers=None):
        """
        Parallel component transfer with smart source resolution.
        
        Each component sources from best available location automatically.
        
        Args:
            dest_location: Destination Location entity
            components: List of Component entities
            user_id: User ID for job tracking
            max_workers: Parallel workers (default: FTRACK_SYNC_MAX_WORKERS env or 4)
        """
        max_workers = max_workers or int(
            os.getenv('FTRACK_SYNC_MAX_WORKERS', 4)
        )
        
        user = self.session.get('User', user_id)
        
        # Create job
        job = self.session.create('Job', {
            'data': json.dumps({
                'phase': 'initializing',
                'progress_pct': 0.0,
                'total_components': len(components),
                'completed_components': 0,
                'description': 'Initializing parallel sync: {} components'.format(
                    len(components)
                )
            }),
            'user': user,
            'status': 'running'
        })
        self.session.commit()
        
        try:
            # Submit all transfers in parallel
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                
                for component in components:
                    # Skip ftrackreview
                    if 'ftrackreview' in component['name'].lower():
                        continue
                    
                    # Resolve best source for THIS component
                    # (may differ per component!)
                    source_location = self.resolve_best_source(component)
                    
                    # Submit transfer
                    future = executor.submit(
                        self._transfer_component_with_session,
                        component,
                        source_location,
                        dest_location
                    )
                    futures[future] = {
                        'component': component,
                        'source': source_location
                    }
                
                # Process completions as they happen
                completed = 0
                for future in as_completed(futures):
                    info = futures[future]
                    component = info['component']
                    
                    try:
                        future.result()
                        completed += 1
                        
                        # Update progress
                        progress_pct = (completed / len(components)) * 100
                        self._update_job_parallel(
                            job, 'transferring', component['name'],
                            progress_pct, completed, len(components)
                        )
                        
                        logger.info(
                            'Completed {} ({}/{})'.format(
                                component['name'], completed, len(components)
                            )
                        )
                        
                    except Exception as e:
                        logger.error(
                            'Failed to transfer {}: {}'.format(
                                component['name'], e
                            )
                        )
                        # Continue with other transfers
            
            # Complete
            job['status'] = 'done'
            self._update_job_parallel(
                job, 'complete', '', 100.0, len(components), len(components)
            )
            
        except Exception as e:
            job['status'] = 'failed'
            self._update_job(job, 'failed', str(e), 0)
            raise
    
    def _transfer_component_with_session(self, component, source_location,
                                          dest_location):
        """
        Transfer component using fresh session for thread safety.
        
        Each worker thread gets its own session.
        """
        # Create worker session (no event hub)
        session = ftrack_api.Session(
            auto_connect_event_hub=False,
            server_url=self.session.server_url,
            api_key=self.session.api_key,
            api_user=self.session.api_user
        )
        
        try:
            # Re-fetch entities in worker session
            component = session.get('Component', component['id'])
            source_location = session.get('Location', source_location['id'])
            dest_location = session.get('Location', dest_location['id'])
            
            # Transfer
            dest_location.add_component(component, source_location)
            
            logger.debug(
                'Worker transferred {} from {} to {}'.format(
                    component['name'],
                    source_location['name'],
                    dest_location['name']
                )
            )
            
        except ftrack_api.exception.ComponentInLocationError:
            # Already exists, not an error
            logger.debug(
                'Component {} already in {}'.format(
                    component['name'], dest_location['name']
                )
            )
        except Exception as e:
            logger.error(
                'Transfer failed for {}: {}'.format(component['name'], e)
            )
            raise
        finally:
            session.close()
    
    def _update_job_parallel(self, job, phase, current_component, progress_pct,
                             completed, total):
        """Update job with parallel progress tracking."""
        job['data'] = json.dumps({
            'phase': phase,
            'current_component': current_component,
            'progress_pct': round(progress_pct, 1),
            'completed_components': completed,
            'total_components': total,
            'description': '{}: {}/{} components ({:.1f}%)'.format(
                phase, completed, total, progress_pct
            )
        })
        self.session.commit()
```

#### 2.3 Selective Component UI

Add component selection to sync action (optional enhancement):

```python
# In resource/hook/sync_action.py

def get_locations_ui(self, event):
    """Build sync form with optional component selection."""
    selection = event['data']['selection']
    
    # Get components from selection
    components = self._get_components_from_selection(selection)
    
    menu = {
        'type': 'form',
        'items': [],
        'title': 'Sync Components',
        'submit_button_label': 'Sync'
    }
    
    # Component selection (if multiple)
    if len(components) > 1:
        menu['items'].append({
            'value': '## Select Components ##',
            'type': 'label'
        })
        
        for component in components:
            size = component.get('size', 0)
            size_str = self._format_size(size) if size > 0 else 'unknown size'
            
            menu['items'].append({
                'type': 'boolean',
                'label': '{} ({})'.format(component['name'], size_str),
                'name': 'component_{}'.format(component['id']),
                'value': True  # Default: all selected
            })
    
    # Destination selection
    menu['items'].append({
        'value': '## Destination ##',
        'type': 'label'
    })
    menu['items'].append(
        self.get_locations_menu('dest_location', label='Destination')
    )
    
    return menu

def _format_size(self, bytes):
    """Format bytes as human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024.0:
            return '{:.1f} {}'.format(bytes, unit)
        bytes /= 1024.0
    return '{:.1f} PB'.format(bytes)

def _get_components_from_selection(self, selection):
    """Extract components from selected entities."""
    components = []
    for item in selection:
        entity = self.session.get(item['entityType'], item['entityId'])
        
        # AssetVersion
        if item['entityType'] == 'AssetVersion':
            components.extend(entity['components'])
        # Task (get latest version)
        elif item['entityType'] == 'Task':
            versions = entity['asset']['versions']
            if versions:
                latest = sorted(versions, key=lambda v: v['version'])[-1]
                components.extend(latest['components'])
    
    return components
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FTRACK_SYNC_MAX_WORKERS` | 4 | Parallel transfer workers (1-16) |

### Files Changed

| File | Change |
|------|--------|
| `source/ftrack_user_location/sync_engine.py` | Add smart source resolution and parallel methods |
| `resource/hook/sync_action.py` | Optional: Add component selection UI |

### Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| Too many workers saturate resources | Cap at 16, default 4, test with load |
| Session per worker overhead | Lightweight sessions (no event hub), connection pooling |
| Progress tracking race conditions | Use thread-safe job updates with locks |

### Success Criteria

- [ ] 4+ components transfer in parallel (visible in logs)
- [ ] Each component sources from best location automatically
- [ ] Progress shows aggregate: "3/10 components (30%)"
- [ ] No slower than sequential for single component
- [ ] Smart source resolution logs show correct priorities

---

## Phase 3 — Resilience: Retry, Resume & Bridge Validation

**Timeline:** Week 3  
**Effort:** Short-Medium (4-8 hours)  
**Risk:** Low-Medium  
**User Impact:** Medium-High (production reliability)

### Goal
Add exponential backoff retry, checkpoint-based resume for interrupted transfers, and bridge-aware validation.

### Technical Approach

#### 3.1 Retry Mechanism

Wrap transfers with exponential backoff:

```python
# source/ftrack_user_location/retry.py

import time
import logging
import os
from functools import wraps
import ftrack_api.exception

logger = logging.getLogger(__name__)


def with_retry(max_retries=None, backoff_base=2):
    """
    Decorator for retry logic with exponential backoff.
    
    Args:
        max_retries: Max retry attempts (default: FTRACK_SYNC_MAX_RETRIES env or 5)
        backoff_base: Backoff multiplier (default: 2)
    """
    max_retries = max_retries or int(os.getenv('FTRACK_SYNC_MAX_RETRIES', 5))
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                    
                except ftrack_api.exception.ComponentInLocationError:
                    # Don't retry - component already exists (not an error)
                    raise
                    
                except ftrack_api.exception.AccessorOperationFailedError as e:
                    if attempt < max_retries - 1:
                        sleep_time = backoff_base ** attempt
                        logger.warning(
                            'Transfer failed (attempt {}/{}), retrying in {}s: {}'.format(
                                attempt + 1, max_retries, sleep_time, e
                            )
                        )
                        time.sleep(sleep_time)
                    else:
                        logger.error(
                            'Transfer failed after {} retries: {}'.format(
                                max_retries, e
                            )
                        )
                        raise
                        
                except Exception as e:
                    # Other exceptions: retry with backoff
                    if attempt < max_retries - 1:
                        sleep_time = backoff_base ** attempt
                        logger.warning(
                            'Operation failed (attempt {}/{}), retrying in {}s: {}'.format(
                                attempt + 1, max_retries, sleep_time, e
                            )
                        )
                        time.sleep(sleep_time)
                    else:
                        raise
        
        return wrapper
    return decorator


# Apply to transfer methods
# In source/ftrack_user_location/sync_engine.py

from .retry import with_retry

class SyncEngine:
    @with_retry()
    def _transfer_component(self, component, source_location, dest_location):
        """Transfer with automatic retry."""
        dest_location.add_component(component, source_location)
```

#### 3.2 Transfer Checkpointing

Resume from where transfer was interrupted:

```python
# In source/ftrack_user_location/sync_engine.py

class SyncEngine:
    def sync_with_resume(self, dest_location, components, user_id, job=None):
        """
        Sync with checkpoint resume support.
        
        If job provided, checks for existing progress and resumes.
        Otherwise, starts fresh sync.
        
        Args:
            dest_location: Destination Location entity
            components: List of Component entities
            user_id: User ID for job tracking
            job: Optional existing Job entity to resume
        """
        user = self.session.get('User', user_id)
        
        # Resume existing job or create new
        if job:
            logger.info('Resuming job {}'.format(job['id']))
            completed_ids = self._get_completed_component_ids(job)
        else:
            completed_ids = set()
            job = self.session.create('Job', {
                'data': json.dumps({
                    'phase': 'initializing',
                    'progress_pct': 0.0,
                    'completed_component_ids': []
                }),
                'user': user,
                'status': 'running'
            })
            self.session.commit()
        
        # Filter to uncompleted components
        remaining = [
            c for c in components
            if c['id'] not in completed_ids
        ]
        
        logger.info(
            'Syncing {} components ({} already complete)'.format(
                len(remaining), len(components) - len(remaining)
            )
        )
        
        try:
            for idx, component in enumerate(remaining):
                # Smart source resolution
                source_location = self.resolve_best_source(component)
                
                # Update progress
                total_progress = (
                    (len(completed_ids) + idx) / len(components)
                ) * 100
                self._update_job(
                    job, 'transferring', component['name'], total_progress
                )
                
                # Transfer
                self._transfer_component(
                    component, source_location, dest_location
                )
                
                # Mark complete (checkpoint)
                self._mark_component_complete(job, component['id'])
                completed_ids.add(component['id'])
            
            # Complete
            job['status'] = 'done'
            self._update_job(job, 'complete', '', 100.0)
            
        except Exception as e:
            logger.error('Sync failed (can resume): {}'.format(e))
            job['data'] = json.dumps({
                **json.loads(job['data']),
                'phase': 'paused',
                'error': str(e),
                'description': 'Paused after error (can resume)'
            })
            job['status'] = 'failed'
            self.session.commit()
            raise
    
    def _get_completed_component_ids(self, job):
        """Extract completed component IDs from job data."""
        data = json.loads(job['data'])
        return set(data.get('completed_component_ids', []))
    
    def _mark_component_complete(self, job, component_id):
        """Record component completion for resume."""
        data = json.loads(job['data'])
        completed = set(data.get('completed_component_ids', []))
        completed.add(component_id)
        data['completed_component_ids'] = list(completed)
        job['data'] = json.dumps(data)
        self.session.commit()
```

#### 3.3 Bridge-Aware Validation

Validate before starting any transfers:

```python
# source/ftrack_user_location/validation.py

import os
import shutil
import logging

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Validation failed - transfer cannot proceed."""
    
    def __init__(self, errors):
        self.errors = errors if isinstance(errors, list) else [errors]
        super().__init__('; '.join(self.errors))


# In source/ftrack_user_location/sync_engine.py

from .validation import ValidationError

class SyncEngine:
    def validate_sync(self, dest_location, components):
        """
        Validate sync can proceed with bridge-aware checks.
        
        Checks:
        - Disk space on destination
        - Write permissions on destination
        - Bridge accessibility
        - At least one source has components
        
        Raises:
            ValidationError: Validation failed with list of errors
        """
        errors = []
        
        # Check destination disk space
        total_size = sum(c.get('size', 0) for c in components)
        dest_prefix = dest_location.accessor.prefix
        
        try:
            usage = shutil.disk_usage(dest_prefix)
            # Require 10% buffer
            required_space = total_size * 1.1
            
            if usage.free < required_space:
                errors.append(
                    'Insufficient disk space on {}: {} required, {} available'.format(
                        dest_location['name'],
                        self._format_size(required_space),
                        self._format_size(usage.free)
                    )
                )
        except Exception as e:
            errors.append(
                'Cannot check disk space on {}: {}'.format(
                    dest_location['name'], e
                )
            )
        
        # Check write permissions
        if not os.access(dest_prefix, os.W_OK):
            errors.append(
                'No write permission on {}: {}'.format(
                    dest_location['name'], dest_prefix
                )
            )
        
        # Check bridge accessibility
        try:
            bridge = self._bridge.bridge_location
            if not bridge.accessor:
                errors.append('Bridge location {} not accessible'.format(
                    bridge['name']
                ))
        except Exception as e:
            errors.append('Cannot access bridge: {}'.format(e))
        
        # Check at least one source has each component
        unavailable = []
        for component in components:
            try:
                # This will raise if component not found anywhere
                source = self.resolve_best_source(component)
            except Exception:
                unavailable.append(component['name'])
        
        if unavailable:
            errors.append(
                'Components not available in any location: {}'.format(
                    ', '.join(unavailable[:5])  # Show first 5
                )
            )
        
        if errors:
            raise ValidationError(errors)
        
        logger.info('Validation passed for {} components'.format(len(components)))
        return True
    
    def _format_size(self, bytes):
        """Format bytes as human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes < 1024.0:
                return '{:.1f} {}'.format(bytes, unit)
            bytes /= 1024.0
        return '{:.1f} PB'.format(bytes)
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FTRACK_SYNC_MAX_RETRIES` | 5 | Max retry attempts for failed transfers |

### Files Changed

| File | Change |
|------|--------|
| `source/ftrack_user_location/retry.py` | **NEW** - Retry decorator |
| `source/ftrack_user_location/validation.py` | **NEW** - ValidationError class |
| `source/ftrack_user_location/sync_engine.py` | Add retry, resume, validation methods |

### Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| Resume conflicts with concurrent syncs | Check availability before each transfer, skip if 100% |
| Validation false positives | Clear error messages, document edge cases |
| Retry storm on persistent failure | Max 5 retries, exponential backoff (~30s total) |

### Success Criteria

- [ ] Failed transfers retry automatically (visible in logs)
- [ ] Interrupted sync resumes from last completed component
- [ ] Pre-transfer validation catches disk full, permissions, bridge down
- [ ] Validation errors show clear, actionable messages
- [ ] Retry backoff visible: "attempt 2/5, retrying in 2s"

---

## Phase 4 — Advanced: Intelligent Caching & Offline Queue

**Timeline:** Weeks 4-5  
**Effort:** Large (3+ days)  
**Risk:** Medium  
**User Impact:** High (seamless offline/online, optimized transfers)

### Goal
Add intelligent local caching from bridge (transparent to user) and offline sync queue for disconnected users.

**Note:** Phase 4 REMOVES peer-to-peer HTTP transfer (security/complexity) and focuses on bridge-based intelligence.

### Technical Approach

#### 4.1 Intelligent Bridge Cache

Transparent local caching with LRU eviction:

```python
# source/ftrack_user_location/cache_manager.py

import os
import logging
import time
import json
from collections import OrderedDict

logger = logging.getLogger(__name__)


class BridgeCacheManager:
    """
    Manages local caching of bridge components.
    
    Provides fast access without user knowing source.
    LRU eviction when cache full.
    """
    
    def __init__(self, local_location, bridge_location, cache_size_gb=None):
        """
        Args:
            local_location: User's local Location
            bridge_location: ftrack.server Location
            cache_size_gb: Cache size limit (default: FTRACK_CACHE_SIZE_GB env or 50)
        """
        self.local = local_location
        self.bridge = bridge_location
        
        cache_size_gb = cache_size_gb or int(
            os.getenv('FTRACK_CACHE_SIZE_GB', 50)
        )
        self.cache_size_bytes = cache_size_gb * 1024 * 1024 * 1024
        
        # Track cached components (LRU)
        self._cache_index = OrderedDict()  # component_id -> metadata
        self._load_cache_index()
        
        logger.info(
            'Cache manager initialized: limit={}GB'.format(cache_size_gb)
        )
    
    def ensure_local(self, component):
        """
        Ensure component is in local cache.
        
        Downloads from bridge if needed, manages cache size via LRU eviction.
        Transparent to user.
        
        Args:
            component: Component entity
        
        Returns:
            str: Local path to component
        """
        component_id = component['id']
        component_name = component['name']
        
        # Check if already local
        local_avail = self.local.get_component_availability(component)
        if local_avail > 0:
            # Update access time
            self._cache_index.move_to_end(component_id, last=True)
            self._save_cache_index()
            
            logger.debug(
                'Component {} already cached locally'.format(component_name)
            )
            return self.local.get_filesystem_path(component)
        
        # Ensure cache space
        component_size = component.get('size', 0)
        self._ensure_cache_space(component_size)
        
        # Download from bridge to local
        logger.info(
            'Caching {} from bridge ({})'.format(
                component_name, self._format_size(component_size)
            )
        )
        
        try:
            # Get from bridge
            temp_path = self.bridge.get_component(
                component, self.local.accessor.prefix
            )
            
            # Add to local location
            self.local.add_component(component, temp_path)
            
            # Track in cache index
            self._cache_index[component_id] = {
                'name': component_name,
                'size': component_size,
                'cached_at': time.time()
            }
            self._cache_index.move_to_end(component_id, last=True)
            self._save_cache_index()
            
            logger.info('Cached {} locally'.format(component_name))
            
            return self.local.get_filesystem_path(component)
            
        except Exception as e:
            logger.error(
                'Failed to cache {} from bridge: {}'.format(component_name, e)
            )
            raise
    
    def _ensure_cache_space(self, required_bytes):
        """
        Ensure cache has space for new component.
        
        Evicts LRU components if needed.
        """
        current_size = sum(
            meta['size'] for meta in self._cache_index.values()
        )
        
        # Need to evict?
        if current_size + required_bytes > self.cache_size_bytes:
            logger.info(
                'Cache full ({}/{}), evicting LRU components'.format(
                    self._format_size(current_size),
                    self._format_size(self.cache_size_bytes)
                )
            )
            
            # Evict oldest entries until enough space
            while current_size + required_bytes > self.cache_size_bytes:
                if not self._cache_index:
                    break  # Nothing left to evict
                
                # Pop oldest (first item)
                component_id, meta = self._cache_index.popitem(last=False)
                
                # Remove from local location
                try:
                    component = self.local.session.get('Component', component_id)
                    self.local.remove_component(component)
                    
                    logger.debug(
                        'Evicted {} ({})'.format(
                            meta['name'], self._format_size(meta['size'])
                        )
                    )
                    
                    current_size -= meta['size']
                    
                except Exception as e:
                    logger.warning(
                        'Failed to evict {}: {}'.format(meta['name'], e)
                    )
            
            self._save_cache_index()
    
    def _load_cache_index(self):
        """Load cache index from disk."""
        index_path = os.path.join(
            self.local.accessor.prefix, '.ftrack_cache_index.json'
        )
        
        if os.path.exists(index_path):
            try:
                with open(index_path, 'r') as f:
                    data = json.load(f)
                    self._cache_index = OrderedDict(data.items())
                logger.debug('Loaded cache index: {} entries'.format(
                    len(self._cache_index)
                ))
            except Exception as e:
                logger.warning('Failed to load cache index: {}'.format(e))
    
    def _save_cache_index(self):
        """Save cache index to disk."""
        index_path = os.path.join(
            self.local.accessor.prefix, '.ftrack_cache_index.json'
        )
        
        try:
            with open(index_path, 'w') as f:
                json.dump(dict(self._cache_index), f, indent=2)
        except Exception as e:
            logger.warning('Failed to save cache index: {}'.format(e))
    
    def _format_size(self, bytes):
        """Format bytes as human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes < 1024.0:
                return '{:.1f}{}'.format(bytes, unit)
            bytes /= 1024.0
        return '{:.1f}PB'.format(bytes)
```

#### 4.2 Offline Sync Queue

Persist sync requests for offline users:

```python
# source/ftrack_user_location/offline_queue.py

import logging
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class OfflineSyncQueue:
    """
    Queue sync requests for offline destinations.
    
    Uses ftrack Job entity for persistence.
    """
    
    def __init__(self, session):
        self.session = session
    
    def publish_sync(self, dest_location, components, user_id):
        """
        Publish sync request.
        
        If destination appears offline, persists to Job entity.
        Otherwise, publishes event immediately.
        
        Args:
            dest_location: Destination Location entity
            components: List of Component entities
            user_id: User ID requesting sync
        """
        # Check if destination online (heuristic)
        is_online = self._is_destination_online(dest_location)
        
        if is_online:
            # Immediate event
            logger.info(
                'Destination {} online, publishing sync event'.format(
                    dest_location['name']
                )
            )
            self._publish_immediate(dest_location, components, user_id)
        else:
            # Queue for later
            logger.info(
                'Destination {} offline, queuing sync request'.format(
                    dest_location['name']
                )
            )
            self._queue_for_later(dest_location, components, user_id)
    
    def process_pending_syncs(self, my_location_name):
        """
        Process pending sync requests for this location.
        
        Call on startup to process any queued syncs.
        
        Args:
            my_location_name: Name of current location
        """
        # Query pending sync jobs for this location
        pending = self.session.query(
            'Job where status is "pending" and '
            'data like "%pending_sync%"'
        ).all()
        
        processed = 0
        for job in pending:
            try:
                data = json.loads(job['data'])
                
                # Check if for this location
                target_location = data.get('target_location')
                if target_location != my_location_name:
                    continue
                
                # Check TTL
                created_at = datetime.fromisoformat(data['created_at'])
                ttl_days = data.get('ttl_days', 7)
                
                if datetime.utcnow() - created_at > timedelta(days=ttl_days):
                    # Expired
                    job['status'] = 'failed'
                    data['error'] = 'Sync expired (TTL exceeded)'
                    job['data'] = json.dumps(data)
                    self.session.commit()
                    logger.warning(
                        'Sync job {} expired (TTL)'.format(job['id'])
                    )
                    continue
                
                # Execute sync
                logger.info('Processing pending sync job {}'.format(job['id']))
                self._execute_pending_sync(job, data)
                
                processed += 1
                
            except Exception as e:
                logger.error(
                    'Failed to process sync job {}: {}'.format(job['id'], e)
                )
                job['status'] = 'failed'
                data = json.loads(job['data'])
                data['error'] = str(e)
                job['data'] = json.dumps(data)
                self.session.commit()
        
        if processed > 0:
            logger.info('Processed {} pending sync requests'.format(processed))
    
    def _is_destination_online(self, dest_location):
        """
        Heuristic: check if destination location appears online.
        
        Could be enhanced with presence tracking, heartbeat, etc.
        For now, assume always offline (safer default).
        """
        # TODO: Implement presence detection
        # For now, always queue (safer - ensures persistence)
        return False
    
    def _publish_immediate(self, dest_location, components, user_id):
        """Publish sync event immediately."""
        import ftrack_api.event.base
        
        event = ftrack_api.event.base.Event(
            topic='ftrack.sync',
            data={
                'actionIdentifier': 'ftrack-to-{}'.format(dest_location['name']),
                'components': [
                    {'id': c['id'], 'name': c['name']} for c in components
                ],
                'locations': {
                    'sync': self.session.query(
                        'Location where name is "ftrack.server"'
                    ).one()['id'],
                    'destination': dest_location['id']
                }
            },
            source={'user': {'id': user_id}}
        )
        
        self.session.event_hub.publish(event)
    
    def _queue_for_later(self, dest_location, components, user_id):
        """Queue sync request as Job entity."""
        job = self.session.create('Job', {
            'data': json.dumps({
                'type': 'pending_sync',
                'target_location': dest_location['name'],
                'components': [
                    {'id': c['id'], 'name': c['name']} for c in components
                ],
                'created_at': datetime.utcnow().isoformat(),
                'ttl_days': 7,
                'description': 'Queued sync for {} ({} components)'.format(
                    dest_location['name'], len(components)
                )
            }),
            'user': self.session.get('User', user_id),
            'status': 'pending'
        })
        self.session.commit()
        
        logger.info(
            'Queued sync job {} for {}'.format(
                job['id'], dest_location['name']
            )
        )
    
    def _execute_pending_sync(self, job, data):
        """Execute queued sync from Job data."""
        from .sync_engine import SyncEngine
        
        # Extract data
        dest_location_name = data['target_location']
        components_data = data['components']
        
        # Resolve entities
        dest_location = self.session.query(
            'Location where name is "{}"'.format(dest_location_name)
        ).one()
        
        components = [
            self.session.get('Component', c['id'])
            for c in components_data
        ]
        
        # Execute sync
        engine = SyncEngine(self.session)
        engine.sync_with_resume(
            dest_location, components, job['user']['id'], job=job
        )
        
        job['status'] = 'done'
        self.session.commit()
```

#### 4.3 Update Service for Offline Processing

Integrate offline queue into sync service:

```python
# In source/ftrack_user_location/sync_service.py

from .offline_queue import OfflineSyncQueue
from .cache_manager import BridgeCacheManager

class SyncService:
    def __init__(self, max_workers=4):
        # ... existing init ...
        
        # Offline queue
        self._offline_queue = OfflineSyncQueue(self._main_session)
        
        # Cache manager
        self._cache_manager = BridgeCacheManager(
            self._bridge.local_location,
            self._bridge.bridge_location
        )
    
    def start(self):
        """Start service and process pending syncs."""
        logger.info('Starting SyncService...')
        
        # Process any pending offline syncs
        my_location = self._bridge.local_location['name']
        self._offline_queue.process_pending_syncs(my_location)
        
        # ... existing event subscriptions ...
        
        self._main_session.event_hub.wait()
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FTRACK_CACHE_SIZE_GB` | 50 | Local cache size limit (GB) |
| `FTRACK_OFFLINE_TTL_DAYS` | 7 | Queued sync expiration (days) |

### Files Changed

| File | Change |
|------|--------|
| `source/ftrack_user_location/cache_manager.py` | **NEW** - Intelligent caching |
| `source/ftrack_user_location/offline_queue.py` | **NEW** - Offline sync queue |
| `source/ftrack_user_location/sync_service.py` | Integrate cache manager and offline queue |
| `resource/hook/connect_plugin_hook.py` | Process pending syncs on startup |

### Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| Cache thrashing on small limit | Default 50GB, configurable, log evictions |
| Offline queue bloat | TTL-based cleanup (7 days), periodic purge |
| LRU eviction removes active files | Check access time, skip recently used components |

### Success Criteria

- [ ] Components transparently cached from bridge
- [ ] LRU eviction works when cache full (visible in logs)
- [ ] Sync requests queued when destination offline
- [ ] Pending syncs processed on destination startup
- [ ] Cache index persists across restarts

---

## Phase 5 — Deferred: Delta/Incremental Sync

**Timeline:** Future  
**Effort:** Very High  
**Risk:** High  
**User Impact:** Medium (large files only)

### Status: NOT PLANNED

**Reason:** Current ftrack API doesn't support partial file transfers. The `Accessor.add_component()` method only supports full-file operations.

### What Would Be Needed

1. **File fingerprinting** - SHA-256 of fixed-size chunks
2. **Chunk metadata storage** - Store chunk hashes in component metadata
3. **Custom ChunkedAccessor** - Read/write byte ranges
4. **Chunk comparison** - Identify changed chunks only
5. **Partial transfer protocol** - Transfer only changed chunks

### Alternative Sketch

```python
class ChunkedDiskAccessor(DiskAccessor):
    """Accessor with chunk-level operations."""
    
    CHUNK_SIZE = 1024 * 1024  # 1MB chunks
    
    def get_chunk_hash(self, resource, chunk_index):
        """Get hash of specific chunk."""
        path = self.get_filesystem_path(resource)
        with open(path, 'rb') as f:
            f.seek(chunk_index * self.CHUNK_SIZE)
            chunk = f.read(self.CHUNK_SIZE)
            return hashlib.sha256(chunk).hexdigest()
    
    def write_chunk(self, resource, chunk_index, data):
        """Write chunk to file (for partial updates)."""
        # Requires complex file reconstruction
        pass
```

### Escalation Trigger

Revisit when:
- ftrack adds partial file transfer support to `Accessor` API
- Teams report that full re-transfer of multi-GB files is a recurring, measurable bottleneck
- Custom chunk-aware accessor becomes feasible

---

## Dependency Chain

```
Phase 0 (Bridge Architecture)
    ├── Required by: Phase 1 (Service uses bridge)
    ├── Required by: Phase 2 (Smart source resolution)
    └── Required by: Phase 4 (Cache manager)

Phase 1 (Service Architecture)
    ├── Required by: Phase 2 (Parallel needs workers)
    ├── Required by: Phase 3 (Retry needs service)
    └── Required by: Phase 4 (Offline queue needs service)

Phase 2 (Performance)
    └── Can parallel with: Phase 3 (Resilience)

Phase 3 (Resilience)
    └── Required by: Phase 4 (Resume for offline)

Phase 4 (Advanced)
    └── No dependencies

Phase 5 (Delta Sync)
    └── Blocked: Waiting for ftrack API support
```

**Critical Path:** Phase 0 → Phase 1 → Phase 2/3 (parallel) → Phase 4

---

## Implementation Order

### Immediate (Start Here)
1. Implement `LocationBridge` class (Phase 0)
2. Update location priority to 100 (Phase 0)
3. Create `SyncService` with session management (Phase 1)
4. Extract `SyncEngine` class (Phase 1)

### Week 1 Completion (Phase 0 + 1)
- Bridge manager operational
- Service architecture complete
- Background execution working
- Progress tracking with percentages

### Week 2 Completion (Phase 2)
- Smart source resolution working
- Parallel transfers functional
- Optional component selection UI

### Week 3 Completion (Phase 3)
- Retry with exponential backoff
- Resume from checkpoints
- Bridge validation

### Weeks 4-5 Completion (Phase 4)
- Intelligent caching operational
- Offline queue working
- Pending sync processing on startup

---

## Testing Strategy

### Unit Tests
- `LocationBridge` with mocked locations
- `SyncEngine` with mocked sessions
- Retry decorator with simulated failures
- Cache manager with temp directories
- Offline queue with in-memory session

### Integration Tests
- Full sync flow with real ftrack API (test instance)
- Bridge fallback chain (local → bridge → origin)
- Resume after interrupted transfer
- Cache eviction under size pressure
- Offline queue persistence across restarts

### Performance Tests
- Parallel vs sequential benchmark (10+ components)
- Smart source resolution overhead
- Cache hit/miss ratios
- Memory usage with large file counts

---

## Migration Notes

### Backward Compatibility
- Keep existing `on_sync_to_remote()` and `on_sync_to_destination()` as wrappers
- Deprecated but functional for one major version
- New code uses `SyncEngine` and `LocationBridge` directly

### Configuration Migration
- New env vars added with sensible defaults
- Existing behavior unchanged if vars not set
- Document new options in README

### Database Migration
- No schema changes needed
- Uses existing `Job` entity
- Adds new fields to `data` JSON (backward compatible)

### Location Priority Migration
- **BREAKING**: User location priority changes from `1-sys.maxsize` to `100`
- This enables bridge fallback but may affect custom location hierarchies
- Document: verify custom location priorities after upgrade

---

## Success Metrics

| Metric | Current | Phase 0 Target | Phase 2 Target | Phase 4 Target |
|--------|---------|----------------|----------------|----------------|
| **Transparency** | Users pick source/dest | Bridge auto-resolves | Smart per-component | Invisible caching |
| **Transfer Speed** | Sequential | Same | 2-4x parallel | 2-4x + cache hits |
| **User Awareness** | "Sync X to Y" | "Getting file..." | "3/10 complete" | "File available" |
| **Availability** | Manual check | Bridge fallback | Multi-source | Offline queue |
| **Reliability** | Fail on first error | Bridge validation | Retry + resume | Queue + resume |

---

## Appendix: File Map

### New Files
```
source/ftrack_user_location/
├── bridge_manager.py          # Phase 0: Bridge abstraction
├── sync_service.py            # Phase 1: Service lifecycle
├── sync_engine.py             # Phase 1: Core transfer engine
├── retry.py                   # Phase 3: Retry decorator
├── validation.py              # Phase 3: ValidationError
├── cache_manager.py           # Phase 4: Intelligent caching
└── offline_queue.py           # Phase 4: Offline sync queue
```

### Modified Files
```
source/ftrack_user_location/
└── sync.py                    # Refactor to wrappers (Phase 1)

resource/location/
└── user_location.py           # Update priority (Phase 0)

resource/hook/
├── sync_action.py             # Optional component selection (Phase 2)
└── connect_plugin_hook.py     # Start service, process pending (Phase 1, 4)
```

---

## Key Architectural Decisions

### 1. Why Bridge Instead of Peer-to-Peer?

**Decision:** All transfers route through ftrack.server as bridge/backup. No direct peer-to-peer.

**Rationale:**
- **Audit Trail**: Every file backed up centrally
- **Security**: No temporary HTTP servers, no firewall configuration
- **Simplicity**: One transfer pattern, not two
- **Reliability**: Bridge is always available (cloud), peers may be offline
- **Transparency**: User never sees where files come from

**Trade-off:** Two-hop transfer (A→bridge→B) vs one-hop (A→B), but bridge caching mitigates this.

### 2. Why Location Priority 100?

**Decision:** User locations get priority 100 (not `1-sys.maxsize`).

**Rationale:**
- ftrack.server has priority ~50 (built-in)
- Lower number = higher priority for reads
- Priority 100 means ftrack.server checked before user locations
- Users still write locally (accessor/structure control writes, not priority)
- Enables transparent bridge fallback

### 3. Why LRU Cache Instead of Time-Based?

**Decision:** Cache eviction uses LRU (least recently used), not age-based.

**Rationale:**
- Active files stay cached (frequent access)
- Old but actively used files not evicted
- Simple to implement (OrderedDict)
- Predictable behavior (size-bound, not time-bound)

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-06-09 | Sisyphus | Initial plan creation |
| 2.0 | 2026-06-09 | Claude | Bridge architecture revision, transparent access model, removed P2P |

---

*End of Plan*
