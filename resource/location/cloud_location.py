# :coding: utf-8
# :copyright: Copyright (c) 2014-2020 ftrack

import os
import sys
import logging
import functools
import platform
from types import MethodType

dependencies_directory = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'dependencies')
)
sys.path.append(dependencies_directory)

import boto3
import ftrack_api
import ftrack_api.structure.standard
from ftrack_s3_accessor.s3 import S3Accessor

# Mandatory environment variables.
AWS_ACCESS_KEY = os.getenv('FTRACK_USER_SYNC_LOCATION_AWS_ID')
AWS_SECRET_KEY = os.getenv('FTRACK_USER_SYNC_LOCATION_AWS_KEY')

# Bucket name used for sync, this should be existing before hand.
FTRACK_SYNC_BUCKET = os.getenv('FTRACK_USER_SYNC_LOCATION_BUCKET_NAME')

if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
    raise ValueError(
        'AWS credentials (FTRACK_USER_SYNC_LOCATION_AWS_ID, FTRACK_USER_SYNC_LOCATION_AWS_KEY)'
        ' missing from environment variables.'
    )

os.environ['AWS_ACCESS_KEY_ID'] = AWS_ACCESS_KEY
os.environ['AWS_SECRET_ACCESS_KEY'] = AWS_SECRET_KEY


if not FTRACK_SYNC_BUCKET:
    raise ValueError(
        'No FTRACK_USER_SYNC_LOCATION_BUCKET_NAME name found in environment variables.'
    )


logging.info('ftrack Sync bucket set to : {}'.format(FTRACK_SYNC_BUCKET))


SYNC_LOCATION_PRIORITY = os.getenv(
    'FTRACK_USER_SYNC_LOCATION_PRIORITY',
    1000
)


def get_url(self, resource_identifier=None):
    '''Return url for *resource_identifier*.'''
    print('args: {} {}'.format(self, resource_identifier))
    s3_object = self.bucket.Object(resource_identifier)
    location = boto3.client('s3').get_bucket_location(Bucket=self._bucket)['LocationConstraint']
    url = "https://s3-{}.amazonaws.com/{}/{}".format(location, self._bucket, s3_object.key)
    print('URL: {}'.format(url))
    return url


S3Accessor.get_url = MethodType(get_url, S3Accessor)


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

    accessor = S3Accessor(FTRACK_SYNC_BUCKET)
    my_location.accessor = accessor

    # Set priority.
    my_location.priority = int(SYNC_LOCATION_PRIORITY)


def register(api_object):
    '''Register plugin with *api_object*.'''

    # Validate that session is an instance of ftrack_api.Session. If not, assume
    # that register is being called from an old or incompatible API and return
    # without doing anything.
    if not isinstance(api_object, ftrack_api.Session):
        logging.debug(
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