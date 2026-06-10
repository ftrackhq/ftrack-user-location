# :coding: utf-8
# :copyright: Copyright (c) 2014-2021 ftrack

import os
import sys
import functools
import logging
import platform
import ftrack_api
import ftrack_api.accessor.disk as _disk
import ftrack_api.structure.standard as _standard
from ftrack_user_location.configure_logging import configure_logging

# Ensure logging is configured for this location hook
# (hooks run outside the package __init__, so configure explicitly)
configure_logging('ftrack_user_location', level=logging.DEBUG)

logger = logging.getLogger(
    'ftrack_user_location'
)




def configure_location(session, event):
    '''Configure user location for this machine.'''

    logger.info('[configure_location] Starting location configuration')
    logger.info(f'[configure_location] Session user: {session.api_user}')
    logger.info(f'[configure_location] Server URL: {session.server_url}')

    # provide a sanitised instance name to be used as folder
    server_folder_name = session.server_url.split(
        '//'
    )[-1].split('.')[0].replace('-', '_')
    logger.debug(f'[configure_location] Server folder name: {server_folder_name}')

    # Default Disk mount point.
    DEFAULT_USER_DISK_PREFIX = os.path.join(
        os.path.expanduser('~'),
        'Documents',
        'local_ftrack_projects',
        server_folder_name
    )

    # Override environment variable for user location prefix
    USER_DISK_PREFIX = os.getenv(
        'FTRACK_USER_LOCATION_PATH',
        DEFAULT_USER_DISK_PREFIX
    )

    if USER_DISK_PREFIX != DEFAULT_USER_DISK_PREFIX:
        logger.info(
            f'[configure_location] Using custom path from FTRACK_USER_LOCATION_PATH: '
            f'{USER_DISK_PREFIX}'
        )

    if not os.path.exists(USER_DISK_PREFIX):
        logger.info(f'[configure_location] Creating folder: {USER_DISK_PREFIX}')
        os.makedirs(USER_DISK_PREFIX)
    else:
        logger.debug(f'[configure_location] Folder already exists: {USER_DISK_PREFIX}')

    logger.info(f'[configure_location] Location path: {os.path.abspath(USER_DISK_PREFIX)}')

    hostname = platform.node()
    original_hostname = hostname
    if platform.system() == 'Darwin' and hostname.endswith('.local'):
        hostname = hostname[:hostname.find('.local')]
        logger.debug(
            f'[configure_location] macOS hostname adjusted: '
            f'{original_hostname} → {hostname}'
        )

    # Name of the location.
    DEFAULT_LOCATION_NAME = '{}.{}'.format(
        session.api_user,
        hostname
    )

    USER_LOCATION_NAME = os.getenv(
        'FTRACK_USER_LOCATION_NAME',
        DEFAULT_LOCATION_NAME
    )

    if USER_LOCATION_NAME != DEFAULT_LOCATION_NAME:
        logger.info(
            f'[configure_location] Using custom location name from '
            f'FTRACK_USER_LOCATION_NAME: {USER_LOCATION_NAME}'
        )

    logger.info(f'[configure_location] Location name: {USER_LOCATION_NAME}')

    location = session.query('Location where name is "{}"'.format(USER_LOCATION_NAME)).first()
    if not location:
        logger.info(f'[configure_location] Location not found in ftrack, creating new one')
        location = session.ensure(
            'Location',
            {
                'name': USER_LOCATION_NAME,
                'description': 'User location for user '
                ': {}, on host {}, with path: {}'.format(
                    session.api_user,
                    hostname,
                    os.path.abspath(USER_DISK_PREFIX)
                )
            }
        )
        logger.info(f'[configure_location] Created new location: {location["id"]}')
    else:
        logger.info(f'[configure_location] Found existing location: {location["id"]}')

    location.accessor = _disk.DiskAccessor(
        prefix=USER_DISK_PREFIX
    )
    location.structure = _standard.StandardStructure()
    location.priority = 1-sys.maxsize

    logger.warning(
        f'[configure_location] ✅ Registered location: {USER_LOCATION_NAME} '
        f'@ {USER_DISK_PREFIX} with priority {location.priority}'
    )
    logger.info(
        f'[configure_location] Location configuration complete '
        f'[name={USER_LOCATION_NAME}, id={location["id"]}, '
        f'accessor={type(location.accessor).__name__}, '
        f'structure={type(location.structure).__name__}]'
    )


def register(api_object, **kw):
    '''Register location with *session*.'''

    logger.info('[register] User location plugin initializing')

    if not isinstance(api_object, ftrack_api.Session):
        logger.warning('[register] API object is not a Session, skipping registration')
        return

    # Check if user location should be disabled (main studio machine)
    if os.getenv('FTRACK_USER_MAIN_LOCATION'):
        logger.warning(
            '[register] FTRACK_USER_MAIN_LOCATION is set - '
            'User location disabled (main studio mode)'
        )
        return

    logger.info('[register] Subscribing to ftrack.api.session.configure-location event')
    api_object.event_hub.subscribe(
        'topic=ftrack.api.session.configure-location',
        functools.partial(configure_location, api_object)
    )
    logger.info('[register] User location plugin registered successfully')
