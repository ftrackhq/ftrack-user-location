# :coding: utf-8
# :copyright: Copyright (c) 2014-2021 ftrack

from typing import Any, Dict, Optional
import os
import sys
import functools
import logging
import platform
import ftrack_api
import ftrack_api.session
import ftrack_api.entity.base
import ftrack_api.accessor.disk as _disk
import ftrack_api.structure.standard as _standard


logger: logging.Logger = logging.getLogger(
    'ftrack_user_location'
)




def configure_location(session: 'ftrack_api.session.Session', event: Dict[str, Any]) -> None:
    '''Listen.'''

    # provide a sanitised instance name to be used as folder
    server_folder_name: str = session.server_url.split(
        '//'
    )[-1].split('.')[0].replace('-', '_')

    # Default Disk mount point.
    DEFAULT_USER_DISK_PREFIX: str = os.path.join(
        os.path.expanduser('~'),
        'Documents',
        'local_ftrack_projects',
        server_folder_name
    )

    # Override environment variable for user location prefix
    USER_DISK_PREFIX: str = os.getenv(
        'FTRACK_USER_LOCTION_PATH',
        DEFAULT_USER_DISK_PREFIX
    )

    if not os.path.exists(USER_DISK_PREFIX):
        logger.info('Creating folder {}'.format(USER_DISK_PREFIX))
        os.makedirs(USER_DISK_PREFIX)

    logger.info('Using folder: {}'.format(os.path.abspath(USER_DISK_PREFIX)))

    hostname: str = platform.node()
    if platform.system() == 'Darwin' and hostname.endswith('.local'):
        hostname = hostname[:hostname.find('.local')]

    # Name of the location.
    DEFAULT_LOCATION_NAME: str = '{}.{}'.format(
        session.api_user,
        hostname
    )

    USER_LOCATION_NAME: str = os.getenv(
        'FTRACK_USER_LOCTION_NAME',
        DEFAULT_LOCATION_NAME
    )

    location: Optional['ftrack_api.entity.base.Entity'] = session.query('Location where name is "{}"'.format(USER_LOCATION_NAME)).first()
    if not location:
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

    location.accessor = _disk.DiskAccessor(
        prefix=USER_DISK_PREFIX
    )
    location.structure = _standard.StandardStructure()
    location.priority = 1-sys.maxsize

    logger.warning(
        'Registering Using location {0} @ {1} with priority {2}'.format(
            USER_LOCATION_NAME, USER_DISK_PREFIX, location.priority
        )
    )


def register(api_object: Any, **kw: Any) -> None:
    '''Register location with *session*.'''

    if not isinstance(api_object, ftrack_api.Session):
        return

    api_object.event_hub.subscribe(
        'topic=ftrack.api.session.configure-location',
        functools.partial(configure_location, api_object)
    )
