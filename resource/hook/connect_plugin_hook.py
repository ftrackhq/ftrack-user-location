# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

import os
import sys
import logging

import ftrack_api

LOCATION_DIRECTORY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'location')
)

sys.path.append(LOCATION_DIRECTORY)

logger = logging.getLogger('ftrack_user_location')

MAIN_LOCATION = os.getenv(
    'FTRACK_USER_MAIN_LOCATION', False
)



def appendPath(path, key, environment):
    '''Append *path* to *key* in *environment*.'''
    try:
        environment[key] = (
            os.pathsep.join([
                environment[key], path
            ])
        )
    except KeyError:
        environment[key] = path

    return environment

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


def register(api_object, **kw):
    '''Register plugin to api_object.'''

    # Validate that api_object is an instance of ftrack_api.Session. If not,
    # assume that register is being called from an incompatible API
    # and return without doing anything.
    if not isinstance(api_object, ftrack_api.Session):
        # Exit to avoid registering this plugin again.
        return

    logger.info('Connect plugin discovered.')

    if not MAIN_LOCATION:
        import user_location
        user_location.register(api_object)

    # Location will be available from DCC applications and actions (combined subscription)
    api_object.event_hub.subscribe(
        'topic=ftrack.connect.application.launch or topic=ftrack.action.launch',
        modify_application_launch
    )

