# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

import ftrack_api
import logging
import json
import time


logger = logging.getLogger(__name__)


def _log_sync_context(logger_func, msg, **context):
    """Log message with structured context.

    Args:
        logger_func: Logger method (logger.info, logger.error, etc.)
        msg: Primary log message
        **context: Additional context fields (job_id, user, component, etc.)
    """
    context_parts = []
    for key, value in context.items():
        if value is not None:
            context_parts.append(f"{key}={value}")

    if context_parts:
        full_msg = f"{msg} [{', '.join(context_parts)}]"
    else:
        full_msg = msg

    logger_func(full_msg)


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

    start_time = time.time()

    # ✅ FIX: Get session user (executor) - fixes permission errors
    session_user = session.query(
        'User where username is "{}"'.format(session.api_user)
    ).first()

    _log_sync_context(
        logger.info,
        "Starting sync operation",
        executor=session_user['username'],
        requesting_user_id=requesting_user_id,
        source=source_name,
        destination=destination_name,
        component_count=len(components)
    )

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

    _log_sync_context(
        logger.info,
        "Job created",
        job_id=job_id,
        job_owner=session_user['username']
    )

    # sanity checks for the transfer
    if not all([source_accessor, destination_accessor]):
        # ✅ FIX: Re-query Job before updating
        job = session.get('Job', job_id)

        message = 'Locations are not accessible'
        _log_sync_context(
            logger.error,
            message,
            job_id=job_id,
            source=source_name,
            destination=destination_name,
            source_accessible=bool(source_accessor),
            destination_accessible=bool(destination_accessor)
        )

        job['data'] = json.dumps({
            'description': message + f': {destination_name}, {source_name}',
            'requested_by': requesting_user_id
        })
        job['status'] = 'failed'
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

        _log_sync_context(
            logger.debug,
            "Checking component availability",
            job_id=job_id,
            component=component_name,
            source_avail=f"{source_available:.0%}",
            dest_avail=f"{destination_available:.0%}"
        )

        if source_available == 0.0:
            _log_sync_context(
                logger.warning,
                "Component not available in source",
                job_id=job_id,
                component=component_name,
                source=source_name
            )
            # ✅ FIX: Track failure instead of updating Job immediately
            components_failed.append({
                'name': component_name,
                'error': 'Not available in source location'
            })
            continue

        if destination_available == 100.0:
            _log_sync_context(
                logger.info,
                "Component already exists at destination (skipping)",
                job_id=job_id,
                component=component_name
            )
            # ✅ FIX: Count as synced (already exists)
            components_synced.append(component_name)
            continue

        _log_sync_context(
            logger.debug,
            "Copying component",
            job_id=job_id,
            component=component_name,
            source=source_name,
            destination=destination_name
        )

        try:
            destination_location.add_component(
                component,
                source_location
            )
            # ✅ FIX: Track success
            components_synced.append(component_name)
            _log_sync_context(
                logger.info,
                "Component synced successfully",
                job_id=job_id,
                component=component_name,
                component_id=component_id
            )

        except ftrack_api.exception.ComponentInLocationError as error:
            _log_sync_context(
                logger.warning,
                "Component already exists at destination (ComponentInLocationError)",
                job_id=job_id,
                component=component_name,
                error=str(error)
            )
            # ✅ FIX: Count as synced (already exists)
            components_synced.append(component_name)
            continue

        except Exception as error:
            import traceback
            _log_sync_context(
                logger.error,
                "Component sync failed",
                job_id=job_id,
                component=component_name,
                component_id=component_id,
                error_type=type(error).__name__,
                error=str(error)
            )
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

    duration = time.time() - start_time
    _log_sync_context(
        logger.info,
        "Sync operation completed",
        job_id=job_id,
        status=job['status'],
        total_components=len(components),
        succeeded=len(components_synced),
        failed=len(components_failed),
        duration_seconds=f"{duration:.2f}",
        components_per_second=f"{len(components)/duration:.2f}" if duration > 0 else "N/A"
    )


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

    start_time = time.time()

    # ✅ FIX: Get session user (executor)
    session_user = session.query(
        'User where username is "{}"'.format(session.api_user)
    ).first()

    # Get requesting user for logging
    requesting_user = session.get('User', requesting_user_id)

    _log_sync_context(
        logger.info,
        "Starting remote sync operation",
        executor=session_user['username'],
        requesting_user=requesting_user['username'],
        source=source,
        destination=destination,
        asset_version_count=len(selection)
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

    # ✅ FIX: Create Job owned by executor, track requester in metadata
    job = session.create('Job', {
        'data': json.dumps({
            'description': f"Sync from {source_name} to {sync_name}",
            'requested_by': requesting_user_id
        }),
        'user': session_user,  # Executor owns Job
        'status': 'running'
    })
    session.commit()

    # ✅ FIX: Store job ID for re-querying
    job_id = job['id']

    _log_sync_context(
        logger.info,
        "Job created for remote sync",
        job_id=job_id,
        job_owner=session_user['username'],
        source=source_name,
        destination=sync_name
    )

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

            _log_sync_context(
                logger.debug,
                "Processing component",
                job_id=job_id,
                component=component_name,
                component_id=component_id
            )

            source_component = results['input'].get_component_availability(
                component
            )
            if source_component != 100.0:
                _log_sync_context(
                    logger.warning,
                    "Component not available in source",
                    job_id=job_id,
                    component=component_name,
                    source=source_name,
                    availability=f"{source_component:.0%}"
                )
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
                _log_sync_context(
                    logger.info,
                    "Component already synced (skipping)",
                    job_id=job_id,
                    component=component_name
                )
                # ✅ FIX: Count as synced (already exists)
                components_synced.append(component_name)
                continue

            _log_sync_context(
                logger.debug,
                "Copying component to sync location",
                job_id=job_id,
                component=component_name,
                source=source_name,
                destination=sync_name
            )

            try:
                results['sync'].add_component(
                    component, results['input']
                )
                # ✅ FIX: Track success
                components_synced.append(component_name)
                _log_sync_context(
                    logger.info,
                    "Component synced successfully",
                    job_id=job_id,
                    component=component_name,
                    component_id=component_id,
                    destination=sync_name
                )

            except ftrack_api.exception.ComponentInLocationError as error:
                _log_sync_context(
                    logger.warning,
                    "Component already exists (ComponentInLocationError)",
                    job_id=job_id,
                    component=component_name,
                    error=str(error)
                )
                # ✅ FIX: Count as synced (already exists)
                components_synced.append(component_name)
                continue

            except Exception as error:
                import traceback
                _log_sync_context(
                    logger.error,
                    "Component sync failed",
                    job_id=job_id,
                    component=component_name,
                    component_id=component_id,
                    error_type=type(error).__name__,
                    error=str(error)
                )
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

    duration = time.time() - start_time
    _log_sync_context(
        logger.info,
        "Remote sync operation completed",
        job_id=job_id,
        status=job['status'],
        total_components=len(components),
        succeeded=len(components_synced),
        failed=len(components_failed),
        duration_seconds=f"{duration:.2f}",
        components_per_second=f"{len(components)/duration:.2f}" if duration > 0 else "N/A"
    )

    # ✅ FIX: Publish event with string user ID
    _log_sync_context(
        logger.debug,
        "Publishing sync event for remote destination",
        job_id=job_id,
        destination=results['output']['name']
    )

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
