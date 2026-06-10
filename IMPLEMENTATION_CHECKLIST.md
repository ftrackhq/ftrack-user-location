# Implementation Checklist: Critical Bug Fixes

**Date**: 2026-06-10  
**Target**: Phase 0 - Critical Bug Fixes  
**Time Estimate**: 4-6 hours

---

## Pre-Implementation

- [ ] Read `IMPLEMENTATION_GUIDE.md` completely
- [ ] Read `JOB_LIFECYCLE_FIX.md` for pattern understanding
- [ ] Review official ftrack pattern in AdvancedBaseAction source
- [ ] Backup current `sync.py` file
- [ ] Create feature branch: `git checkout -b fix/job-permission-lifecycle`

---

## Code Changes

### File: `source/ftrack_user_location/sync.py`

#### Function 1: `on_sync_to_destination()` (Lines 11-170)

- [ ] **Line 11**: Change parameter name `user_id` → `requesting_user_id`
- [ ] **After line 40**: Add session user query
  ```python
  session_user = session.query(
      'User where username is "{}"'.format(session.api_user)
  ).first()
  ```
- [ ] **Line 44-52**: Update Job creation
  - [ ] Change `'user': session.get('User', user_id)` → `'user': session_user`
  - [ ] Add `'requested_by': requesting_user_id` to Job.data
- [ ] **After line 54**: Add `job_id = job['id']`
- [ ] **Lines 56-68**: Update sanity check failure handling
  - [ ] Add `job = session.get('Job', job_id)` before updating
  - [ ] Add `'requested_by': requesting_user_id` to Job.data
- [ ] **After line 69**: Add tracking lists
  ```python
  components_synced = []
  components_failed = []
  ```
- [ ] **Lines 86-97**: Update component unavailability handling
  - [ ] Remove `job['status'] = 'failed'` and commit
  - [ ] Add to `components_failed` list instead
- [ ] **Lines 98-158**: Update component processing
  - [ ] Remove all intermediate `job['data']` updates
  - [ ] Remove all intermediate `session.commit()` calls
  - [ ] Track results in `components_synced` and `components_failed`
- [ ] **After line 158**: Add batch commit
  ```python
  session.commit()
  ```
- [ ] **After batch commit**: Add final Job update
  ```python
  job = session.get('Job', job_id)
  if components_failed:
      job['status'] = 'failed'
      job['data'] = json.dumps({...})
  else:
      job['status'] = 'done'
      job['data'] = json.dumps({...})
  session.commit()
  ```

#### Function 2: `on_sync_to_remote()` (Lines 159-390)

- [ ] **Line 159**: Change parameter name `user_id` → `requesting_user_id`
- [ ] Apply same pattern as `on_sync_to_destination()`
  - [ ] Add session user query
  - [ ] Update Job creation
  - [ ] Store job_id
  - [ ] Add tracking lists
  - [ ] Batch commits
  - [ ] Re-query before updates

---

## Testing

### Unit Tests

- [ ] Session user query returns correct user
- [ ] Job created with session user as owner
- [ ] Job ID extracted correctly
- [ ] `session.get('Job', job_id)` works
- [ ] Job updates succeed without errors
- [ ] Multiple Job updates work
- [ ] Requesting user in Job.data

### Single-User Test

- [ ] User A triggers sync on their own machine
- [ ] Job owned by User A
- [ ] Sync completes successfully
- [ ] Job status = 'done'
- [ ] No permission errors

### Multi-User Test (CRITICAL)

Setup: Two machines, two different ftrack users logged in

**Test 1**: User A → User B's machine
- [ ] User A triggers sync action in ftrack UI
- [ ] Event received by User B's machine
- [ ] No permission errors during Job creation
- [ ] Job owned by User B (executor)
- [ ] Job.data contains `requested_by: user_a_id`
- [ ] Sync completes successfully
- [ ] No "must be committed first" errors
- [ ] Job visible in ftrack UI

**Test 2**: User B → User A's machine
- [ ] User B triggers sync action in ftrack UI
- [ ] Event received by User A's machine
- [ ] No permission errors
- [ ] Job owned by User A (executor)
- [ ] Job.data contains `requested_by: user_b_id`
- [ ] Sync completes successfully

### Performance Test

- [ ] Create asset version with 100 components
- [ ] Trigger sync
- [ ] Time the operation
- [ ] Verify completes in <2 minutes
- [ ] Check session commit count (should be 2, not 200+)
- [ ] Memory usage stable
- [ ] No timeout errors

### Failure Scenarios

- [ ] Component not available in source
  - [ ] Tracked in `components_failed`
  - [ ] Job status = 'failed'
  - [ ] Job.data shows failed component list
  
- [ ] Location not accessible
  - [ ] Job status = 'failed'
  - [ ] Clear error message
  
- [ ] Exception during sync
  - [ ] Job status = 'failed'
  - [ ] Job.data contains error description

---

## Validation Script

Run this to verify the fix:

```python
# File: test_job_fix.py
import ftrack_api
import json

def test_job_pattern():
    '''Test the Job ownership and lifecycle pattern.'''
    
    # Connect as User B
    session = ftrack_api.Session(
        api_user='user_b',
        api_key='<user_b_key>'
    )
    
    # Simulate User A requesting
    user_a_id = '<user_a_id>'
    
    # Get session user (executor)
    session_user = session.query(
        'User where username is "{}"'.format(session.api_user)
    ).first()
    
    print(f"✓ Session user: {session_user['username']}")
    
    # Create Job owned by executor
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
    print(f"✓ Job created: {job_id}")
    print(f"✓ Job owner: {job['user']['username']}")
    
    # Re-query before update
    job = session.get('Job', job_id)
    job['status'] = 'done'
    job['data'] = json.dumps({
        'description': 'Test completed',
        'requested_by': user_a_id
    })
    session.commit()
    
    print(f"✓ Job updated successfully!")
    print(f"✓ Final status: {job['status']}")
    
    # Verify data
    job_data = json.loads(job['data'])
    assert job_data['requested_by'] == user_a_id
    print(f"✓ Requesting user tracked correctly")
    
    print("\n✅ ALL TESTS PASSED!")

if __name__ == '__main__':
    test_job_pattern()
```

Expected output:
```
✓ Session user: user_b
✓ Job created: <job-id>
✓ Job owner: user_b
✓ Job updated successfully!
✓ Final status: done
✓ Requesting user tracked correctly

✅ ALL TESTS PASSED!
```

---

## Documentation Updates

- [ ] Update `ARCHITECTURE.md` - Document Job ownership model
- [ ] Update `README.md` - Clarify multi-user support
- [ ] Fix `AGENTS.md` - Correct environment variable typo
- [ ] Update `CHANGELOG.md` - Add entry for bug fixes

---

## Git Workflow

- [ ] Commit changes with descriptive message:
  ```
  fix: Job permission and lifecycle management
  
  - Jobs now owned by executor (session user), not requester
  - Use session.get('Job', job_id) to re-query before updates
  - Batch component commits for performance
  - Track requesting user in Job.data metadata
  
  Fixes multi-user permission errors and "must be committed first" errors.
  Based on official ftrack-action-handler AdvancedBaseAction pattern.
  
  Performance: 100 components now complete in <2 minutes (vs 5-10 minutes)
  ```
- [ ] Push to remote: `git push origin fix/job-permission-lifecycle`
- [ ] Create pull request with detailed description
- [ ] Link to implementation guide and fix documentation

---

## Post-Implementation

- [ ] Deploy to test environment
- [ ] Run full test suite
- [ ] Test with pilot users (3-5 users, 1 week)
- [ ] Monitor for issues
- [ ] Collect feedback
- [ ] Update documentation based on findings

---

## Rollback Plan (If Needed)

- [ ] Document the issue discovered
- [ ] Revert commit: `git revert <commit-hash>`
- [ ] Push revert: `git push origin fix/job-permission-lifecycle`
- [ ] Investigate root cause
- [ ] Update fix and re-deploy

---

## Success Criteria

**All must pass before considering complete:**

- ✅ No permission errors in multi-user workflows
- ✅ No "must be committed first" errors
- ✅ 100-component sync in <2 minutes
- ✅ Job owned by executor
- ✅ Requesting user tracked in Job.data
- ✅ Failed components tracked correctly
- ✅ All tests pass
- ✅ Documentation updated
- ✅ Code reviewed

---

## Time Tracking

- **Code Changes**: _____ hours
- **Testing**: _____ hours
- **Documentation**: _____ hours
- **Total**: _____ hours

**Target**: 4-6 hours total

---

## Notes

Add any observations, issues, or deviations from the plan here:

---

## Sign-Off

- [ ] Code changes complete
- [ ] All tests passing
- [ ] Documentation updated
- [ ] Ready for code review
- [ ] Approved by: _______________
- [ ] Deployed to production: _______________
