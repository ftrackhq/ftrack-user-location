# Implementation Guide: Critical Bug Fixes

**Target**: Phase 0 - Critical Bug Fixes  
**Files**: `source/ftrack_user_location/sync.py`  
**Estimated Time**: 4-6 hours

---

## Overview

This guide provides step-by-step instructions to fix the three critical bugs blocking production:

1. **Cross-User Job Permission Errors** - Jobs owned by wrong user
2. **Job Lifecycle Errors** - "must be committed first" when updating Jobs
3. **Session Commit Storm** - Per-component commits cause 5-10 minute sync times

---

## Bug #0: Job Ownership + Lifecycle Fixes

### Changes Required

Both `on_sync_to_destination()` and `on_sync_to_remote()` need these fixes:

1. Change Job owner from requesting user to session user (executor)
2. Store `job_id` after creation
3. Use `session.get('Job', job_id)` before all Job updates
4. Track requesting user in `Job.data` metadata

### File: `source/ftrack_user_location/sync.py`

#### Function 1: `on_sync_to_destination()`

**Location**: Lines 11-170

**Current Code (Broken)**:
```python
def on_sync_to_destination(session, source_id, destination_id, components, user_id):
    # ... location setup ...
    
    # ❌ WRONG: Job owned by requesting user
    job = session.create('Job', {
        'data': json.dumps({
            'description': "Sync from {} to {} ".format(
                source_name,
                destination_name
            )
        }),
        'user': session.get('User', user_id),  # ❌ Requesting user
        'status': 'running'
    })
    session.commit()
    
    # ... later ...
    job['status'] = 'failed'  # ❌ Fails with permission error
    session.commit()
```

**Fixed Code**:
```python
def on_sync_to_destination(session, source_id, destination_id, components, requesting_user_id):
    '''Callback for when files are copied from the cloud location into the
    destination one.

        *source_id* : The id of the source location.
        *destination_id* : The id of the destination location.
        *components* : a list of ids of all the components to be copied over.
        *requesting_user_id* : the id of the user who requested the sync.

    '''
    components = [session.get('Component', cid['id']) for cid in components]

    # get location objects
    source_location = session.get('Location', source_id)
    destination_location = session.get('Location', destination_id)

    # get location accessors
    source_accessor = source_location.accessor
    destination_accessor = destination_location.accessor

    # get the location names
    source_name = source_location['name']
    destination_name = destination_location['name']

    logger.info(
        "Syncing from {} to {}".format(
            source_name,
            destination_name,
        )
    )

    # ✅ FIX: Get session user (executor)
    session_user = session.query(
        'User where username is "{}"'.format(session.api_user)
    ).first()

    # ✅ FIX: Create Job owned by executor
    job = session.create('Job', {
        'data': json.dumps({
            'description': "Sync from {} to {} ".format(
                source_name,
                destination_name
            ),
            'requested_by': requesting_user_id  # Track requester in metadata
        }),
        'user': session_user,  # ✅ Executor owns Job
        'status': 'running'
    })
    session.commit()
    
    # ✅ FIX: Store job ID for re-querying
    job_id = job['id']

    # sanity checks for the transfer
    if not all([source_accessor, destination_accessor]):
        # ✅ FIX: Re-query before updating
        job = session.get('Job', job_id)
        
        message = 'Locations are not accessible : {}, {}'.format(
            destination_name,
            source_name
        )
        job['data'] = json.dumps({
            'description': message,
            'requested_by': requesting_user_id
        })
        job['status'] = 'failed'
        logger.error(message)
        session.commit()
        return

    # ✅ FIX: Track sync results
    components_synced = []
    components_failed = []

    # now try to do the sync for each component
    for component in components:
        component_id = component['id']
        component_name = component['name']

        # exclude ftrack-review component names
        if 'ftrackreview' in component_name:
            continue

        destination_available = destination_location.get_component_availability(
            component
        )

        source_available = source_location.get_component_availability(
            component
        )

        if source_available == 0.0:
            status = 'Component "{}" is not available in {}'.format(
                component_name, source_name
            )
            logger.warning(status)
            components_failed.append({
                'name': component_name,
                'error': 'Not available in source'
            })
            continue
        else:
            status = 'component "{}" is available in {}'.format(
                component_name, source_name
            )
            logger.debug(status)

        if destination_available == 100.0:
            status = 'Component "{}" already exists in {}'.format(
                component_name, destination_name
            )
            logger.info(status)
            components_synced.append(component_name)
            continue
        else:
            status = 'component "{}" is not available in {}'.format(
                component_name, destination_name
            )
            logger.debug(status)

        # copy the component from source to destination
        try:
            destination_location.add_component(
                component, source_location
            )
            components_synced.append(component_name)
            logger.info(
                'Added component "{}" from {} to {}'.format(
                    component_name, source_name, destination_name
                )
            )

        except ftrack_api.exception.ComponentInLocationError:
            status = 'Component "{}" already in location {}'.format(
                component_name, destination_name
            )
            logger.warning(status)
            components_synced.append(component_name)

        except Exception:
            import traceback
            logger.error(traceback.format_exc())
            components_failed.append({
                'name': component_name,
                'error': 'Sync operation failed'
            })

    # ✅ FIX: Batch commit after all components
    session.commit()

    # ✅ FIX: Re-query Job before final update
    job = session.get('Job', job_id)
    
    # ✅ FIX: Set final status based on results
    if components_failed:
        job['status'] = 'failed'
        job['data'] = json.dumps({
            'description': '{} components failed, {} succeeded'.format(
                len(components_failed),
                len(components_synced)
            ),
            'requested_by': requesting_user_id,
            'components_synced': components_synced,
            'components_failed': components_failed
        })
    else:
        job['status'] = 'done'
        job['data'] = json.dumps({
            'description': 'Sync from {} to {} completed successfully'.format(
                source_name,
                destination_name
            ),
            'requested_by': requesting_user_id,
            'components_synced': components_synced
        })
    
    session.commit()
    logger.info('Sync job {} completed'.format(job_id))
```

---

#### Function 2: `on_sync_to_remote()`

**Location**: Lines 159-390

**Current Code Pattern (Broken)**:
```python
def on_sync_to_remote(session, source_id, destination_id, user_id, selection):
    # ... setup ...
    
    # ❌ WRONG: Job owned by requesting user
    job = session.create('Job', {
        'data': json.dumps({
            'description': message
        }),
        'user': user,  # ❌ Requesting user
        'status': 'running'
    })
    session.commit()
    
    # ... later ...
    job['status'] = 'done'  # ❌ Fails
    session.commit()
```

**Key Changes** (same pattern as on_sync_to_destination):

1. Rename parameter from `user_id` to `requesting_user_id`
2. Query for session user (executor)
3. Create Job owned by session user
4. Store `job_id` after commit
5. Track requesting user in Job.data
6. Use `session.get('Job', job_id)` before all updates
7. Batch commits (once after all components)
8. Track failures properly

**Apply the same pattern** shown above to `on_sync_to_remote()`.

---

## Bug #1: Session Commit Storm Fix

**Already Fixed** by the changes above:

✅ Before: `session.commit()` after every component operation (100+ commits)  
✅ After: One `session.commit()` after all component operations + one for final Job update

**Impact**:
- Before: 100 components = 200+ commits = 5-10 minutes
- After: 100 components = 2 commits = <2 minutes

---

## Testing Checklist

### Unit Tests

- [ ] Session user query returns correct user
- [ ] Job created with session user as owner
- [ ] Job ID stored correctly
- [ ] `session.get('Job', job_id)` returns Job successfully
- [ ] Job updates work without permission errors
- [ ] Multiple Job updates in sequence work
- [ ] Requesting user ID tracked in Job.data

### Integration Tests

- [ ] Single-user sync works (User A → User A's machine)
- [ ] Cross-user sync works (User A triggers → User B's machine executes)
- [ ] Job visible in ftrack UI with correct owner
- [ ] Job.data contains `requested_by` field
- [ ] Failed components tracked correctly
- [ ] Job status transitions correctly (running → done/failed)

### Multi-User Scenario

**Setup**: Two machines, two different ftrack users

**Test 1**: User A triggers sync on User B's machine
- [ ] No permission errors
- [ ] Job owned by User B (executor)
- [ ] Job.data shows User A as requester
- [ ] Sync completes successfully

**Test 2**: User B triggers sync on User A's machine
- [ ] No permission errors
- [ ] Job owned by User A (executor)
- [ ] Job.data shows User B as requester
- [ ] Sync completes successfully

### Performance Test

- [ ] 100-component sync completes in <2 minutes
- [ ] Verify only 2 session commits (not 200+)
- [ ] Memory usage stable
- [ ] No database timeout errors

---

## Rollback Plan

If issues discovered after deployment:

1. **Revert commit**: Use git to revert to previous version
2. **Document issue**: Record what failed and under what conditions
3. **Disable multi-user workflows**: Set documentation to warn single-user only
4. **Schedule fix**: Plan additional time to address root cause

---

## Validation

After implementing fixes, run these validation commands:

```python
# Test script: test_job_fixes.py
import ftrack_api
import json

# Connect as User B
session = ftrack_api.Session(
    api_user='user_b',
    api_key='<user_b_key>'
)

# Simulate User A requesting sync
user_a_id = '<user_a_id>'

# Get session user (User B)
session_user = session.query(
    'User where username is "{}"'.format(session.api_user)
).first()

print(f"Session user: {session_user['username']}")

# Create Job owned by session user
job = session.create('Job', {
    'user': session_user,
    'status': 'running',
    'data': json.dumps({
        'description': 'Test sync',
        'requested_by': user_a_id
    })
})
session.commit()

# Store job ID
job_id = job['id']
print(f"Job created: {job_id}")
print(f"Job owner: {job['user']['username']}")

# Re-query before update
job = session.get('Job', job_id)
job['status'] = 'done'
job['data'] = json.dumps({
    'description': 'Test completed',
    'requested_by': user_a_id
})
session.commit()

print("✅ Job update succeeded!")
print(f"Final status: {job['status']}")
```

**Expected Output**:
```
Session user: user_b
Job created: <job-id>
Job owner: user_b
✅ Job update succeeded!
Final status: done
```

---

## Documentation Updates

After implementing fixes:

1. Update `ARCHITECTURE.md` - Document Job ownership model
2. Update `README.md` - Clarify multi-user workflow support
3. Update `AGENTS.md` - Fix Job entity description
4. Add `TROUBLESHOOTING.md` - Common Job-related issues

---

## Summary

**Files Modified**: `source/ftrack_user_location/sync.py`

**Functions Changed**:
- `on_sync_to_destination()` (lines 11-170)
- `on_sync_to_remote()` (lines 159-390)

**Key Changes**:
1. Session user ownership for Jobs
2. Store job_id after creation
3. Use `session.get('Job', job_id)` before updates
4. Batch commits (2 total instead of 200+)
5. Track requesting user in Job.data

**Testing Required**:
- Unit tests for Job creation/updates
- Integration tests for multi-user scenarios
- Performance test with 100+ components

**Expected Results**:
- ✅ No permission errors in multi-user workflows
- ✅ No "must be committed first" errors
- ✅ 100-component sync in <2 minutes (vs 5-10 minutes)
- ✅ All multi-user use cases functional

---

**Estimated Implementation Time**: 2-3 hours  
**Estimated Testing Time**: 2-3 hours  
**Total**: 4-6 hours
