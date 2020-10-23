import ftrack_api
import logging
import json

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def on_sync_to_destination(session, source_id, destination_id, components, user_id):
    ''' Callback for when files are copied from the cloud location into the
    destination one.

        *source_id* : The id if the source location.
        *destination_id* : The id if the source location.
        *components* : a list of ids of all the component to be copied over.
        *userId* : the id of the user who requested the sync.

    '''
    components = [session.get('Component', cid['id']) for cid in components]

    # get location objects
    source_location = session.get('Location', source_id)
    destination_location = session.get('Location', destination_id)
    logger.warning("Sync to dest: source loc = %s, dest loc = %s" % (source_location, destination_location))
    # get location accessors
    source_accessor = source_location.accessor
    destination_accessor = destination_location.accessor

    logger.warning("Sync to dest: source acc = %s, dest acc = %s" % (source_accessor, destination_accessor))
    # get the location names
    source_name = source_location['name']
    destination_name = destination_location['name']
    logger.warning("Sync to dest: source name = %s, dest name = %s" % (source_name, destination_name))

    # start the job
    job = session.create('Job', {
        'description':"Sync from %s to %s " % (
            source_name,
            destination_name
        ),
        'user': session.get('User', user_id),
        'status': 'running'
    })
    session.commit()

    # sanity checks for the transfer
    if not all([source_accessor, destination_accessor]):
        message = 'locations not available : %s, %s' % (
            destination_name,
            source_name
        )
        job['data'] = json.dumps({
            'description': message
        })
        job['status'] = 'failed'
        logger.warning(message)
        return

    # if STUDIO not in destination_name and SITE not in destination_name:
    #     message = 'No suitable location found for %s' % destination_name
    #     job.setStatus('failed')
    #     job.setDescription(message)
    #     logger.warning(message)
    #     return

    # now try to do the sync for each component
    for component in components:
        component_id = component['id']
        component_name = component['name']
        if 'ftrackreview' in component_name:
            logger.warning('Component %s can not be sync' % component_name)
            continue

        destination_available = destination_location.get_component_availability(
            component
        )

        source_available = source_location.get_component_availability(
            component
        )

        if source_available == 0.0:
            status = 'component %s is not available in %s' % (
                component_name, source_name
            )
            logger.warning(status)
            job['data'] = json.dumps({
                'description': status
            })
            job['status'] = 'failed'
            session.commit()

            continue
        else:
            status = 'component %s is available in %s' % (
                component_name, source_name
            )
            job['data'] = json.dumps({
                'description': status
            })
            session.commit()


        logger.warning(
            '%s availability in %s is %s' % (
                component_name, source_name, source_available
            )
        )
        logger.warning(
            '%s availability in %s is %s' % (
                component_name, destination_name, destination_available
            )
        )

        if destination_available == 100.0:
            status = '%s already sync from %s to %s' % (
                component_name,
                source_name,
                destination_name
            )
            job['data'] = json.dumps({
                'description': status
            })
            logger.warning(status)
            session.commit()

            continue

        message = 'copying %s, from %s to %s' % (
                component_name,
                source_name,
                destination_name
        )

        logger.warning(message)
        job['data'] = json.dumps({
            'description': message
        })
        session.commit()

        try:
            destination_location.add_component(
                component,
                source_location
            )

        except ftrack_api.exception.ComponentInLocationError, error:
            logger.warning(error)
            continue

        except Exception, error:
            logger.error('Component %s with ID %s failed: %s' % (
                component_name,
                component_id,
                error
            ))
            import traceback
            logger.error(traceback.format_exc())
            job.setStatus('failed')
            session.commit()

    job['status'] = 'done'
    session.commit()

    logger.warning('Finished sync of %i components.' % len(components))


def on_sync_to_remote(session, source, destination, user_id, selection):
    ''' Callback for when files are copied from the local location to the cloud
        one.

        *buttonId* : The name of the callback defined in the ftrack interface.
        *userId* : the id of the user who requested the sync.
        *selection* : a list of the ids of the selected entity in ftrack.

        once the copy to the cloud location is completed, an event
        `available_on_amazon` will then be emitted to sync the data to the
        destination.
    '''
    store_mapping = {
        'sync': 'ftrack.server',
        'input': source,
        'output': destination
    }

    logger.warning("Sync to remote: source = %s, dest = %s, user = %s, sel = %s" % (source, destination, user_id, selection))

    results = {}
    for location in session.query('Location').all():
        location_name = location['name']
        for store_type, store_name in store_mapping.items():
            if store_name == location_name:
                logger.warning("sync to remote, found location %s, store = %s, type = %s" % (location_name, store_name, store_type))
                results[store_type] = location

    source_name = results['input']['name']
    sync_name = results['sync']['name']
    logger.warning("Sync to remote: source name = %s, sync name = %s" % (source_name, sync_name))

    # create a job to inform the user that something is going on
    message = " Sync from %s to %s" % (source_name, sync_name)
    logger.warning(message)

    job = session.create('Job', {
        'data': json.dumps({
            'description': message
        }),
        'user': session.get('User', user_id),
        'status': 'running'
    })
    session.commit()

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

            job['data'] = json.dumps(
                {
                    'description': 'Sync %s from %s to %s' % (
                        component_name,
                        source_name,
                        sync_name
                    )
                }
            )
            session.commit()

            # check if the component is available in the source location
            logger.warning("input = %s of type %s" % (results['input'], type(results['input'])))

            source_component = results['input'].get_component_availability(
                component
            )
            if source_component != 100.0:
                status = '%s not available %s, availability = %s' % (
                    component_name,
                    source_name,
                    source_component
                )
                logger.warning(status)
                job['data'] = json.dumps(
                    {
                        'description': status
                    }
                )
                session.commit()

                continue

            # check whether the component is already available
            # in the sync location

            synced_component = results['sync'].get_component_availability(
                component
            )

            if synced_component == 100.0:
                status = '%s already sync to %s' % (
                    component_name,
                    sync_name
                )
                logger.warning(status)
                job['data'] = json.dumps(
                    {
                        'description': status
                    }
                )
                continue

            logger.warning('copying %s , from %s to %s' % (
                    component['name'],
                    source_name,
                    sync_name
                )
            )

            try:
                results['sync'].add_component(
                    component, results['input']
                )

            except ftrack_api.exception.ComponentInLocationError, error:
                logger.warning(error)
                continue

            except Exception:
                import traceback
                logger.error(traceback.format_exc())
                job['status'] = 'failed'
                # sys.exit(1)

    job['status'] = 'done'
    logger.warning('Finished uploading %i components.' % len(components))

    event = ftrack_api.event.base.Event(
        topic='ftrack.sync',
        data={
            'actionIdentifier': 'syncto-%s' % results['output']['name'],
            'components': components,
            'locations': {
                'sync': results['sync']['id'],
                'source': results['input']['id'],
                'destination': results['output']['id']
            }
        },
        source={'user': user_id}
    )

    logger.warning(event)
    session.event_hub.publish(event)
