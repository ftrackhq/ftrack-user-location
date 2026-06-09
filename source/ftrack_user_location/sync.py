# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

import ftrack_api
import logging
import json


logger = logging.getLogger(__name__)

# Configuration
BATCH_COMMIT_SIZE = 10  # Commit every 10 components for optimal performance
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


def on_sync_to_destination(session, source_id, destination_id, components, user_id):
    '''Callback for when files are copied between locations.

    Args:
        session: ftrack API session
        source_id: Source location ID
        destination_id: Destination location ID
        components: List of component dicts with 'id' key
        user_id: User ID requesting sync
    '''
    # Batch query with projection (optimized)
    component_ids = [cid['id'] for cid in components]

    if not component_ids:
        logger.info('No components to sync')
        return

    components = session.query(
        'select id, name, version_id from Component where id in ({})'.format(
            ','.join('"{}"'.format(cid) for cid in component_ids)
        )
    ).all()

    logger.info('Queried {} components for sync'.format(len(components)))

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

    # start the job
    job = session.create('Job', {
        'description': "Sync from {} to {} ".format(
            source_name,
            destination_name
        ),
        'user': session.get('User', user_id),
        'status': 'running'
    })
    session.commit()

    # sanity checks for the transfer
    if not all([source_accessor, destination_accessor]):
        message = 'Locations are not accessible : {}, {}'.format(
            destination_name,
            source_name
        )
        job['data'] = json.dumps({
            'description': message
        })
        job['status'] = 'failed'
        logger.error(message)
        session.commit()
        return

    # Track progress and results
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
            skipped.append(component_name)
            continue

        logger.debug(
            '"{}" availability in {} is {}'.format(
                component_name, source_name, source_available
            )
        )
        logger.debug(
            '"{}" availability in {} is {}'.format(
                component_name, destination_name, destination_available
            )
        )

        if destination_available == 100.0:
            status = '"{}" already exists in {}'.format(
                component_name,
                destination_name
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

            # Batch commit for performance
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
            session.rollback()
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
    '''Sync components from local location to remote.

    Args:
        session: ftrack API session
        source: Source location name
        destination: Destination location name
        user_id: User ID requesting sync
        selection: List of selected entities

    Raises:
        ValueError: If required locations not found
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

    # Query locations by name directly (optimized - prevents fetching all locations)
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

    # create a job to inform the user that something is going on
    message = " Sync from {} to {}".format(source_name, sync_name)
    logger.info(message)

    job = session.create('Job', {
        'data': json.dumps({
            'description': message
        }),
        'user': user,
        'status': 'running'
    })
    session.commit()

    # Batch query with projection (optimized - prevents N+1 query problem)
    version_ids = [s['entityId'] for s in selection]

    if not version_ids:
        logger.warning('No versions selected for sync')
        job['status'] = 'done'
        session.commit()
        return

    # Single query with projection - much faster than N individual queries
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

            # Batch commit for performance
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

    event = ftrack_api.event.base.Event(
        topic='ftrack.sync',
        data={
            'actionIdentifier': 'ftrack-to-{}'.format(results['output']['name']),
            'components': components,
            'locations': {
                'sync': results['sync']['id'],
                'source': results['input']['id'],
                'destination': results['output']['id']
            }
        },
        source={'user': user_id}
    )

    session.event_hub.publish(event)
