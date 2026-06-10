# Architecture Clarification: Mandatory Bridge Pattern

**Date:** 2026-06-09  
**Version:** 1.0

---

## Core Constraint

**Users cannot access each other's file systems over the internet.**

```
User A (Tokyo)  ──X──  User B (London)
                 ❌
        Direct access IMPOSSIBLE
        (firewall, NAT, internet separation)
```

Therefore, **ftrack.server is the MANDATORY intermediary**, not an optional optimization.

---

## Correct Architecture

```
┌─────────────────────┐                  ┌─────────────────────┐
│   User A (Tokyo)    │                  │   User B (London)   │
│                     │                  │                     │
│ Local Storage:      │                  │ Local Storage:      │
│ - Fast read/write   │                  │ - Fast read/write   │
│ - Isolated          │                  │ - Isolated          │
│ - NOT accessible    │                  │ - NOT accessible    │
│   to User B         │                  │   to User A         │
└──────────┬──────────┘                  └──────────┬──────────┘
           │                                        │
           │ Auto Upload                            │ On-Demand
           │ (background)                           │ Download
           │                                        │
           ▼                                        ▼
    ┌──────────────────────────────────────────────────────┐
    │         ftrack.server (Mandatory Bridge)             │
    │                                                       │
    │  - ONLY location accessible to all users             │
    │  - Persistent storage/backup                         │
    │  - ALL site-to-site transfers go through here        │
    └──────────────────────────────────────────────────────┘
```

---

## Transfer Flows

### Flow 1: User A Publishes New Asset

```
1. User A creates file locally
   → ~/Documents/local_ftrack_projects/project/asset.ma
   
2. User A publishes in DCC
   → ftrack_api creates Component entity
   → Component registered in User A's location
   
3. BACKGROUND: Auto-upload to bridge
   → sync_service detects new component
   → Uploads User A location → ftrack.server
   → Now available to all users
```

**User A Experience:** "Published" (instant, upload happens in background)

### Flow 2: User B Accesses Asset

```
1. User B opens asset browser
   → Sees asset (metadata from ftrack database)
   
2. User B double-clicks to open
   → DCC requests file path from ftrack_api
   → ftrack_api checks: Local cache? NO
   → ftrack_api checks: ftrack.server? YES
   → Downloads ftrack.server → User B local cache
   
3. DCC opens local cached file
   → Future opens use cached copy (instant)
```

**User B Experience:** "Opening..." (2-10 seconds first time, instant after)

### Flow 3: Component Not in Bridge Yet

```
1. User B requests asset immediately after User A publishes
   → Local cache: NO
   → ftrack.server: NO (background upload still in progress)
   
2. System response:
   Option A: Wait for upload to complete (polling)
   Option B: Show error "Asset still uploading, try again shortly"
   Option C: Queue request, notify when available
```

**This is the ONLY cross-user access pattern possible.**

---

## Why This Matters for the PLAN

### ❌ WRONG Assumptions (In Original Plan)

1. "Smart source resolution across multiple user locations"
   - **Wrong:** Cannot access other user locations
   
2. "Fallback chain: local → bridge → origin"
   - **Wrong:** "origin" user location is not accessible
   
3. "Location priority determines read preference"
   - **Misleading:** Priority only matters for THIS user's local vs bridge
   
4. "Find where component exists and trigger origin → bridge transfer"
   - **Wrong:** Cannot query other users' locations to "find" components

### ✅ CORRECT Architecture

1. **Only two accessible locations per user:**
   - My local location (only I can access)
   - ftrack.server (everyone can access)
   
2. **Simple two-location pattern:**
   - Read: Check local first, then bridge
   - Write: Write local, upload to bridge (background)
   
3. **No cross-user direct access:**
   - Users upload TO bridge
   - Users download FROM bridge
   - Never User A → User B directly

---

## Impact on Phase Implementations

### Phase 0: Bridge Architecture

**Change:** Remove "smart multi-location resolution"

```python
class LocationBridge:
    """Only manages TWO locations: local + bridge."""
    
    def get_component(self, component):
        # Check local
        if self.local_location.get_component_availability(component) > 0:
            return self.local_location.get_component(component)
        
        # Check bridge (ONLY other accessible location)
        if self.bridge_location.get_component_availability(component) > 0:
            local_path = self.bridge_location.get_component(component)
            self._cache_locally(component, local_path)
            return local_path
        
        # Not available ANYWHERE this user can access
        raise ComponentNotFoundError(
            "Component not in bridge. Origin user must upload first."
        )
```

### Phase 1: Service Architecture

**Keep:** Background upload to bridge

```python
class SyncService:
    def on_component_created(self, event):
        """When user creates component locally, auto-upload to bridge."""
        component = event['data']['component']
        
        # Submit background upload
        self._executor.submit(
            self._upload_to_bridge,
            component
        )
    
    def _upload_to_bridge(self, component):
        """Upload from local to bridge (background)."""
        self.bridge_location.add_component(
            component,
            self.local_location
        )
```

### Phase 2: Parallel Transfers

**Simplify:** No smart source resolution needed

```python
def sync_components_parallel(self, components):
    """Download multiple components from bridge in parallel."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(self._download_from_bridge, c)
            for c in components
        ]
        # ...
```

### Phase 4: Offline Queue

**Keep:** Queue requests when bridge unavailable

- User A tries to upload but network down → queue for retry
- User B tries to download but component not in bridge yet → queue/wait/notify

---

## Revised Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| **Locations per user** | Local + Bridge + Other users | **Local + Bridge ONLY** |
| **Source resolution** | Find best among N locations | **Check local, then bridge** |
| **Fallback chain** | Local → Bridge → Origin | **Local → Bridge → ERROR** |
| **Cross-user access** | Via bridge OR direct (P2P) | **Via bridge ONLY (mandatory)** |

---

## Summary

**The architecture is simpler than v2.0 of the PLAN suggests:**

1. Users have TWO locations: `my_local` and `ftrack.server`
2. Other users' locations are NOT accessible (firewalls/internet)
3. ftrack.server is the MANDATORY shared location
4. All site-to-site = upload to bridge + download from bridge
5. No "smart resolution" across multiple user locations needed

**Update PLAN.md to reflect this simpler, correct model.**

---

## Next Steps

1. Update Phase 0 to remove multi-location resolution
2. Update Phase 1 to focus on background bridge uploads
3. Update Phase 2 to parallel downloads from bridge (not smart source resolution)
4. Update Phase 4 to handle bridge-only offline scenarios
5. Remove all references to "finding origin location" or "fallback to origin"

The bridge is not a fallback—it's the ONLY way users share files.
