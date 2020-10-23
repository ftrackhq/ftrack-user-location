import ftrack_api
import logging

logger = logging.getLogger(__name__)
ftrack_api


sync_serve_name = 'ftrack.server'


def on_sync_to_destination(session, source_id, destination_id, components, userId):
    ''' Callback for when files are copied from the cloud location into the
    destination one.

        *source_id* : The id if the source location.
        *destination_id* : The id if the source location.
        *components* : a list of ids of all the component to be copied over.
        *userId* : the id of the user who requested the sync.

    '''
    # get location objects
    source_location = session.get('Location', source_id)
    destination_location = session.get('Location', destination_id)
    logger.debug("Sync to dest: source loc = %s, dest loc = %s" % (source_location, destination_location))

    # get location accessors
    source_accessor = source_location.getAccessor()
    destination_accessor = destination_location.getAccessor()

    logger.debug("Sync to dest: source acc = %s, dest acc = %s" % (source_accessor, destination_accessor))
    # get the location names
    source_name = source_location.getName()
    destination_name = destination_location.getName()
    logger.debug("Sync to dest: source name = %s, dest name = %s" % (source_name, destination_name))

    # start the job
    job = ftrack.createJob(
            description="Sync from %s to %s " % (
                source_name,
                destination_name
            ),
            status="running",
            user=ftrack.User(userId)
    )

    # sanity checks for the transfer
    if not all([source_accessor, destination_accessor]):
        message = 'locations not available : %s, %s' % (
            destination_name,
            source_name
        )
        job.setDescription(message)
        job.setStatus('failed')
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
            logger.debug('Component %s can not be sync' % component_name)
            continue

        destination_available = destination_location.getComponentAvailabilities(
            [component_id]
        )[0]

        source_available = source_location.getComponentAvailabilities(
            [component_id]
        )[0]

        if source_available == 0.0:
            status = 'component %s is not available in %s' % (
                component_name, source_name
            )
            logger.warning(status)
            job.setDescription(status)
            job.setStatus('failed')
            continue
        else:
            status = 'component %s is available in %s' % (
                component_name, source_name
            )
            job.setDescription(status)

        logger.info(
            '%s availability in %s is %s' % (
                component_name, source_name, source_available
            )
        )
        logger.info(
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
            job.setDescription(status)
            logger.warning(status)
            continue

        message = 'copying %s, from %s to %s' % (
                component_name,
                source_name,
                destination_name
        )

        logger.info(message)
        job.setDescription(message)

        try:
            destination_location.addComponent(
                source_location.getComponent(component_id)
            )

        except ftrack.ComponentInLocationError, error:
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

    job.setStatus('done')
    logger.info('Finished sync of %i components.' % len(components))

def on_sync_to_remote(session, source, destination, userId, selection):
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
        'sync': sync_serve_name,
        'input': source,
        'output': destination
    }

    logger.debug("Sync to remote: source = %s, dest = %s, user = %s, sel = %s" % (source, destination, userId, selection))

    results = {}
    for location in session.query('Location').all():
        location_name = location['name']
        for store_type, store_name in store_mapping.items():
            if store_name == location_name:
                logger.debug("sync to remote, found location %s, store = %s, type = %s" % (location_name, store_name, store_type))
                results[store_type] = location

    source_name = results['input']['name']
    sync_name = results['sync']['name']
    logger.debug("Sync to remote: source name = %s, sync name = %s" % (source_name, sync_name))

    # create a job to inform the user that something is going on
    message = " Sync from %s to %s" % (source_name, sync_name)
    logger.info(message)
    # job = ftrack.createJob(
    #         description=message,
    #         status="running",
    #         user=ftrack.User(userId)
    # )

    components = []
    for s in selection:
        version = session.get('AssetVersion', s['entityId'])

        # get all the asset components
        for component in version.getComponents():
            component_name = component.getName()
            component_id = component.getId()
            components.append(
                {
                    'id': component.getId(),
                    'name': component_name
                }
            )

            job.setDescription('Sync %s from %s to %s' % (
                component_name,
                source_name,
                sync_name
                )
            )
            # check if the component is available in the source location
            logger.debug("input = %s of type %s" % (results['input'], type(results['input'])))
            source_component = results['input'].getComponentAvailabilities(
                [component_id]
            )[0]
            if source_component != 100.0:
                status = '%s not available %s, availability = %s' % (
                    component_name,
                    source_name,
                    source_component
                )
                logger.warning(status)
                job.setDescription(status)
                continue

            # check whether the component is already available
            # in the sync location
            synced_component = results['sync'].getComponentAvailabilities(
                [component_id]
            )[0]
            if synced_component == 100.0:
                status = '%s already sync to %s' % (
                    component_name,
                    sync_name
                )
                logger.warning(status)
                job.setDescription(status)
                continue

            logger.info('copying %s , from %s to %s' % (
                    component.getName(),
                    source_name,
                    sync_name
                    )
            )

            try:
                results['sync'].addComponent(
                    results['input'].getComponent(component_id)
                )

            except ftrack.ComponentInLocationError, error:
                logger.warning(error)
                continue

            except Exception:
                import traceback
                logger.error(traceback.format_exc())
                job.setStatus('failed')
                # sys.exit(1)

    job.setStatus('done')
    logger.info('Finished uploading %i components.' % len(components))

    # emit the signal to trigger the destination sync
    event = {
        'data': {
            'actionIdentifier': 'syncto-%s' % results['output'].getName(),
            'components': components,
            'locations': {
                'sync': results['sync'].getId(),
                'source': results['input'].getId(),
                'destination': results['output'].getId()
            }
        },
        'source': {'user': userId},
        'topic': 'ftrack.sync'
    }
    session.event_hub.publish(event)
