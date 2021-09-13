# :coding: utf-8
# :copyright: Copyright (c) 2014-2021 ftrack

import os
import sys
import functools
import logging
import getpass
import ftrack_api
import ftrack_api.accessor.disk as _disk
import ftrack_api.structure.standard as _standard


logger = logging.getLogger(
    'ftrack_user_location'
)

# Name of the location.
LOCATION_NAME = '{}.local'.format(getpass.getuser())

# Disk mount point.
DISK_PREFIX = os.path.join(
    os.path.expanduser('~'), 
    'Documents', 
    'local_ftrack_projects'
)

if not os.path.exists(DISK_PREFIX):
    os.makedirs(DISK_PREFIX)


def configure_location(session, event):
    '''Listen.'''
    location = session.ensure(
        'Location', 
        {
            'name': LOCATION_NAME
        }
    )

    location.accessor = _disk.DiskAccessor(
        prefix=DISK_PREFIX
    )
    location.structure = _standard.StandardStructure()
    location.priority = 1-sys.maxsize

    logger.warning(
        'Registering Using location {0} @ {1} with priority {2}'.format(
            LOCATION_NAME, DISK_PREFIX, location.priority
        )
    )


def register(api_object, **kw):
    '''Register location with *session*.'''

    if not isinstance(api_object, ftrack_api.Session):
        return

    if not os.path.exists(DISK_PREFIX) or not os.path.isdir(DISK_PREFIX):
        logger.error('Disk prefix {} does not exist.'.format(DISK_PREFIX))
        return

    api_object.event_hub.subscribe(
        'topic=ftrack.api.session.configure-location',
        functools.partial(configure_location, api_object)
    )
