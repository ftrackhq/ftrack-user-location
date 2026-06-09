# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

import os
import sys
import logging

dependencies_directory = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'dependencies')
)

sys.path.append(dependencies_directory)



import ftrack_api
from ftrack_action_handler.action import BaseAction
from ftrack_user_location import sync


logger = logging.getLogger(
    'ftrack_user_location.SyncAction'
)


class SyncAction(BaseAction):

    name = 'ftrack sync tool'
    label = 'ftrack sync tool'
    identifier = 'ftrack.fsync'

    def __init__(self, session):
        super(SyncAction, self).__init__(session)
        self._location_data = {}
        self._sync_data = {}
        # Locations to exclude from sync dropdown
        # Include ftrack.server as it's the primary sync target
        # Exclude only internal/system locations
        self._ignored_locations = [
            'ftrack.origin',     # Original file location (not a sync target)
            'ftrack.unmanaged',  # Unmanaged files
            'ftrack.connect',    # Connect internal location
            'ftrack.review'      # Review proxy location
        ]

        # Cache current user ID to avoid querying on every discovery event
        self._current_user_id = self.session.query(
            'User where username is "{}"'.format(self.session.api_user)
        ).first()['id']

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
        '''Build location dropdown menu for sync action.

        Shows:
        - User locations (e.g., username.hostname)
        - ftrack.server (primary sync target)

        Excludes:
        - Internal ftrack locations (origin, unmanaged, connect, review)
        - Self location if exclude_self=True
        - Inaccessible locations if exclude_inaccessibles=True
        '''
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

        # Filter out internal ftrack locations (but keep ftrack.server for sync)
        locations = [x for x in locations if x['name'] not in self._ignored_locations]

        if exclude_inaccessibles:
            # Filter non-accessible locations
            locations = [x for x in locations if x.accessor]

        locations = sorted(locations, key=lambda x: x['name'], reverse=True)


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
        '''Build sync event with comprehensive validation.

        Args:
            event (dict): Action event with form values

        Returns:
            dict: Modified event with sync parameters

        Raises:
            ValueError: If validation fails
        '''
        values = event['data'].get('values', {})

        source_location = values.get('source_location')
        dest_location = values.get('dest_location')

        # Validate required fields
        if not source_location:
            raise ValueError('Source location is required')
        if not dest_location:
            raise ValueError('Destination location is required')

        # Prevent self-sync
        if source_location == dest_location:
            raise ValueError('Source and destination must be different')

        # Validate locations exist
        if not self.location_exists(source_location):
            raise ValueError(
                'Source location "{}" does not exist'.format(source_location)
            )

        if not self.location_exists(dest_location):
            raise ValueError(
                'Destination location "{}" does not exist'.format(dest_location)
            )

        # Build event
        event['data']['actionIdentifier'] = 'syncto-{}'.format(dest_location)
        event['source']['location'] = self.location['name']
        event['target'] = {'location': dest_location}

        return event

    def get_locations_ui(self, event):
        menu = {
            'type': 'form',
            'items': [],
            'title': 'Sync Tool',
            'submit_button_label': 'Sync'
        }

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
                #exclude_self=True
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
        '''Discover action only for current user to prevent duplicates.

        When multiple users run ftrack Connect, each registers their own
        action handler. We filter by matching the event source user with
        the current session user to ensure only one action appears per user.
        '''
        if not entities:
            return False

        entity_type, entity_id = entities[0]
        if entity_type != 'AssetVersion':
            return False

        # Only respond to discovery from the same user that registered this action
        # This prevents multiple action instances appearing when multiple users
        # are running ftrack Connect simultaneously
        event_user_id = event.get('source', {}).get('user', {}).get('id')

        if event_user_id and event_user_id != self._current_user_id:
            # This discovery event is from a different user's Connect instance
            # Don't respond to prevent duplicate actions in UI
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
        '''Launch sync action with comprehensive error handling.

        Args:
            session: ftrack API session
            entities: Selected entities
            event: Action event

        Returns:
            dict: Success/failure message or form UI
        '''
        self.logger.info(
            "Sync action launched from location {}".format(self.location['name'])
        )

        if 'values' not in event['data']:
            # Show form
            event = self.get_locations_ui(event)
            return event
        else:
            try:
                event = self.build_sync_event(event)
            except ValueError as e:
                self.logger.warning('Validation error: {}'.format(e))
                return {
                    'success': False,
                    'message': str(e)
                }
            except Exception as e:
                self.logger.error('Unexpected error building sync event: {}'.format(e))
                import traceback
                self.logger.error(traceback.format_exc())
                return {
                    'success': False,
                    'message': 'An unexpected error occurred. Please check logs.'
                }

            # Publish event
            try:
                event['data']['actionIdentifier'] = '{}-to-ftrack'.format(
                    self.location['name']
                )
                self.session.event_hub.publish(event)

                return {
                    'success': True,
                    'message': 'Sync launched successfully'
                }
            except Exception as e:
                self.logger.error('Failed to publish sync event: {}'.format(e))
                import traceback
                self.logger.error(traceback.format_exc())
                return {
                    'success': False,
                    'message': 'Failed to launch sync. Please try again.'
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


def register(api_object, **kwargs):
    # Validate that session is an instance of ftrack_api.Session. If not,
    # assume that register is being called from an incompatible API
    # and return without doing anything.
    if not isinstance(api_object, ftrack_api.Session):
        return

    action = SyncAction(api_object)
    logger.info('Registering : {}'.format(api_object))
    action.register()