# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

import ftrack_api
import logging
import json
import time
from .sync_report import create_and_attach_sync_report


logger = logging.getLogger(__name__)


def _format_size(bytes_size):
    """Format file size in bytes to human-readable string."""
    if bytes_size is None:
        return "unknown"

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return "{:.2f} {}".format(bytes_size, unit)
        bytes_size /= 1024.0
    return "{:.2f} PB".format(bytes_size)


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

        # Provide clear error message based on which accessor is missing
        if not source_accessor and not destination_accessor:
            message = f'Both locations are not accessible: {source_name} and {destination_name}'
            hint = 'Ensure both locations are registered on this machine'
        elif not source_accessor:
            message = f'Source location is not accessible: {source_name}'
            hint = (
                f'The source location "{source_name}" is not available on this machine. '
                f'For remote-to-local transfers, use a two-step process: '
                f'1) Remote machine syncs to ftrack.server, then '
                f'2) Local machine syncs from ftrack.server to local'
            )
        else:
            message = f'Destination location is not accessible: {destination_name}'
            hint = f'The destination location "{destination_name}" is not available on this machine'

        _log_sync_context(
            logger.error,
            message,
            job_id=job_id,
            source=source_name,
            destination=destination_name,
            source_accessible=bool(source_accessor),
            destination_accessible=bool(destination_accessor)
        )
        logger.info(f"Sync hint: {hint}")

        job['data'] = json.dumps({
            'description': f'{message}. {hint}',
            'requested_by': requesting_user_id
        })
        job['status'] = 'failed'
        session.commit()
        return

    # ✅ FIX: Track sync results for final Job update and reporting
    components_synced = []
    components_failed = []
    components_skipped = []

    # now try to do the sync for each component
    for component in components:
        component_id = component['id']
        component_name = component['name']

        # Get asset version info for reporting
        version_info = 'N/A'
        try:
            if component.get('version'):
                version = component['version']
                version_info = f"{version['asset']['name']} v{version['version']}"
        except Exception:
            pass

        # Get component size for reporting
        component_size = component.get('size')

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
                'id': component_id,
                'error': 'Not available in source location',
                'error_type': 'ComponentUnavailable',
                'version': version_info,
                'size': component_size
            })
            continue

        if destination_available == 100.0:
            _log_sync_context(
                logger.info,
                "Component already exists at destination (skipping)",
                job_id=job_id,
                component=component_name
            )
            # Track as skipped (already exists)
            components_skipped.append({
                'name': component_name,
                'id': component_id,
                'reason': 'Already exists at destination',
                'version': version_info,
                'size': component_size
            })
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
            # ✅ FIX: Track success with details for reporting
            components_synced.append({
                'name': component_name,
                'id': component_id,
                'version': version_info,
                'size': component_size
            })
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
            # Track as skipped (already exists, caught by exception)
            components_skipped.append({
                'name': component_name,
                'id': component_id,
                'reason': 'Already exists at destination (caught during transfer)',
                'version': version_info,
                'size': component_size
            })
            continue

        except Exception as error:
            import traceback
            error_type = type(error).__name__
            _log_sync_context(
                logger.error,
                "Component sync failed",
                job_id=job_id,
                component=component_name,
                component_id=component_id,
                error_type=error_type,
                error=str(error)
            )
            logger.error(traceback.format_exc())
            # ✅ FIX: Track failure instead of immediate Job update
            components_failed.append({
                'name': component_name,
                'id': component_id,
                'error': str(error),
                'error_type': error_type,
                'version': version_info,
                'size': component_size
            })

    # ✅ FIX: Batch commit all component operations (performance fix)
    session.commit()

    # ✅ FIX: Re-query Job before final update
    job = session.get('Job', job_id)

    # Calculate duration before attaching report
    duration = time.time() - start_time

    # Generate and attach sync report as Job Component
    _log_sync_context(
        logger.info,
        "Generating sync report",
        job_id=job_id,
        synced=len(components_synced),
        skipped=len(components_skipped),
        failed=len(components_failed)
    )

    report_component_id = create_and_attach_sync_report(
        session=session,
        job_id=job_id,
        source_name=source_name,
        destination_name=destination_name,
        executor_username=session_user['username'],
        requesting_user_id=requesting_user_id,
        components_synced=components_synced,
        components_failed=components_failed,
        components_skipped=components_skipped,
        duration=duration
    )

    # ✅ FIX: Set final status based on results
    # Extract component names for backward compatibility
    synced_names = [c['name'] if isinstance(c, dict) else c for c in components_synced]
    failed_details = [{'name': c['name'], 'error': c['error']} for c in components_failed]

    if components_failed:
        job['status'] = 'failed'
        description = '{} components failed, {} succeeded, {} skipped'.format(
            len(components_failed),
            len(components_synced),
            len(components_skipped)
        )
        if report_component_id:
            description += ' - See attached report for details'

        job['data'] = json.dumps({
            'description': description,
            'requested_by': requesting_user_id,
            'components_synced': synced_names,
            'components_failed': failed_details,
            'components_skipped': len(components_skipped),
            'report_component_id': report_component_id
        })
    else:
        job['status'] = 'done'
        description = 'Sync from {} to {} completed successfully - {} synced, {} skipped'.format(
            source_name,
            destination_name,
            len(components_synced),
            len(components_skipped)
        )
        if report_component_id:
            description += ' - See attached report for details'

        job['data'] = json.dumps({
            'description': description,
            'requested_by': requesting_user_id,
            'components_synced': synced_names,
            'components_skipped': len(components_skipped),
            'report_component_id': report_component_id
        })

    session.commit()

    _log_sync_context(
        logger.info,
        "Sync operation completed",
        job_id=job_id,
        status=job['status'],
        total_components=len(components),
        succeeded=len(components_synced),
        skipped=len(components_skipped),
        failed=len(components_failed),
        duration_seconds=f"{duration:.2f}",
        components_per_second=f"{len(components)/duration:.2f}" if duration > 0 else "N/A",
        report_attached=bool(report_component_id)
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

    # Validate required locations were found
    if 'input' not in results or 'sync' not in results:
        error_msg = f"Required locations not found - input: {source}, sync: ftrack.server"
        logger.error(error_msg)
        # Create failed Job without storing job_id since we're returning early
        job = session.create('Job', {
            'data': json.dumps({
                'description': error_msg,
                'requested_by': requesting_user_id
            }),
            'user': session_user,
            'status': 'failed'
        })
        session.commit()
        return

    source_location = results['input']
    sync_location = results['sync']
    source_name = source_location['name']
    sync_name = sync_location['name']

    # CRITICAL: Validate that source location has an accessor on this machine
    # This should only fail if the event was routed incorrectly
    if not source_location.accessor:
        error_msg = (
            f'ERROR: Source location "{source_name}" is not accessible on this machine ({session_user["username"]}). '
            f'This sync event was delivered to the wrong machine! '
            f'The event should have been picked up by the machine running Connect for location "{source_name}". '
            f'Please ensure ftrack Connect is running on the machine that owns this location.'
        )
        _log_sync_context(
            logger.error,
            "Event routing error: source location has no accessor on this machine",
            source=source_name,
            destination=sync_name,
            executor=session_user['username'],
            machine=session.api_user
        )
        logger.error(
            f"Event actionIdentifier should be '{source_name}-to-ftrack' "
            f"and should be picked up by the machine with {source_name} location registered"
        )

        # Create failed Job
        job = session.create('Job', {
            'data': json.dumps({
                'description': error_msg,
                'requested_by': requesting_user_id
            }),
            'user': session_user,
            'status': 'failed'
        })
        session.commit()
        return

    # ✅ FIX: Create Job owned by executor, track requester in metadata
    # Only create Job after validation passes
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

            # Check component size and warn on very large files
            component_size = component.get('size', 0)
            if component_size > 10 * 1024**3:  # 10GB threshold
                size_str = _format_size(component_size)
                _log_sync_context(
                    logger.warning,
                    "WARNING: Large component detected - sync may take a while",
                    job_id=job_id,
                    component=component_name,
                    size=size_str,
                    threshold="10GB"
                )

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
