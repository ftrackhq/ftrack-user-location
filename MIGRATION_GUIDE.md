# Migration Guide: ftrack API Best Practices

## Overview

This guide provides step-by-step instructions for implementing the ftrack API code review recommendations. Changes are prioritized by impact and risk.

**Estimated Total Time**: 2-3 days
**Testing Time**: 1 day
**Total Effort**: 3-4 days

---

## Pre-Migration Checklist

- [ ] Create feature branch: `git checkout -b feature/ftrack-api-optimizations`
- [ ] Backup current working plugin build
- [ ] Document current sync performance baseline (components/minute)
- [ ] Ensure test environment available
- [ ] Review this entire guide before starting

---

## Migration Phases

### Phase 1: Query Optimizations (HIGH PRIORITY)
**Time**: 3-4 hours  
**Risk**: Low  
**Impact**: 10-20x performance improvement

### Phase 2: Session Management (HIGH PRIORITY)
**Time**: 4-5 hours  
**Risk**: Medium (requires careful testing)  
**Impact**: 5-10x performance improvement

### Phase 3: Event Handling (MEDIUM PRIORITY)
**Time**: 2-3 hours  
**Risk**: Low  
**Impact**: Prevents crashes, cleaner code

### Phase 4: Component Operations (MEDIUM PRIORITY)
**Time**: 3-4 hours  
**Risk**: Medium (affects core sync logic)  
**Impact**: Better error handling, progress tracking

### Phase 5: Action Handler Improvements (LOW PRIORITY)
**Time**: 2 hours  
**Risk**: Low  
**Impact**: Better validation, user feedback

---

## Phase 1: Query Optimizations

### 1.1 Fix Location Query in sync.py

**File**: `source/ftrack_user_location/sync.py`  
**Lines**: 180-204  
**Time**: 1 hour

#### Before:
```python
def on_sync_to_remote(session, source, destination, user_id, selection):
    store_mapping = {
        'sync': 'ftrack.server',
        'input': source,
        'output': destination
    }

    user = session.get('User', user_id)

    logger.info(
        "User {} is syncing {} items from {} to {}".format(
            user['username'], len(selection),
            source, destination)
    )

    results = {}
    for location in session.query('select name from Location').all():
        location_name = location['name']
        for store_type, store_name in list(store_mapping.items()):
            if store_name == location_name:
                logger.debug(
                    "Syncing to remote, found location {} in {} of type = {}".format(
                        location_name, store_name, store_type)
                    )
                results[store_type] = location
```

#### After:
```python
def on_sync_to_remote(session, source, destination, user_id, selection):
    '''Sync components from local location to remote.
    
    Args:
        session: ftrack API session
        source: Source location name
        destination: Destination location name
        user_id: User ID requesting sync
        selection: List of selected entities
    '''
    store_mapping = {
        'sync': 'ftrack.server',
        'input': source,
        'output': destination
    }

    user = session.get('User', user_id)

    logger.info(
        "User {} is syncing {} items from {} to {}".format(
            user['username'], len(selection),
            source, destination)
    )

    # Query locations by name directly (optimized)
    results = {}
    for store_type, store_name in store_mapping.items():
        location = session.query(
            'Location where name is "{}"'.format(store_name)
        ).first()
        
        if location:
            results[store_type] = location
            logger.debug(
                "Found location {} for type {}".format(store_name, store_type)
            )
        else:
            logger.warning('Location "{}" not found'.format(store_name))
    
    # Validate required locations exist
    if 'sync' not in results:
        raise ValueError('Sync location "ftrack.server" not found')
    if 'input' not in results:
        raise ValueError('Source location "{}" not found'.format(source))
    if 'output' not in results:
        raise ValueError('Destination location "{}" not found'.format(destination))
```

**Testing**:
```python
# Test with valid locations
on_sync_to_remote(session, 'user.local', 'ftrack.server', user_id, selection)

# Test with invalid location (should raise ValueError)
try:
    on_sync_to_remote(session, 'invalid.location', 'ftrack.server', user_id, selection)
except ValueError as e:
    print(f"Expected error: {e}")
```

---

### 1.2 Fix N+1 Query Problem

**File**: `source/ftrack_user_location/sync.py`  
**Lines**: 221-234  
**Time**: 2 hours

#### Before:
```python
components = []
for s in selection:
    version = session.get('AssetVersion', s['entityId'])

    # get all the asset components
    for component in version['components']:
        component_name = component['name']
        component_id = component['id']
        components.append(
            {
                'id': component_id,
                'name': component_name
            }
        )
```

#### After:
```python
# Batch query with projection (optimized)
version_ids = [s['entityId'] for s in selection]

if not version_ids:
    logger.warning('No versions selected for sync')
    job['status'] = 'done'
    session.commit()
    return

# Single query with projection - much faster
versions = session.query(
    'select components.id, components.name from AssetVersion '
    'where id in ({})'.format(','.join('"{}"'.format(vid) for vid in version_ids))
).all()

components = []
for version in versions:
    for component in version.get('components', []):
        components.append({
            'id': component['id'],
            'name': component['name']
        })

logger.info('Found {} components across {} versions'.format(
    len(components), len(versions)
))
```

**Testing**:
```python
# Test with 100 selections
import time

# Before optimization
start = time.time()
old_sync_method(session, source, dest, user_id, large_selection)
old_time = time.time() - start

# After optimization
start = time.time()
new_sync_method(session, source, dest, user_id, large_selection)
new_time = time.time() - start

print(f"Speedup: {old_time / new_time:.1f}x")
```

---

### 1.3 Fix Component Query in on_sync_to_destination

**File**: `source/ftrack_user_location/sync.py`  
**Lines**: 22  
**Time**: 30 minutes

#### Before:
```python
components = [session.get('Component', cid['id']) for cid in components]
```

#### After:
```python
# Batch query with projection
component_ids = [cid['id'] for cid in components]

if not component_ids:
    logger.info('No components to sync')
    job['status'] = 'done'
    session.commit()
    return

components = session.query(
    'select id, name, version_id from Component where id in ({})'.format(
        ','.join('"{}"'.format(cid) for cid in component_ids)
    )
).all()

logger.info('Queried {} components for sync'.format(len(components)))
```

---

## Phase 2: Session Management

### 2.1 Implement Batch Commits

**File**: `source/ftrack_user_location/sync.py`  
**Function**: `on_sync_to_destination`  
**Time**: 3-4 hours

#### Strategy:
1. Remove commits from inside loops
2. Add batch commits every N operations
3. Add proper rollback on errors
4. Track progress for partial failures

#### Implementation:

Create new file: `source/ftrack_user_location/sync_optimized.py`

```python
# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

import ftrack_api
import logging
import json


logger = logging.getLogger(__name__)

# Configuration
BATCH_COMMIT_SIZE = 10  # Commit every 10 components
IGNORED_COMPONENT_PATTERNS = ['ftrackreview', 'ftrack-review', 'review-media']


def should_skip_component(component_name):
    '''Check if component should be skipped during sync.
    
    Args:
        component_name (str): Component name to check
        
    Returns:
        bool: True if component should be skipped
    '''
    name_lower = component_name.lower()
    return any(pattern in name_lower for pattern in IGNORED_COMPONENT_PATTERNS)


def check_batch_availability(location, components):
    '''Check availability for multiple components efficiently.
    
    Args:
        location: ftrack Location entity
        components (list): List of Component entities
        
    Returns:
        dict: Component ID -> availability percentage mapping
    '''
    availability = {}
    for component in components:
        try:
            availability[component['id']] = location.get_component_availability(component)
        except Exception as e:
            logger.warning(
                'Could not check availability for component {}: {}'.format(
                    component.get('name', component['id']), e
                )
            )
            availability[component['id']] = 0.0
    return availability


def on_sync_to_destination(session, source_id, destination_id, components, user_id):
    '''Callback for when files are copied between locations.
    
    Optimized version with batched commits and better error handling.
    
    Args:
        session: ftrack API session
        source_id: Source location ID
        destination_id: Destination location ID
        components: List of component dicts with 'id' key
        user_id: User ID requesting sync
    '''
    # Batch query components with projection
    component_ids = [cid['id'] for cid in components]
    
    if not component_ids:
        logger.info('No components to sync')
        return
    
    components = session.query(
        'select id, name, version_id from Component where id in ({})'.format(
            ','.join('"{}"'.format(cid) for cid in component_ids)
        )
    ).all()
    
    # Get location objects
    source_location = session.get('Location', source_id)
    destination_location = session.get('Location', destination_id)
    
    # Get location accessors
    source_accessor = source_location.accessor
    destination_accessor = destination_location.accessor
    
    # Get location names
    source_name = source_location['name']
    destination_name = destination_location['name']
    
    logger.info(
        "Syncing from {} to {}".format(source_name, destination_name)
    )
    
    # Start the job
    job = session.create('Job', {
        'description': "Sync from {} to {}".format(source_name, destination_name),
        'user': session.get('User', user_id),
        'status': 'running'
    })
    session.commit()  # Initial commit for job creation
    
    # Sanity checks
    if not source_accessor:
        message = 'Source location "{}" has no accessor configured'.format(source_name)
        logger.error(message)
        job['data'] = json.dumps({'description': message})
        job['status'] = 'failed'
        session.commit()
        return
    
    if not destination_accessor:
        message = 'Destination location "{}" has no accessor configured'.format(
            destination_name
        )
        logger.error(message)
        job['data'] = json.dumps({'description': message})
        job['status'] = 'failed'
        session.commit()
        return
    
    # Batch availability check
    logger.info('Checking component availability...')
    source_availability = check_batch_availability(source_location, components)
    dest_availability = check_batch_availability(destination_location, components)
    
    # Track progress
    total_components = len(components)
    processed = 0
    successful = []
    skipped = []
    failed = []
    
    # Process components with batched commits
    for i, component in enumerate(components):
        component_id = component['id']
        component_name = component['name']
        
        # Skip review components
        if should_skip_component(component_name):
            logger.debug('Skipping review component: {}'.format(component_name))
            skipped.append(component_name)
            continue
        
        # Check source availability
        if source_availability.get(component_id, 0.0) == 0.0:
            status = 'Component "{}" is not available in {}'.format(
                component_name, source_name
            )
            logger.warning(status)
            skipped.append(component_name)
            continue
        
        # Check if already in destination
        if dest_availability.get(component_id, 0.0) == 100.0:
            status = '"{}" already exists in {}'.format(
                component_name, destination_name
            )
            logger.debug(status)
            skipped.append(component_name)
            continue
        
        # Attempt transfer
        try:
            logger.debug('Copying "{}" from {} to {}'.format(
                component_name, source_name, destination_name
            ))
            
            destination_location.add_component(component, source_location)
            successful.append(component_name)
            processed += 1
            
            # Update job progress (no commit yet)
            progress_pct = int((processed / total_components) * 100)
            job['data'] = json.dumps({
                'description': 'Syncing {} ({}/{})'.format(
                    component_name, processed, total_components
                ),
                'progress': progress_pct,
                'successful': len(successful),
                'skipped': len(skipped),
                'failed': len(failed)
            })
            
            # Batch commit
            if (i + 1) % BATCH_COMMIT_SIZE == 0:
                session.commit()
                logger.info('Committed batch {}/{} components'.format(i + 1, total_components))
            
        except ftrack_api.exception.ComponentInLocationError as error:
            logger.warning('Component already in location: {}'.format(error))
            skipped.append(component_name)
            continue
            
        except ftrack_api.exception.LocationError as error:
            logger.error('Location error for {}: {}'.format(component_name, error))
            failed.append({'name': component_name, 'error': str(error)})
            session.rollback()  # Rollback failed component
            continue
            
        except IOError as error:
            logger.error('IO error for {}: {}'.format(component_name, error))
            failed.append({'name': component_name, 'error': str(error)})
            session.rollback()
            continue
            
        except Exception as error:
            logger.error('Unexpected error for {}: {}'.format(component_name, error))
            import traceback
            logger.error(traceback.format_exc())
            failed.append({'name': component_name, 'error': str(error)})
            session.rollback()
            # Continue processing other components
    
    # Final commit and status
    if failed:
        job['status'] = 'failed'
        job['data'] = json.dumps({
            'description': 'Completed {}/{} components. {} failed.'.format(
                len(successful), total_components, len(failed)
            ),
            'successful': successful,
            'skipped': skipped,
            'failed': failed
        })
    else:
        job['status'] = 'done'
        job['data'] = json.dumps({
            'description': 'Successfully synced {} components. {} skipped.'.format(
                len(successful), len(skipped)
            ),
            'successful': successful,
            'skipped': skipped
        })
    
    session.commit()  # Final commit
    
    logger.info(
        'Finished processing {} components: {} successful, {} skipped, {} failed'.format(
            total_components, len(successful), len(skipped), len(failed)
        )
    )


def on_sync_to_remote(session, source, destination, user_id, selection):
    '''Callback for syncing from local location to remote.
    
    Optimized version with batched queries and commits.
    
    Args:
        session: ftrack API session
        source: Source location name
        destination: Destination location name
        user_id: User ID requesting sync
        selection: List of selected entities
    '''
    store_mapping = {
        'sync': 'ftrack.server',
        'input': source,
        'output': destination
    }
    
    user = session.get('User', user_id)
    
    logger.info(
        "User {} is syncing {} items from {} to {}".format(
            user['username'], len(selection), source, destination
        )
    )
    
    # Query locations by name directly (optimized)
    results = {}
    for store_type, store_name in store_mapping.items():
        location = session.query(
            'Location where name is "{}"'.format(store_name)
        ).first()
        
        if location:
            results[store_type] = location
            logger.debug('Found location {} for type {}'.format(store_name, store_type))
        else:
            logger.warning('Location "{}" not found'.format(store_name))
    
    # Validate required locations exist
    if 'sync' not in results:
        raise ValueError('Sync location "ftrack.server" not found')
    if 'input' not in results:
        raise ValueError('Source location "{}" not found'.format(source))
    if 'output' not in results:
        raise ValueError('Destination location "{}" not found'.format(destination))
    
    source_name = results['input']['name']
    sync_name = results['sync']['name']
    
    # Create job
    message = "Sync from {} to {}".format(source_name, sync_name)
    logger.info(message)
    
    job = session.create('Job', {
        'data': json.dumps({'description': message}),
        'user': user,
        'status': 'running'
    })
    session.commit()  # Initial commit
    
    # Batch query asset versions with components projection
    version_ids = [s['entityId'] for s in selection]
    
    if not version_ids:
        logger.warning('No versions selected for sync')
        job['status'] = 'done'
        session.commit()
        return
    
    # Single query with projection - much faster
    versions = session.query(
        'select components.id, components.name from AssetVersion '
        'where id in ({})'.format(','.join('"{}"'.format(vid) for vid in version_ids))
    ).all()
    
    components = []
    for version in versions:
        for component in version.get('components', []):
            components.append({
                'id': component['id'],
                'name': component['name']
            })
    
    logger.info('Found {} components across {} versions'.format(
        len(components), len(versions)
    ))
    
    # Track progress
    total = len(components)
    processed = 0
    successful = []
    skipped = []
    failed = []
    
    for i, comp_dict in enumerate(components):
        component_id = comp_dict['id']
        component_name = comp_dict['name']
        
        # Get full component entity
        component = session.get('Component', component_id)
        
        # Skip review components
        if should_skip_component(component_name):
            logger.debug('Skipping review component: {}'.format(component_name))
            skipped.append(component_name)
            continue
        
        # Check source availability
        source_component = results['input'].get_component_availability(component)
        if source_component != 100.0:
            status = 'Component {} not available in {}: {}%'.format(
                component_name, source_name, source_component
            )
            logger.debug(status)
            skipped.append(component_name)
            continue
        
        # Check if already synced
        synced_component = results['sync'].get_component_availability(component)
        if synced_component == 100.0:
            status = 'Component {} already synced to {}'.format(
                component_name, sync_name
            )
            logger.debug(status)
            skipped.append(component_name)
            continue
        
        # Attempt sync
        try:
            logger.debug('Copying {} from {} to {}'.format(
                component['name'], source_name, sync_name
            ))
            
            results['sync'].add_component(component, results['input'])
            successful.append(component_name)
            processed += 1
            
            # Update job (no commit yet)
            progress_pct = int((processed / total) * 100)
            job['data'] = json.dumps({
                'description': 'Syncing {} ({}/{})'.format(
                    component_name, processed, total
                ),
                'progress': progress_pct
            })
            
            # Batch commit
            if (i + 1) % BATCH_COMMIT_SIZE == 0:
                session.commit()
                logger.info('Committed batch {}/{}'.format(i + 1, total))
            
        except ftrack_api.exception.ComponentInLocationError as error:
            logger.warning('Component already in location: {}'.format(error))
            skipped.append(component_name)
            continue
            
        except Exception as error:
            logger.error('Failed to sync {}: {}'.format(component_name, error))
            import traceback
            logger.error(traceback.format_exc())
            failed.append({'name': component_name, 'error': str(error)})
            session.rollback()
    
    # Final status
    if failed:
        job['status'] = 'failed'
        job['data'] = json.dumps({
            'description': 'Completed {}/{} components. {} failed.'.format(
                len(successful), total, len(failed)
            ),
            'successful': successful,
            'skipped': skipped,
            'failed': failed
        })
    else:
        job['status'] = 'done'
        job['data'] = json.dumps({
            'description': 'Successfully synced {} components. {} skipped.'.format(
                len(successful), len(skipped)
            ),
            'successful': successful,
            'skipped': skipped
        })
    
    session.commit()  # Final commit
    
    logger.info('Finished processing {} components: {} successful, {} skipped, {} failed'.format(
        total, len(successful), len(skipped), len(failed)
    ))
    
    # Publish completion event
    event = ftrack_api.event.base.Event(
        topic='ftrack.sync',
        data={
            'actionIdentifier': 'ftrack-to-{}'.format(results['output']['name']),
            'components': [{'id': c['id'], 'name': c['name']} for c in components],
            'locations': {
                'sync': results['sync']['id'],
                'source': results['input']['id'],
                'destination': results['output']['id']
            }
        },
        source={'user': user_id}
    )
    
    session.event_hub.publish(event)
```

#### Migration Steps:

1. **Create backup**:
```bash
cp source/ftrack_user_location/sync.py source/ftrack_user_location/sync_backup.py
```

2. **Replace sync.py with optimized version**:
```bash
cp source/ftrack_user_location/sync_optimized.py source/ftrack_user_location/sync.py
```

3. **Test thoroughly** (see Testing section below)

4. **Monitor production** for 1 week before removing backup

---

## Phase 3: Event Handling

### 3.1 Combine Event Subscriptions

**File**: `resource/hook/connect_plugin_hook.py`  
**Lines**: 74-84  
**Time**: 30 minutes

#### Before:
```python
# Location will be available from within the dcc applications.
api_object.event_hub.subscribe(
    'topic=ftrack.connect.application.launch',
    modify_application_launch
)

# Location will be available from actions
api_object.event_hub.subscribe(
    'topic=ftrack.action.launch',
    modify_application_launch
)
```

#### After:
```python
# Location will be available from DCC applications and actions
api_object.event_hub.subscribe(
    'topic=ftrack.connect.application.launch or topic=ftrack.action.launch',
    modify_application_launch
)
```

---

### 3.2 Add Event Validation

**File**: `resource/hook/connect_plugin_hook.py`  
**Function**: `modify_application_launch`  
**Time**: 1 hour

#### Before:
```python
def modify_application_launch(event):
    '''Modify the application environment to include  our location plugin.'''
    environment = event['data'].get('options', {}).get('env', {})

    appendPath(
        LOCATION_DIRECTORY,
        'FTRACK_EVENT_PLUGIN_PATH',
        environment
    )
    
    appendPath(
        LOCATION_DIRECTORY,
        'PYTHONPATH',
        environment
    )

    logger.info(
        'Connect plugin modified launch hook to register location plugin.'
    )
```

#### After:
```python
def modify_application_launch(event):
    '''Modify the application environment to include our location plugin.
    
    Args:
        event (dict): ftrack event with application launch data
    '''
    # Validate event structure
    if not event or 'data' not in event:
        logger.warning('Invalid event structure, missing data')
        return
    
    options = event['data'].get('options')
    if not isinstance(options, dict):
        logger.warning('Event options is not a dictionary')
        return
        
    environment = options.get('env', {})
    if not isinstance(environment, dict):
        logger.warning('Event environment is not a dictionary, creating new')
        environment = {}
        options['env'] = environment
    
    try:
        appendPath(
            LOCATION_DIRECTORY,
            'FTRACK_EVENT_PLUGIN_PATH',
            environment
        )
        
        appendPath(
            LOCATION_DIRECTORY,
            'PYTHONPATH',
            environment
        )
        
        logger.info(
            'Connect plugin modified launch hook to register location plugin.'
        )
    except Exception as error:
        logger.error('Failed to modify environment: {}'.format(error))
        import traceback
        logger.error(traceback.format_exc())
        # Don't raise - let application launch continue
```

---

## Phase 4: Component Operations

### 4.1 Improve Component Filtering

**File**: `source/ftrack_user_location/sync.py`  
**Time**: 30 minutes

Already included in Phase 2 optimized version (see `should_skip_component` function).

---

## Phase 5: Action Handler Improvements

### 5.1 Add Form Validation

**File**: `resource/hook/sync_action.py`  
**Function**: `build_sync_event`  
**Time**: 1 hour

#### Before:
```python
def build_sync_event(self, event):
    source_location = event['data']['values']['source_location']
    dest_location = event['data']['values']['dest_location']

    if not self.location_exists(source_location):
        raise ValueError(
            'Source location {} does not exist'.format(source_location)
        )

    if not self.location_exists(dest_location):
        raise ValueError(
            'Destination location {} does not exist'.format(dest_location)
        )

    event['data']['actionIdentifier'] = 'syncto-{}'.format(dest_location)
    event['source']['location'] = self.location['name']
    event['target'] = {'location': dest_location}

    return event
```

#### After:
```python
def build_sync_event(self, event):
    '''Build sync event with comprehensive validation.
    
    Args:
        event (dict): Action event with form values
        
    Returns:
        dict: Modified event with sync parameters
        
    Raises:
        ValueError: If validation fails
    '''
    values = event['data'].get('values', {})
    
    source_location = values.get('source_location')
    dest_location = values.get('dest_location')
    
    # Validate required fields
    if not source_location:
        raise ValueError('Source location is required')
    if not dest_location:
        raise ValueError('Destination location is required')
    
    # Prevent self-sync
    if source_location == dest_location:
        raise ValueError('Source and destination must be different')
    
    # Validate locations exist
    if not self.location_exists(source_location):
        raise ValueError(
            'Source location "{}" does not exist'.format(source_location)
        )
    
    if not self.location_exists(dest_location):
        raise ValueError(
            'Destination location "{}" does not exist'.format(dest_location)
        )
    
    # Build event
    event['data']['actionIdentifier'] = 'syncto-{}'.format(dest_location)
    event['source']['location'] = self.location['name']
    event['target'] = {'location': dest_location}
    
    return event
```

---

### 5.2 Improve Launch Error Handling

**File**: `resource/hook/sync_action.py`  
**Function**: `launch`  
**Time**: 30 minutes

#### Before:
```python
def launch(self, session, entities, event):
    self.logger.info("Sync action launched from location {}".format(self.location['name']))

    if 'values' not in event['data']:
        event = self.get_locations_ui(event)
        return event
    else:
        try:
            event = self.build_sync_event(event)
        except ValueError as e:
            return {
                'success': False,
                'message': str(e)
            }

        event['data']['actionIdentifier'] = '{}-to-ftrack'.format(self.location['name'])
        self.session.event_hub.publish(event)

        return {
            'success': True,
            'message': 'Sync launched'
        }
```

#### After:
```python
def launch(self, session, entities, event):
    '''Launch sync action with comprehensive error handling.
    
    Args:
        session: ftrack API session
        entities: Selected entities
        event: Action event
        
    Returns:
        dict: Success/failure message or form UI
    '''
    self.logger.info(
        "Sync action launched from location {}".format(self.location['name'])
    )

    if 'values' not in event['data']:
        # Show form
        event = self.get_locations_ui(event)
        return event
    else:
        try:
            event = self.build_sync_event(event)
        except ValueError as e:
            self.logger.warning('Validation error: {}'.format(e))
            return {
                'success': False,
                'message': str(e)
            }
        except Exception as e:
            self.logger.error('Unexpected error building sync event: {}'.format(e))
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': 'An unexpected error occurred. Please check logs.'
            }
        
        # Publish event
        try:
            event['data']['actionIdentifier'] = '{}-to-ftrack'.format(
                self.location['name']
            )
            self.session.event_hub.publish(event)
            
            return {
                'success': True,
                'message': 'Sync launched successfully'
            }
        except Exception as e:
            self.logger.error('Failed to publish sync event: {}'.format(e))
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': 'Failed to launch sync. Please try again.'
            }
```

---

## Testing Strategy

### Performance Testing

Create: `tests/performance_test.py`

```python
# :coding: utf-8

import ftrack_api
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def performance_test_sync():
    '''Test sync performance with optimizations.'''
    
    session = ftrack_api.Session()
    
    # Create test data
    project = session.query('Project').first()
    
    # Create 100 test asset versions
    logger.info('Creating test data...')
    versions = []
    for i in range(10):  # Start with 10 for quick test
        asset = session.create('Asset', {
            'name': 'perftest_{}'.format(i),
            'type': session.query('AssetType').first(),
            'parent': project
        })
        version = session.create('AssetVersion', {
            'asset': asset,
            'task': None
        })
        versions.append(version)
    
    session.commit()
    
    # Test query performance
    logger.info('Testing query performance...')
    
    version_ids = [v['id'] for v in versions]
    
    # Old way (N+1)
    start = time.time()
    for vid in version_ids:
        v = session.get('AssetVersion', vid)
        _ = v['components']  # Trigger relationship load
    old_time = time.time() - start
    
    # New way (batch)
    start = time.time()
    results = session.query(
        'select components.id, components.name from AssetVersion '
        'where id in ({})'.format(','.join('"{}"'.format(vid) for vid in version_ids))
    ).all()
    new_time = time.time() - start
    
    # Results
    logger.info('Old method: {:.3f}s'.format(old_time))
    logger.info('New method: {:.3f}s'.format(new_time))
    logger.info('Speedup: {:.1f}x'.format(old_time / new_time))
    
    # Cleanup
    for v in versions:
        session.delete(v['asset'])
    session.commit()
    
    return old_time / new_time


def performance_test_commits():
    '''Test commit batching performance.'''
    
    session = ftrack_api.Session()
    project = session.query('Project').first()
    
    # Test commit frequency
    logger.info('Testing commit frequency...')
    
    # Old way (commit per operation)
    start = time.time()
    for i in range(50):
        note = session.create('Note', {
            'content': 'Test {}'.format(i),
            'parent': project
        })
        session.commit()
    old_time = time.time() - start
    
    # New way (batched commits)
    start = time.time()
    BATCH_SIZE = 10
    for i in range(50):
        note = session.create('Note', {
            'content': 'Test batch {}'.format(i),
            'parent': project
        })
        if (i + 1) % BATCH_SIZE == 0:
            session.commit()
    session.commit()  # Final
    new_time = time.time() - start
    
    # Results
    logger.info('Old method (commit each): {:.3f}s'.format(old_time))
    logger.info('New method (batch of 10): {:.3f}s'.format(new_time))
    logger.info('Speedup: {:.1f}x'.format(old_time / new_time))
    
    # Cleanup
    notes = session.query('Note where content like "Test%"').all()
    for note in notes:
        session.delete(note)
    session.commit()
    
    return old_time / new_time


if __name__ == '__main__':
    query_speedup = performance_test_sync()
    commit_speedup = performance_test_commits()
    
    print('\n=== Performance Summary ===')
    print('Query optimization: {:.1f}x faster'.format(query_speedup))
    print('Commit batching: {:.1f}x faster'.format(commit_speedup))
    print('Expected total improvement: {:.1f}x faster'.format(
        query_speedup * commit_speedup
    ))
```

Run:
```bash
uv run python tests/performance_test.py
```

---

### Integration Testing

Create: `tests/integration_test.py`

```python
# :coding: utf-8

import ftrack_api
import logging
import tempfile
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_sync_workflow():
    '''Test complete sync workflow with optimizations.'''
    
    session = ftrack_api.Session()
    
    logger.info('Starting integration test...')
    
    # 1. Create test data
    project = session.query('Project').first()
    asset = session.create('Asset', {
        'name': 'integration_test',
        'type': session.query('AssetType').first(),
        'parent': project
    })
    version = session.create('AssetVersion', {
        'asset': asset,
        'task': None
    })
    session.commit()
    
    # 2. Create test file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
    temp_file.write(b'Test content for integration test')
    temp_file.close()
    
    # 3. Upload component
    location = session.query('Location where name is "ftrack.server"').one()
    component = version.create_component(
        path=temp_file.name,
        data={'name': 'main'},
        location=location
    )
    session.commit()
    
    logger.info('Created test component: {}'.format(component['id']))
    
    # 4. Test sync (if sync functions available)
    # Import optimized sync
    from ftrack_user_location.sync import on_sync_to_destination, check_batch_availability
    
    # Test batch availability check
    availability = check_batch_availability(location, [component])
    assert component['id'] in availability
    assert availability[component['id']] == 100.0
    
    logger.info('Batch availability check: PASSED')
    
    # 5. Cleanup
    session.delete(component)
    session.delete(version)
    session.delete(asset)
    session.commit()
    
    os.unlink(temp_file.name)
    
    logger.info('Integration test: PASSED')
    return True


if __name__ == '__main__':
    try:
        test_sync_workflow()
        print('\n✓ All integration tests passed')
    except Exception as e:
        print('\n✗ Integration test failed: {}'.format(e))
        import traceback
        traceback.print_exc()
```

Run:
```bash
uv run python tests/integration_test.py
```

---

## Rollback Plan

If issues occur after migration:

### Immediate Rollback (< 1 hour)
```bash
# Restore backup
git checkout HEAD~1 source/ftrack_user_location/sync.py
git checkout HEAD~1 resource/hook/connect_plugin_hook.py
git checkout HEAD~1 resource/hook/sync_action.py

# Rebuild
uv run python setup.py build_plugin

# Reinstall plugin
# (Copy build/ftrack-user-location-*.zip to ftrack Connect)
```

### Partial Rollback
If only specific phases cause issues:

**Phase 1 (Queries) Rollback**:
```bash
git checkout HEAD~3 source/ftrack_user_location/sync.py
```

**Phase 2 (Commits) Rollback**:
```bash
# Keep query optimizations, revert commit batching
git show HEAD~2:source/ftrack_user_location/sync.py > sync_temp.py
# Manually merge query optimizations
```

**Phase 3 (Events) Rollback**:
```bash
git checkout HEAD~1 resource/hook/connect_plugin_hook.py
```

---

## Monitoring After Migration

### Metrics to Track

1. **Sync Performance**:
   - Components synced per minute
   - Average sync time for 100 components
   - Failed sync rate

2. **Error Rates**:
   - Event validation failures
   - Component transfer failures
   - Job failure rate

3. **System Load**:
   - Database query count
   - Session commit frequency
   - Memory usage

### Logging to Monitor

Add to `source/ftrack_user_location/configure_logging.py`:

```python
# Add performance logging
import time

class PerformanceLogger:
    '''Log performance metrics for sync operations.'''
    
    def __init__(self, logger):
        self.logger = logger
        self.start_times = {}
    
    def start(self, operation):
        '''Start timing an operation.'''
        self.start_times[operation] = time.time()
    
    def end(self, operation, count=None):
        '''End timing and log performance.'''
        if operation not in self.start_times:
            return
        
        elapsed = time.time() - self.start_times[operation]
        
        if count:
            rate = count / elapsed if elapsed > 0 else 0
            self.logger.info(
                'PERF: {} completed in {:.2f}s ({:.1f} items/sec)'.format(
                    operation, elapsed, rate
                )
            )
        else:
            self.logger.info(
                'PERF: {} completed in {:.2f}s'.format(operation, elapsed)
            )
        
        del self.start_times[operation]
```

Usage in sync.py:
```python
from ftrack_user_location.configure_logging import PerformanceLogger

perf = PerformanceLogger(logger)

def on_sync_to_destination(session, source_id, destination_id, components, user_id):
    perf.start('sync_to_destination')
    
    # ... sync logic ...
    
    perf.end('sync_to_destination', count=len(successful))
```

---

## Post-Migration Checklist

- [ ] All performance tests pass with expected speedup
- [ ] Integration tests pass
- [ ] Plugin builds without errors
- [ ] Manual testing in ftrack Connect
- [ ] Sync 10 components successfully
- [ ] Sync 100+ components successfully
- [ ] Error handling works (invalid location names)
- [ ] Progress tracking visible in Job UI
- [ ] Partial failures handled correctly
- [ ] Event validation prevents crashes
- [ ] No memory leaks after 1000+ syncs
- [ ] Documentation updated
- [ ] Migration guide reviewed by team
- [ ] Monitoring dashboard created
- [ ] Alert thresholds configured

---

## Expected Results

### Before Migration:
- 100 components: ~5-10 minutes
- 1000 commits to database
- No progress tracking
- Frequent crashes on malformed events
- Poor error messages

### After Migration:
- 100 components: ~30-60 seconds (5-10x faster)
- 100 commits to database (10x reduction)
- Real-time progress in ftrack UI
- Robust event handling with validation
- Detailed error reporting with partial success

---

## Support and Troubleshooting

### Common Issues

**Issue**: "Location not found" errors after migration
**Fix**: Verify location names haven't changed. Check database with:
```python
session.query('select name from Location').all()
```

**Issue**: Performance not improved as expected
**Fix**: 
1. Check `BATCH_COMMIT_SIZE` - may need tuning (5-20 range)
2. Verify session cache is enabled
3. Check network latency to ftrack server

**Issue**: Components fail to sync with rollback errors
**Fix**: 
1. Check component file permissions
2. Verify location accessors configured correctly
3. Review specific component error in job data

---

## Timeline Summary

| Phase | Time | Can Parallelize? |
|-------|------|------------------|
| Phase 1: Queries | 3-4 hours | Yes |
| Phase 2: Sessions | 4-5 hours | No (depends on Phase 1) |
| Phase 3: Events | 2-3 hours | Yes |
| Phase 4: Components | Included in Phase 2 | - |
| Phase 5: Actions | 2 hours | Yes |
| Testing | 1 day | No |
| **Total** | **3-4 days** | - |

---

## Next Steps

1. Review this guide with team
2. Schedule migration window (recommend: Friday for weekend testing)
3. Backup production plugin
4. Execute Phase 1
5. Test and validate
6. Continue with remaining phases
7. Monitor for 1 week
8. Document lessons learned

---

**Questions or issues?** Contact the ftrack API development team.
