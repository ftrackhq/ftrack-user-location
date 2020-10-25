# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

import os
import sys
import logging

dependencies_directory = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'dependencies')
)
sys.path.append(dependencies_directory)

import ftrack_api
from ftrack_action_handler.action import BaseAction
from ftrack_freelancer_location import sync

logger = logging.getLogger('ftrack_freelancer_location.sync_action')


class SyncAction(BaseAction):

    name = 'ftrack sync tool'
    label = 'ftrack sync tool'
    identifier = 'ftrack.fsync'

    def __init__(self, session):
        super(SyncAction, self).__init__(session)
        self._location_data = {}
        self._sync_data = {}
        self._ignored_locations = [
            'ftrack.origin',
            'ftrack.server',
            'ftrack.unmanaged',
            'ftrack.connect',
            'ftrack.review'
        ]

    @property
    def variant(self):
        return 'Sync @ {}'.format(self.location['name'])

    @property
    def location(self):
        return self.session.pick_location()

    def get_locations(self, name=False):
        locations = self.session.query('select name from Location').all()
        if name:
            locations = [x['name'] for x in locations]
        return locations

    def get_current_location(self, name=False):
        location = self.location
        if name:
            location = location['name']
        return location

    def get_locations_menu(
            self, field_id, label=None,
            default_value=None, exclude_self=False, exclude_inaccessibles=False):

        location_menu = {
            'label': label,
            'type': 'enumerator',
            'name': field_id,
            'value': default_value or [],
            'data': []
        }

        locations = self.get_locations()

        if exclude_self:
            locations = [x for x in locations if not x['name'] == self.location['name']]

        # filter out ftrack locations from sync
        locations = [x for x in locations if x['name'] not in self._ignored_locations]

        if exclude_inaccessibles:
            # filter non accessible locations
            locations = [x for x in locations if x.accessor]

        locations = sorted(locations)

        for location in locations:

            item = {
                'label': location['name'],
                'value': location['name']
            }

            location_menu['data'].append(
                item
            )

        return location_menu

    def location_exists(self, location):
        return location in self.get_locations(name=True)

    def build_sync_event(self, event):
        source_location = event['data']['values']['source_location']
        dest_location = event['data']['values']['dest_location']

        if not self.location_exists(source_location):
            raise ValueError(
                'Source location {} does not exist'.format(source_location)
            )

        if not self.location_exists(dest_location):
            raise ValueError(
                'Destination location {} does not exist'.format(dest_location)
            )

        event['data']['actionIdentifier'] = 'syncto-{}'.format(dest_location)
        event['source']['location'] = self.location['name']
        event['target'] = {'location': dest_location}

        return event

    def get_locations_ui(self, event):

        menu = {'items': []}

        menu['items'].append(
            {
                'value': '## {} ##'.format(self.location['name']),
                'type': 'label'
            }
        )

        menu['items'].append(
            {
                'value':'Locations',
                'type': 'label'
            }
        )

        menu['items'].append(
            self.get_locations_menu(
                'source_location',
                label='Source',
                default_value=self.get_current_location(name=True),
                # exclude_inaccessibles=True
            )
        )

        menu['items'].append(
            self.get_locations_menu(
                'dest_location',
                label='Destination',
                exclude_self=True
            )
        )

        event.update(menu)
        return event

    def sync_here(self, event=None):

        try:
            sync.on_sync_to_destination(
                self.session,
                event['data']['locations']['sync'],
                event['data']['locations']['destination'],
                event['data']['components'],
                event['source']['user']
            )
        except Exception:
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': (
                    'Something failed,'
                    ' please check the logs'
                    )
            }
            raise

    def sync_there(self, event):
        try:
            _id = event['source']['id']
            source_location = event['data']['values']['source_location']
            dest_location = event['data']['values']['dest_location']

            sync.on_sync_to_remote(
                self.session,
                source_location,
                dest_location,
                event['source']['user']['id'],
                event['data'].get('selection', [])
            )
            self._location_data.pop(_id) if _id in self._location_data else None

        except Exception:
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': (
                    'Something failed,'
                    ' please check the logs'
                    )
            }
            raise

    def discover(self, session, entities, event):
        if not entities:
            return False

        entity_type, entity_id = entities[0]
        if entity_type != 'AssetVersion':
            return False

        return True

    def _discover(self, event):
        accepts = super(SyncAction, self)._discover(event)
        # add location to discovered item.

        if accepts:
            for item in accepts['items']:
                item['location'] = self.location['name']

        return accepts

    def launch(self, session, entities, event):
        self.logger.info("Sync action launched from location {}".format(self.location['name']))

        if 'values' not in event['data']:
            event = self.get_locations_ui(event)
            return event
        else:
            try:
                event = self.build_sync_event(event)
            except ValueError as e:
                return {
                    'success': False,
                    'message': e
                }

            event['data']['actionIdentifier'] = '{}-to-ftrack'.format(self.location['name'])
            self.session.event_hub.publish(event)

            return {
                'success': True,
                'message': 'Sync launched'
            }

    def register(self):
        # ensure session has been finishing to load and discovered locations.
        self.session.event_hub.subscribe(
            'topic=ftrack.api.session.ready',
            self._register
        )

    def _register(self, event):
        # discover action
        self.session.event_hub.subscribe(
            'topic=ftrack.action.discover',
            self._discover
        )

        # launch action
        self.session.event_hub.subscribe(
            'topic=ftrack.action.launch and data.actionIdentifier={0}'
            ' and data.location="{1}"'.format(
                self.identifier,
                self.location['name']
            ),
            self._launch
        )

        # register event for every accessible location
        for location in self.get_locations():
            if location.accessor:
                # listen to transfer events.
                self.session.event_hub.subscribe(
                    'data.actionIdentifier={0}-to-ftrack'.format(location['name']),
                    self.sync_there
                )

                self.session.event_hub.subscribe(
                    'topic=ftrack.sync and data.actionIdentifier=ftrack-to-{0}'.format(location['name']),
                    self.sync_here
                )


def register(session, **kwargs):

    # Validate that session is an instance of ftrack_api.Session. If not,
    # assume that register is being called from an incompatible API
    # and return without doing anything.
    if not isinstance(session, ftrack_api.Session):
        return

    action = SyncAction(session)
    action.register()
