# CRITICAL: Cross-User Job Permission Errors

**Date**: 2026-06-10  
**Severity**: CRITICAL - BLOCKS ALL MULTI-USER WORKFLOWS  
**Status**: IDENTIFIED - REQUIRES IMMEDIATE FIX

---

## The Problem

**Your plugin cannot work in multi-user scenarios due to ftrack permission violations.**

### Current Broken Flow

1. **User A** (Alice on Machine A) triggers sync action in ftrack UI
2. Event published with `source={'user': alice_id}`
3. **User B** (Bob on Machine B) receives event via event hub
4. Bob's session creates Job: `'user': session.get('User', alice_id)`
5. Bob's session tries to update: `job['status'] = 'done'`
6. **ftrack rejects**: "User B cannot modify User A's Job" → **PERMISSION DENIED**

### Why This Fails

**ftrack Permission Model:**
- All API operations are authenticated as the **session user**
- When you assign `Job.user = Alice`, ftrack treats it as "Alice's Job"
- Bob's session **cannot update Alice's Job** (unless Bob is admin)
- On `session.commit()`, ftrack validates permissions and **rejects the update**

---

## The Fix

**Job must be owned by the executor (session user), not the requester.**

### Solution: Executor Ownership Pattern

```python
# ❌ WRONG (current code)
def on_sync_to_destination(session, source_id, destination_id, components, user_id):
    job = session.create('Job', {
        'user': session.get('User', user_id),  # Points to User A (requester)
        'status': 'running'
    })
    session.commit()
    
    # Later...
    job['status'] = 'done'  # ❌ User B's session updating User A's Job = ERROR
    session.commit()
```

```python
# ✅ CORRECT (fixed code)
def on_sync_to_destination(session, source_id, destination_id, components, requesting_user_id):
    '''Sync components from source to destination.
    
    Job owned by session user (executor), with requester tracked in metadata.
    '''
    
    # Get session user (the executor - User B)
    session_user = session.query(
        'User where username is "{}"'.format(session.api_user)
    ).first()
    
    # Get requesting user for metadata
    requesting_user = session.get('User', requesting_user_id)
    
    # Get locations
    source_location = session.get('Location', source_id)
    destination_location = session.get('Location', destination_id)
    
    # Create Job owned by executor
    job = session.create('Job', {
        'user': session_user,  # ✅ Owned by User B (executor)
        'status': 'running',
        'data': json.dumps({
            'description': 'Sync from {} to {}'.format(
                source_location['name'],
                destination_location['name']
            ),
            'requested_by_user_id': requesting_user_id,
            'requested_by_username': requesting_user['username'],
            'operation': 'component_sync',
            'source_location': source_location['name'],
            'destination_location': destination_location['name']
        })
    })
    session.commit()
    
    try:
        # Perform sync operations...
        components_synced = []
        components_failed = []
        
        for component in components:
            try:
                # ... sync logic ...
                components_synced.append(component['name'])
            except Exception as e:
                components_failed.append({'name': component['name'], 'error': str(e)})
        
        # Update Job status
        if components_failed:
            job['status'] = 'failed'
            job['data'] = json.dumps({
                'description': '{} failed, {} succeeded'.format(
                    len(components_failed),
                    len(components_synced)
                ),
                'requested_by_user_id': requesting_user_id,
                'components_synced': components_synced,
                'components_failed': components_failed
            })
        else:
            job['status'] = 'done'
            job['data'] = json.dumps({
                'description': 'Sync completed successfully',
                'requested_by_user_id': requesting_user_id,
                'components_synced': components_synced
            })
        
        session.commit()  # ✅ Works - executor updates their own Job
        
    except Exception as error:
        logger.error(traceback.format_exc())
        job['status'] = 'failed'
        job['data'] = json.dumps({
            'description': 'Sync failed: {}'.format(str(error)),
            'requested_by_user_id': requesting_user_id
        })
        session.commit()
```

---

## Benefits of Executor Ownership

✅ **No permission conflicts** - Session user creates and updates their own Jobs  
✅ **Audit trail** - Shows who actually performed the work (important for troubleshooting)  
✅ **Requester tracked** - `Job.data['requested_by_user_id']` preserves who initiated the sync  
✅ **UI filtering** - Can filter Jobs by `requested_by_user_id` to show "my requests"  
✅ **Works offline** - Executor can complete work even if requester disconnects  

---

## Alternative Solutions

### Option A: API User / Service Account (Enterprise Pattern)

Create a dedicated **system user** for all background operations:

**Setup:**
1. Create user in ftrack UI: `api_sync_service`
2. Assign appropriate role (needs Job create/update permissions)
3. Generate API key for this user
4. Store in environment: `FTRACK_SYNC_API_KEY`

**Implementation:**
```python
# Dedicated API session for background work
api_session = ftrack_api.Session(
    server_url=os.getenv('FTRACK_SERVER'),
    api_key=os.getenv('FTRACK_SYNC_API_KEY'),
    api_user='api_sync_service'
)

api_user = api_session.query('User where username is "api_sync_service"').first()

job = api_session.create('Job', {
    'user': api_user,  # ✅ Owned by service account
    'status': 'running',
    'data': json.dumps({
        'description': 'Syncing...',
        'requested_by': requesting_user_id,
        'executed_by': session.api_user  # Track executor separately
    })
})
api_session.commit()

# ... perform work ...

job['status'] = 'done'
api_session.commit()  # ✅ Service account updates its own Jobs
```

**Benefits:**
- ✅ Clean separation of user vs. system operations
- ✅ Consistent ownership regardless of executor
- ✅ Admin can query all background Jobs by service account
- ✅ No cross-user permission issues

**Trade-offs:**
- ⚠️ Requires additional ftrack user license
- ⚠️ Requires API key management
- ⚠️ More complex setup

### Option B: Event Relay Pattern (Preserve Original Context)

Relay execution back to requesting user's machine:

**Flow:**
1. User A triggers action → publishes `ftrack.sync.request` event
2. User B's machine receives request → publishes `ftrack.sync.execute` event **targeted at User A**
3. User A's machine receives execute event → creates Job owned by User A → performs sync

**Implementation:**
```python
# User B's machine: Receive sync request
def on_sync_request(event):
    requesting_user_id = event['source']['user']['id']
    
    # Relay execution back to requesting user's machine
    session.event_hub.publish(
        ftrack_api.event.base.Event(
            topic='ftrack.sync.execute',
            data={
                'source': source_id,
                'destination': destination_id,
                'components': components
            },
            target='applicationId=ftrack-connect and user.id="{}"'.format(requesting_user_id)
        )
    )

# User A's machine: Execute on their own machine
def on_sync_execute(event):
    session_user = session.query('User where username is "{}"'.format(session.api_user)).first()
    
    job = session.create('Job', {
        'user': session_user,  # ✅ User A owns their own Job
        'status': 'running'
    })
    session.commit()
    
    # Perform sync on User A's machine
    # ...
    
    job['status'] = 'done'
    session.commit()  # ✅ Works - same user
```

**Trade-offs:**
- ✅ Job owned by requesting user (clean UI)
- ❌ Requires requesting user's machine to be online during sync
- ❌ Doesn't work for offline/disconnected users
- ❌ More complex event choreography

---

## Recommended Implementation

**Use Solution 1: Executor Ownership** (simplest, most robust)

### Files to Modify

1. **`source/ftrack_user_location/sync.py`**
   - Lines 11-52: `on_sync_to_destination()` function
   - Lines 159-227: `on_sync_to_remote()` function
   - Change Job creation to use session user

2. **`resource/hook/sync_action.py`**
   - No changes required (already passes `user_id` correctly)
   - UI can optionally filter Jobs by `requested_by_user_id` from Job.data

### Testing Checklist

- [ ] User A triggers sync on their own machine → Job owned by User A → works
- [ ] User A triggers sync on User B's machine → Job owned by User B → no permission errors
- [ ] Job visible in ftrack UI with correct owner
- [ ] Job.data contains `requested_by_user_id` = User A's ID
- [ ] Job updates (`status`, `data`) succeed without permission errors
- [ ] Multi-component sync completes successfully
- [ ] Failed components tracked correctly in Job.data

---

## Impact Assessment

### Who Is Affected

**Currently Broken:**
- ❌ User A → User B's machine (cross-user sync)
- ❌ User A → ftrack.server via User B's machine
- ❌ Any remote collaboration workflow

**Currently Works:**
- ✅ User A → User A's machine (same-user sync)
- ✅ User A → ftrack.server via User A's machine

### Priority

**CRITICAL - FIX IMMEDIATELY**

This bug **blocks the primary use case** of the plugin:
- Remote users cannot collaborate
- Cross-machine transfers fail
- Plugin only works in single-user scenarios

---

## Implementation Steps

1. **Modify `sync.py:on_sync_to_destination()`**
   - Add session user query
   - Change Job creation to use session user
   - Add `requested_by_user_id` to Job.data

2. **Modify `sync.py:on_sync_to_remote()`**
   - Same changes as above

3. **Test multi-user scenario**
   - Set up two machines with different ftrack users
   - User A triggers sync on User B's machine
   - Verify no permission errors
   - Verify Job ownership correct

4. **Update documentation**
   - Document Job ownership model
   - Update ARCHITECTURE.md
   - Add troubleshooting section

5. **Add to CHANGELOG**
   - Breaking change: Job ownership changed
   - Migration note: Existing Jobs unaffected (already created)

---

## Verification

After fix is applied, verify:

```python
# Test script
import ftrack_api

# User B's session (executor)
session_b = ftrack_api.Session(
    api_user='user_b',
    api_key='<user_b_key>'
)

# Simulate User A requesting sync
user_a_id = '<user_a_id>'

# Create Job (as User B would)
session_b_user = session_b.query('User where username is "user_b"').first()

job = session_b.create('Job', {
    'user': session_b_user,  # Owned by User B
    'status': 'running',
    'data': json.dumps({
        'description': 'Test sync',
        'requested_by': user_a_id  # Track User A
    })
})
session_b.commit()

print(f"Job created: {job['id']}")
print(f"Job owner: {job['user']['username']}")  # Should be 'user_b'

# Update Job (should succeed)
job['status'] = 'done'
session_b.commit()

print(f"Job updated successfully!")
```

Expected output:
```
Job created: <job-id>
Job owner: user_b
Job updated successfully!
```

---

## Summary

**Critical Issues Identified:**

### Issue #1: Cross-User Permission Errors
- Jobs assigned to requesting user but updated by executor's session
- ftrack rejects cross-user Job updates due to permission model
- **All multi-user workflows broken**

**Fix:**
- Job owned by executor (session user)
- Requester tracked in Job.data metadata

### Issue #2: Job Entity Lifecycle Error
- "job has to be committed first" error when updating Job after creation
- Created Job entities need `session.refresh(job)` after commit before updates
- Session state mismatch causes stale entity references

**Fix:**
```python
job = session.create('Job', {...})
session.commit()
session.refresh(job)  # ✅ Critical: refresh after commit

# Now updates work
job['status'] = 'done'
session.commit()
```

**Action Required:**
1. Implement executor ownership pattern in `sync.py`
2. Store `job_id` after Job creation
3. Use `session.get('Job', job_id)` to re-query before updates (official ftrack pattern)
4. Batch component commits (not per-component)
5. Test multi-user scenario thoroughly
6. Update documentation

**Official Pattern Reference:**
- `ftrack-action-handler` AdvancedBaseAction class
- Source: `C:\Python312\Lib\site-packages\ftrack_action_handler\action\advanced.py`
- Methods: `create_job()` (line 337), `mark_job_as_done()` (line 372)
- Documentation: https://ftrack-action-handler.readthedocs.io/en/latest/

**Estimated Effort:** 4-6 hours (including testing)

---

**These are the #1 and #2 blocking issues before production deployment.**
