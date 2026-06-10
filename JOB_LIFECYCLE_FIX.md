# Job Lifecycle Management: Official ftrack Pattern

**Date**: 2026-06-10  
**Issue**: "job has to be committed first" error when updating Job entities  
**Solution**: Use `session.get()` to re-query Jobs before updates

---

## The Problem

When you create a Job and commit it, then later try to update its properties, you get:

```
Error: job has to be committed first
```

**Your Current Code:**
```python
# Create Job
job = session.create('Job', {
    'user': user,
    'status': 'running',
    'data': json.dumps({'description': 'Starting...'})
})
session.commit()

# Later in same function...
job['status'] = 'done'  # ❌ ERROR: "job has to be committed first"
session.commit()
```

---

## Why This Happens

After `session.commit()`:
1. The local `job` variable is a **stale entity reference**
2. ftrack session tracks entity states (new, modified, committed)
3. Updating a stale reference triggers the error
4. Session may have cleared its cache or the entity was modified elsewhere

---

## The Official ftrack Solution

From `ftrack-action-handler` AdvancedBaseAction class:

### Pattern: Store ID + Re-Query

**Source**: `ftrack-action-handler/action/advanced.py` (lines 337-379)

```python
class AdvancedBaseAction(BaseAction):
    
    def create_job(self, event, description):
        '''Create a new job.'''
        user_id = event['source']['user']['id']
        job = self.session.create(
            'Job',
            {
                'user': self.session.get('User', user_id),
                'status': 'running',
                'data': json.dumps({'description': u'{}'.format(description)}),
            },
        )
        self.session.commit()
        job_id = job.get('id')  # ✅ Store the ID after commit
        self.job_id = job_id
        return self.job_id
    
    def mark_job_as_done(self, job_id, description):
        '''Mark a job as done.'''
        job = self.session.get('Job', job_id)  # ✅ RE-QUERY using session.get()
        job['data'] = json.dumps({'description': u'{}'.format(description)})
        job['status'] = 'done'
        self.session.commit()
    
    def mark_job_as_failed(self, job_id, error_message):
        '''Mark a job as failed.'''
        job = self.session.get('Job', job_id)  # ✅ RE-QUERY before update
        job['data'] = json.dumps({'description': u'{}'.format(error_message)})
        job['status'] = 'failed'
        self.session.commit()
```

---

## The Pattern

**Step 1**: Create Job and commit
**Step 2**: Store the `job_id`
**Step 3**: Re-query using `session.get('Job', job_id)` before any updates

```python
# ✅ CORRECT PATTERN

# Step 1: Create and commit
job = session.create('Job', {
    'user': user,
    'status': 'running',
    'data': json.dumps({'description': 'Starting...'})
})
session.commit()

# Step 2: Store ID
job_id = job['id']

# ... do work ...

# Step 3: Re-query before updating
job = session.get('Job', job_id)
job['status'] = 'done'
job['data'] = json.dumps({'description': 'Completed'})
session.commit()  # ✅ Works!
```

---

## Why `session.get()` Works

`session.get()` fetches the entity fresh from the server (or session cache):
- Returns entity with current server state
- Properly tracked by session
- Updates work without "must be committed first" error

**Alternative** (also works):
```python
session.refresh(job)  # Refresh existing entity reference
```

But `session.get()` is the official ftrack-action-handler pattern.

---

## Applied to Your Sync Functions

### Fix for `on_sync_to_destination()`

```python
def on_sync_to_destination(session, source_id, destination_id, components, requesting_user_id):
    '''Sync components from source to destination.'''
    
    # Get session user (executor)
    session_user = session.query(
        'User where username is "{}"'.format(session.api_user)
    ).first()
    
    # Get locations
    source_location = session.get('Location', source_id)
    destination_location = session.get('Location', destination_id)
    
    # ✅ Create Job
    job = session.create('Job', {
        'user': session_user,
        'status': 'running',
        'data': json.dumps({
            'description': 'Sync from {} to {}'.format(
                source_location['name'],
                destination_location['name']
            ),
            'requested_by': requesting_user_id
        })
    })
    session.commit()
    
    # ✅ Store job ID
    job_id = job['id']
    
    # Sanity checks
    if not all([source_location.accessor, destination_location.accessor]):
        # ✅ Re-query before updating
        job = session.get('Job', job_id)
        job['data'] = json.dumps({
            'description': 'Locations not accessible: {}, {}'.format(
                destination_location['name'],
                source_location['name']
            )
        })
        job['status'] = 'failed'
        session.commit()
        return
    
    # Track results
    components_synced = []
    components_failed = []
    
    try:
        # Process components
        for component in components:
            component_name = component['name']
            
            # Skip ftrackreview
            if 'ftrackreview' in component_name:
                continue
            
            try:
                # Check availability
                source_available = source_location.get_component_availability(component)
                
                if source_available == 0.0:
                    components_failed.append({
                        'name': component_name,
                        'error': 'Not available in source'
                    })
                    continue
                
                # Sync component
                destination_location.add_component(component, source_location)
                components_synced.append(component_name)
                
            except ftrack_api.exception.ComponentInLocationError:
                logger.warning(f'Component {component_name} already in destination')
                components_synced.append(component_name)
            except Exception as e:
                logger.error(f'Failed to sync {component_name}: {e}')
                components_failed.append({
                    'name': component_name,
                    'error': str(e)
                })
        
        # ✅ Batch commit all component operations
        session.commit()
        
        # ✅ Re-query Job before final update
        job = session.get('Job', job_id)
        
        # Update Job with results
        if components_failed:
            job['status'] = 'failed'
            job['data'] = json.dumps({
                'description': '{} failed, {} succeeded'.format(
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
                'description': 'Sync completed successfully',
                'requested_by': requesting_user_id,
                'components_synced': components_synced
            })
        
        session.commit()
        
    except Exception as error:
        logger.error(traceback.format_exc())
        
        # ✅ Re-query on error too
        job = session.get('Job', job_id)
        job['status'] = 'failed'
        job['data'] = json.dumps({
            'description': 'Sync failed: {}'.format(str(error)),
            'requested_by': requesting_user_id
        })
        session.commit()
        raise
```

---

## Fix for `on_sync_to_remote()`

Same pattern applies:

```python
def on_sync_to_remote(session, source_id, destination_id, requesting_user_id, selection):
    '''Sync from source to remote destination.'''
    
    # Get session user
    session_user = session.query(
        'User where username is "{}"'.format(session.api_user)
    ).first()
    
    # ... get locations ...
    
    # ✅ Create Job
    job = session.create('Job', {
        'user': session_user,
        'status': 'running',
        'data': json.dumps({
            'description': 'Sync from {} to {}'.format(
                source_name,
                sync_name
            )
        })
    })
    session.commit()
    
    # ✅ Store job ID
    job_id = job['id']
    
    # ... process components ...
    
    # ✅ Re-query before final update
    job = session.get('Job', job_id)
    job['status'] = 'done'
    job['data'] = json.dumps({'description': 'Completed'})
    session.commit()
```

---

## Key Takeaways

1. **Always store `job_id`** after creating and committing a Job
2. **Always use `session.get('Job', job_id)`** before updating Job properties
3. **This pattern applies to ALL entity updates** after commit (not just Jobs)
4. **Official ftrack pattern**: Used in `ftrack-action-handler` AdvancedBaseAction
5. **Batch commits**: Commit components in bulk, then update Job once at end

---

## Testing Checklist

- [ ] Job creation succeeds
- [ ] `job_id` stored correctly
- [ ] Multiple Job updates work without "must be committed first" errors
- [ ] Job status transitions: running → done/failed
- [ ] Job.data updates persist correctly
- [ ] Error handling re-queries Job before marking as failed

---

## References

- **ftrack-action-handler Documentation**: https://ftrack-action-handler.readthedocs.io/en/latest/api_reference/index.html
- **AdvancedBaseAction Source**: `ftrack-action-handler/action/advanced.py` (lines 337-379)
- **Package Location**: `C:\Python312\Lib\site-packages\ftrack_action_handler\action\advanced.py`
- **Installed Version**: ftrack-action-handler 0.3.1

---

## Summary

**The Issue**: Stale entity references after commit cause "must be committed first" errors

**The Solution**: Use `session.get('Job', job_id)` to re-query before updates

**The Pattern**:
```python
job = session.create('Job', {...})
session.commit()
job_id = job['id']  # Store ID

# Later...
job = session.get('Job', job_id)  # Re-query
job['status'] = 'done'  # Update
session.commit()  # Works!
```

This is the **official ftrack pattern** used throughout ftrack-action-handler.
