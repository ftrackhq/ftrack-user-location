# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

import ftrack_api
import logging
import json


logger = logging.getLogger(__name__)


def on_sync_to_destination(session, source_id, destination_id, components, requesting_user_id):
    ''' Callback for when files are copied from the cloud location into the
    destination one.

        *source_id* : The id of the source location.
        *destination_id* : The id of the destination location.
        *components* : a list of ids of all the component to be copied over.
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

    # ✅ FIX: Get session user (executor) - fixes permission errors
    session_user = session.query(
        'User where username is "{}"'.format(session.api_user)
    ).first()

    # ✅ FIX: Create Job owned by executor, track requester in metadata
    job = session.create('Job', {
        'data': json.dumps({
            'description': "Sync from {} to {} ".format(
                source_name,
                destination_name
            ),
            'requested_by': requesting_user_id
        }),
        'user': session_user,  # Executor owns Job
        'status': 'running'
    })
    session.commit()

    # ✅ FIX: Store job ID for re-querying (fixes "must be committed first" error)
    job_id = job['id']

    # sanity checks for the transfer
    if not all([source_accessor, destination_accessor]):
        # ✅ FIX: Re-query Job before updating
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

    # ✅ FIX: Track sync results for final Job update
    components_synced = []
    components_failed = []

    # now try to do the sync for each component
    for component in components:
        component_id = component['id']
        component_name = component['name']

        # exclude ftrack-review component names ?
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
            # ✅ FIX: Track failure instead of updating Job immediately
            components_failed.append({
                'name': component_name,
                'error': 'Not available in source location'
            })
            continue
        else:
            status = 'component "{}" is available in {}'.format(
                component_name, source_name
            )
            logger.debug(status)

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
            status = '"{}" already sync from {} to {}'.format(
                component_name,
                source_name,
                destination_name
            )
            logger.info(status)
            # ✅ FIX: Count as synced (already exists)
            components_synced.append(component_name)
            continue

        message = 'Copying Component "{}" from {} to {}'.format(
                component_name,
                source_name,
                destination_name
        )

        logger.debug(message)

        try:
            destination_location.add_component(
                component,
                source_location
            )
            # ✅ FIX: Track success
            components_synced.append(component_name)
            logger.info(
                'Added component "{}" from {} to {}'.format(
                    component_name, source_name, destination_name
                )
            )

        except ftrack_api.exception.ComponentInLocationError as error:
            logger.warning(error)
            # ✅ FIX: Count as synced (already exists)
            components_synced.append(component_name)
            continue

        except Exception as error:
            logger.error('Component "{}" with ID {} failed: {}'.format(
                component_name,
                component_id,
                error
            ))
            import traceback
            logger.error(traceback.format_exc())
            # ✅ FIX: Track failure instead of immediate Job update
            components_failed.append({
                'name': component_name,
                'error': str(error)
            })

    # ✅ FIX: Batch commit all component operations (performance fix)
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

    logger.info('Finished processing {} components ({} succeeded, {} failed).'.format(
        len(components), len(components_synced), len(components_failed)
    ))


def on_sync_to_remote(session, source, destination, requesting_user_id, selection):
    ''' Callback for when files are copied from the local location to the cloud
        one.

        *source* : The source location name.
        *destination* : The destination location name.
        *requesting_user_id* : the id of the user who requested the sync.
        *selection* : a list of the ids of the selected entity in ftrack.

        once the copy to the cloud location is completed, an event
        `ftrack.sync` will then be emitted to sync the data to the
        destination.
    '''
    store_mapping = {
        'sync': 'ftrack.server',
        'input': source,
        'output': destination
    }

    # ✅ FIX: Get session user (executor)
    session_user = session.query(
        'User where username is "{}"'.format(session.api_user)
    ).first()

    # Get requesting user for logging
    requesting_user = session.get('User', requesting_user_id)

    logger.info(
        "User {} is syncing {} items from {} to {}".format(
            requesting_user['username'], len(selection),
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

    source_name = results['input']['name']
    sync_name = results['sync']['name']

    # create a job to inform the user that something is going on
    message = " Sync from {} to {}".format(source_name, sync_name)
    logger.info(message)

    # ✅ FIX: Create Job owned by executor, track requester in metadata
    job = session.create('Job', {
        'data': json.dumps({
            'description': message,
            'requested_by': requesting_user_id
        }),
        'user': session_user,  # Executor owns Job
        'status': 'running'
    })
    session.commit()

    # ✅ FIX: Store job ID for re-querying
    job_id = job['id']

    # ✅ FIX: Track sync results
    components = []
    components_synced = []
    components_failed = []
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

            # ✅ FIX: Remove per-component Job updates
            logger.debug('Processing {} from {} to {}'.format(
                component_name,
                source_name,
                sync_name
            ))

            source_component = results['input'].get_component_availability(
                component
            )
            if source_component != 100.0:
                status = 'Component {} not available in {} : {}'.format(
                    component_name,
                    source_name,
                    source_component
                )
                logger.warning(status)
                # ✅ FIX: Track failure
                components_failed.append({
                    'name': component_name,
                    'error': 'Not available in source location'
                })
                continue

            # check whether the component is already available
            # in the sync location
            synced_component = results['sync'].get_component_availability(
                component
            )

            if synced_component == 100.0:
                status = 'Component {} already synced to {}'.format(
                    component_name,
                    sync_name
                )
                logger.info(status)
                # ✅ FIX: Count as synced (already exists)
                components_synced.append(component_name)
                continue

            logger.debug('copying {} from {} to {}'.format(
                    component['name'],
                    source_name,
                    sync_name
                )
            )

            try:
                results['sync'].add_component(
                    component, results['input']
                )
                # ✅ FIX: Track success
                components_synced.append(component_name)
                logger.info('Added component {} to {}'.format(
                    component_name, sync_name
                ))

            except ftrack_api.exception.ComponentInLocationError as error:
                logger.warning(error)
                # ✅ FIX: Count as synced (already exists)
                components_synced.append(component_name)
                continue

            except Exception as error:
                import traceback
                logger.error(traceback.format_exc())
                # ✅ FIX: Track failure
                components_failed.append({
                    'name': component_name,
                    'error': str(error)
                })

    # ✅ FIX: Batch commit all component operations
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
                sync_name
            ),
            'requested_by': requesting_user_id,
            'components_synced': components_synced
        })

    session.commit()

    logger.info('Finished processing {} components ({} succeeded, {} failed).'.format(
        len(components), len(components_synced), len(components_failed)
    ))

    # ✅ FIX: Publish event with string user ID
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
        source={'user': {'id': requesting_user_id}}
    )

    session.event_hub.publish(event)
