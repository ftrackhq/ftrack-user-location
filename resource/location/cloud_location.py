# :coding: utf-8
# :copyright: Copyright (c) 2014-2020 ftrack

import os
import sys
import logging
import functools
import platform

dependencies_directory = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'dependencies')
)
sys.path.append(dependencies_directory)

import boto3
import ftrack_api
import ftrack_api.structure.standard
from ftrack_s3_accessor.s3 import S3Accessor


# Pick the current folder location name.
this_dir = os.path.abspath(os.path.dirname(__file__))


def configure_location(session, event):
    '''Configure locations for *session* and *event*.'''

    logging.info('Configuring location....')

    my_location = session.ensure(
        'Location', {
            'name': 'ftrack.sync'
        }
    )

    # Set new structure in location.
    my_location.structure = ftrack_api.structure.standard.StandardStructure()
    
    # Set accessor.
    my_location.accessor = S3Accessor('ftrack.sync.location')

    # Set priority.
    my_location.priority = -1000


def register(api_object):
    '''Register plugin with *api_object*.'''

    # Validate that session is an instance of ftrack_api.Session. If not, assume
    # that register is being called from an old or incompatible API and return
    # without doing anything.
    if not isinstance(api_object, ftrack_api.Session):
        logger.debug(
            'Not subscribing plugin as passed argument {0} is not an '
            'ftrack_api.Session instance.'.format(api_object)
        )
        return

    # React to configure location event.
    api_object.event_hub.subscribe(
        'topic=ftrack.api.session.configure-location',
        functools.partial(configure_location, api_object),
        priority=0
    )