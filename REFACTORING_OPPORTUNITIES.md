# Refactoring Opportunities - Using ftrack-action-handler Methods

**Analysis Date**: 2026-06-10

---

## Summary

**Status**: ✅ REFACTORING COMPLETE (2026-06-10)

After reviewing the ftrack-action-handler BaseAction and AdvancedBaseAction classes, we identified opportunities to use official methods instead of reinventing functionality. The recommended migration to AdvancedBaseAction has been completed.

---

## 1. ✅ DONE: _get_entity_type()

**Status**: ✅ Refactored in commit 085ff22

**What**: Translates entity types from event data (lowercase) to proper schema names (PascalCase)

**Usage**: 
```python
entity_type = self._get_entity_type(item)  # 'assetversion' → 'AssetVersion'
```

---

## 2. Consider: Job Management Methods (AdvancedBaseAction)

**Available Methods**:
- `create_job(event, description)` - Creates Job owned by event user
- `attach_component_to_job(job_id, component_id, description)` - Attach report
- `mark_job_as_done(job_id, description)` - Update Job status
- `mark_job_as_failed(job_id, error_message)` - Mark Job as failed

**Current Implementation**: 
We handle Job creation manually in `sync.py` with executor ownership pattern.

**Decision**: **KEEP CURRENT IMPLEMENTATION**

**Reason**:
1. Our Jobs need special ownership (executor, not requester) - critical for multi-user
2. `create_job()` uses `event['source']['user']['id']` which would be WRONG for us
3. We need custom Job.data structure with multiple fields
4. Our Job lifecycle is more complex (batch commits, re-query pattern)
5. `attach_component_to_job()` could be useful but we handle it differently

**Potential Use**: Could use `attach_component_to_job()` for report attachment

---

## 3. Consider: _identify_entity_() (AdvancedBaseAction)

**What It Does**:
Tries multiple entity types (__KNOWN_TYPES__) to identify an entity when type is unknown.

**Method**:
```python
def _identify_entity_(self, entity):
    entity_types = self.__KNOWN_TYPES__  # ['Context', 'AssetVersion', 'FileComponent']
    _id = entity.get('entityId')
    for entity_type in entity_types:
        entity = self.session.get(entity_type, _id)
        if getattr(entity, 'entity_type', None):
            return entity.entity_type
```

**Current Usage**: We don't use this pattern

**Decision**: **NOT NEEDED**

**Reason**: We always know the entity type from event data (it's AssetVersion)

---

## 4. Consider: _get_selection_() (AdvancedBaseAction)

**What It Does**:
Extracts selection from event data

**Method**:
```python
def _get_selection_(self, event):
    data = event['data']
    return data.get('selection', [])
```

**Current Usage**: We use `event['data'].get('selection', [])`

**Decision**: **COULD REFACTOR (Low Priority)**

**Benefit**: Slightly cleaner, but minimal gain

---

## 5. Consider: Permission Checking (AdvancedBaseAction)

**Available Methods**:
- `_check_permissions_(action_user)` - Checks roles/groups
- `_check_limit_to_user_(action_user)` - Checks user limits
- `_check_allowed_types_(selection)` - Checks allowed/ignored entity types

**Properties**:
- `allowed_roles = []`
- `allowed_groups = []`
- `ignored_types = []`
- `allowed_types = []`
- `limit_to_user = None`

**Current Usage**: We check entity type in `discover()` method manually

**Decision**: **COULD MIGRATE TO AdvancedBaseAction (Medium Priority)**

**Benefits**:
- Built-in permission filtering
- User role/group checks
- Entity type filtering
- Less boilerplate

**Migration**:
```python
# Change base class
class SyncAction(AdvancedBaseAction):  # Instead of BaseAction
    
    # Set allowed types
    allowed_types = ['AssetVersion']
    
    # Remove manual discover() check
    # The base class handles it automatically
```

---

## 6. Consider: Settings Persistence (AdvancedBaseAction)

**Available Methods**:
- `read_settings_from_user(event)` - Read settings from user metadata
- `write_settings_to_user(event, settings)` - Save settings to user metadata

**What**: Stores action settings in user metadata

**Current Usage**: We don't persist user preferences

**Decision**: **FUTURE ENHANCEMENT**

**Potential Use**: 
- Remember last selected source/destination locations
- User preferences (default sync behavior)

---

## 7. Consider: run_as_user (AdvancedBaseAction)

**What**: If `run_as_user = True`, creates a new session as the event user

**Current Usage**: We always run as the session user (machine user)

**Decision**: **NOT APPLICABLE**

**Reason**: 
Our architecture requires running as the machine's session user (executor pattern).
The `run_as_user` pattern would break our multi-user fix.

---

## 8. Consider: User Retrieval

**AdvancedBaseAction Method**:
```python
def get_action_user(self, event):
    return self.session.get('User', event['source']['user']['id'])
```

**Current Usage**: 
```python
session_user = session.query('User where username is "{}"'.format(session.api_user)).first()
requesting_user = session.get('User', requesting_user_id)
```

**Decision**: **KEEP CURRENT IMPLEMENTATION**

**Reason**: We need executor (session.api_user), not event user

---

## Recommendations

### ✅ COMPLETED: Migrate to AdvancedBaseAction (commit 4090161)

**Why we did this**:
1. Get permission checking for free
2. Cleaner entity type filtering
3. More standard ftrack action patterns
4. Could use Job management methods in future

**Implementation** (commit 4090161):

```python
# ✅ 1. Changed import
from ftrack_action_handler.action import AdvancedBaseAction

# ✅ 2. Changed base class
class SyncAction(AdvancedBaseAction):
    
    # ✅ 3. Set entity type filter
    allowed_types = ['AssetVersion']
    description = 'Sync components between user locations and ftrack.server'
    
    # ✅ 4. Simplified discover() - removed manual type checking
    def discover(self, session, entities, event):
        # Base class already filtered by allowed_types
        if not entities:
            return False
        return True
    
    # ✅ 5. Used base class method for selection
    selection = self._get_selection_(event)  # Instead of event['data'].get('selection', [])
```

**Release**: v0.3.5 (2026-06-10)

### Medium Priority: Use attach_component_to_job()

**Current** (in sync_report.py):
```python
session.create('JobComponent', {
    'component_id': component['id'],
    'job_id': job_id
})
session.commit()
```

**Could Use**:
```python
# But we'd need to inherit from AdvancedBaseAction or access its methods
# Keep current for now as it's cleaner without inheritance
```

### Low Priority: Refactor Small Methods

**Examples**:
- Use `_get_selection_()` instead of inline `event['data'].get('selection', [])`
- Consider settings persistence for user preferences

---

## What NOT to Change

### ✅ Keep: Custom Job Creation Pattern

Our Job creation with executor ownership is CRITICAL for multi-user support.
The AdvancedBaseAction.create_job() would break this.

### ✅ Keep: Session User Pattern

We need `session.api_user` (executor), not `event['source']['user']` (requester).

### ✅ Keep: Job Lifecycle Pattern

Our batch commit + re-query pattern is essential for performance.

### ✅ Keep: Custom Event Subscriptions

Our event subscriptions for {location}-to-ftrack and ftrack-to-{location} 
are unique to this plugin's architecture.

---

## Migration Risk Assessment

**Migrating to AdvancedBaseAction**:
- **Risk**: Low-Medium
- **Benefit**: Medium-High
- **Complexity**: Low
- **Testing Required**: Full integration tests

**Key Risks**:
1. Might affect event subscription patterns
2. Need to ensure Job creation still uses executor pattern
3. Permission checks might be too restrictive
4. Need to test with all scenarios (local, remote, cross-user)

**Mitigation**:
- Test in isolated branch first
- Verify all sync scenarios work
- Check event subscriptions still correct
- Validate Job ownership pattern unchanged

---

## Conclusion

**✅ Completed Actions** (v0.3.5):
1. ✅ **DONE**: Use `_get_entity_type()` - Implemented in commit 085ff22
2. ✅ **DONE**: Migrate to AdvancedBaseAction - Implemented in commit 4090161
3. ✅ **DONE**: Use `_get_selection_()` base class method
4. ✅ **DONE**: Simplified discover() method using declarative filtering

**Future Enhancements** (optional):
- 💭 **CONSIDER**: Use settings persistence for user preferences
- 💭 **CONSIDER**: Add role/group-based permissions using AdvancedBaseAction features

**Not Changed** (by design):
- ✅ **KEPT**: Custom `create_job()` - Executor ownership critical for multi-user
- ✅ **KEPT**: Session user pattern - Need machine user, not event user  
- ✅ **KEPT**: Job lifecycle with re-query - Essential for reliability
- ✅ **KEPT**: Custom event subscriptions - Unique to our architecture

**Status**: ✅ Refactoring complete. Code now follows official ftrack patterns while preserving critical multi-user functionality.
