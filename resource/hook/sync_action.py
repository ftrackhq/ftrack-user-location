# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

import os
import sys
import logging

# Add dependencies directory to path so we can import ftrack_user_location
dependencies_directory = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'dependencies')
)
sys.path.append(dependencies_directory)

import ftrack_api
from ftrack_action_handler.action import AdvancedBaseAction

from ftrack_user_location import sync
from ftrack_user_location.configure_logging import configure_logging

# Ensure logging is configured for this hook
# (hooks run outside the package __init__, so configure explicitly)
configure_logging('ftrack_user_location', level=logging.DEBUG)

logger = logging.getLogger(
    'ftrack_user_location.SyncAction'
)


class SyncAction(AdvancedBaseAction):
    """Sync action for transferring components between locations.

    Migrated to AdvancedBaseAction for:
    - Automatic entity type filtering (allowed_types)
    - Built-in permission checking
    - Standard ftrack action patterns
    """

    # Action metadata
    label = 'ftrack sync tool'
    identifier = 'ftrack.fsync'
    description = 'Sync components between user locations and ftrack.server'

    # Entity filtering - show action for AssetVersions and FileComponents
    # Session user filter in discover() prevents duplicates when multiple
    # users have Connect running
    allowed_types = ['AssetVersion', 'FileComponent']

    # Allow empty context for testing
    allow_empty_context = False

    def __init__(self, session):
        super(SyncAction, self).__init__(session)
        self._location_data = {}
        self._sync_data = {}
        # Locations to exclude from sync UI
        # Note: ftrack.server is NOT excluded - it's a valid source/destination
        self._ignored_locations = [
            'ftrack.origin',
            'ftrack.unmanaged',
            'ftrack.connect',
            'ftrack.review'
        ]

        # Note: Cannot log location name here as session.types is not yet initialized
        # Location logging happens in _register() when session is fully ready

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

    def check_remote_location_online(self, location_name, timeout=2.0):
        """Check if a remote location is online by pinging via event.

        Args:
            location_name: Name of the location to check
            timeout: Seconds to wait for response

        Returns:
            bool: True if location responds, False otherwise
        """
        import threading

        # Create a response tracker
        response_received = {'value': False}
        response_event = threading.Event()

        def handle_pong(event):
            """Handle the pong response."""
            if event['data'].get('location') == location_name:
                response_received['value'] = True
                response_event.set()
                return True

        # Subscribe to pong responses
        pong_topic = f'topic=ftrack.location.ping.response.{location_name}'
        self.session.event_hub.subscribe(pong_topic, handle_pong)

        try:
            # Publish ping event
            ping_event = {
                'topic': f'ftrack.location.ping.{location_name}',
                'source': {},  # Event hub will populate with connection ID
                'data': {
                    'location': location_name,
                    'requestor': self.location['name']
                }
            }
            self.session.event_hub.publish(ping_event)

            # Wait for response with timeout
            response_event.wait(timeout=timeout)

            return response_received['value']

        finally:
            # Unsubscribe to avoid leaks (pass callback to match specific subscription)
            try:
                self.session.event_hub.unsubscribe(pong_topic, handle_pong)
            except Exception as e:
                self.logger.debug(f"[check_remote_location_online] Unsubscribe cleanup error: {e}")

    def get_locations_menu(
            self, field_id, label=None,
            default_value=None, exclude_self=False, exclude_inaccessibles=False,
            filter_by_availability=None):
        """Build location dropdown menu.

        Args:
            field_id: Form field ID
            label: Field label
            default_value: Default selected value
            exclude_self: Exclude current location
            exclude_inaccessibles: Exclude locations without accessor
            filter_by_availability: Dict of {location_name: (available, total)}
                                   Only show locations with available > 0

        Returns:
            dict: Form field definition
        """
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

        # Filter by component availability (for source location dropdown)
        # Don't filter out remote locations - show them with availability indicator
        if filter_by_availability is not None:
            # Only include locations we know about
            locations = [
                x for x in locations
                if x['name'] in filter_by_availability
            ]

        locations = sorted(locations, key=lambda x: x['name'], reverse=True)

        for location in locations:
            # Show online status indicator
            # [ONLINE] = accessible (has accessor) or ping responds
            # [OFFLINE] = no accessor and no ping response
            if location.accessor:
                # Has accessor on this machine
                status = '[ONLINE]'
            elif location['name'] == 'ftrack.server':
                # ftrack.server is always online
                status = '[ONLINE]'
            else:
                # Remote location - check via ping
                is_online = self.check_remote_location_online(location['name'])
                status = '[ONLINE]' if is_online else '[OFFLINE]'
                self.logger.debug(
                    f"[get_locations_menu] Remote location {location['name']} "
                    f"ping check: {'online' if is_online else 'offline'}"
                )

            # Add availability info if filtering by components
            availability_info = ''
            if filter_by_availability and location['name'] in filter_by_availability:
                available, total, can_check = filter_by_availability[location['name']]

                if can_check:
                    # We verified availability on this machine
                    percentage = (available / total * 100) if total > 0 else 0
                    availability_info = ' ({}/{} - {:.0f}%)'.format(available, total, percentage)
                else:
                    # Remote location - can't verify from here
                    availability_info = ' ({} components - availability unknown)'.format(total)

            item = {
                'label': '{} {}{}'.format(status, location['name'], availability_info),
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

        # Prevent syncing to same location
        if source_location == dest_location:
            raise ValueError(
                'Source and destination cannot be the same location. '
                'Please select different locations to sync.'
            )

        event['data']['actionIdentifier'] = 'syncto-{}'.format(dest_location)
        event['source']['location'] = self.location['name']
        event['target'] = {'location': dest_location}

        return event

    def get_component_locations(self, components):
        """Get locations where components are available.

        Args:
            components: List of component entities or IDs

        Returns:
            dict: {location_name: (available_count, total_count, can_check)}
            where can_check indicates if we could actually verify availability
        """
        location_availability = {}

        for location in self.get_locations():
            location_name = location['name']
            if location_name in self._ignored_locations:
                continue

            # Check if we can verify availability on this machine
            can_check = location.accessor is not None

            available = 0
            total = len(components)

            if can_check:
                # We can check availability (local location or ftrack.server)
                for component in components:
                    # Handle different component formats:
                    # - FileComponent entity object (from version['components'])
                    # - Dict with 'id' key
                    # - String ID

                    if hasattr(component, 'entity_type'):
                        # It's already a FileComponent entity
                        component_entity = component
                    elif isinstance(component, dict):
                        # It's a dict, get the ID
                        comp_id = component.get('id')
                        component_entity = self.session.get('FileComponent', comp_id)
                    elif isinstance(component, str):
                        # It's a string ID
                        component_entity = self.session.get('FileComponent', component)
                    else:
                        # Unknown format, skip
                        self.logger.warning(
                            f"[get_component_locations] Unknown component format: {type(component)}"
                        )
                        continue

                    if not component_entity:
                        continue

                    try:
                        availability = location.get_component_availability(component_entity)
                        if availability == 100.0:
                            available += 1
                    except Exception as e:
                        self.logger.debug(
                            f"[get_component_locations] Error checking {location_name} "
                            f"for component {component_entity['id']}: {e}"
                        )
            else:
                # Remote location - can't check from this machine
                # Assume components might be there (will be verified by remote machine)
                self.logger.debug(
                    f"[get_component_locations] {location_name} is remote - "
                    f"cannot verify availability from this machine"
                )

            # Include all locations:
            # - Locations we can check: show actual availability
            # - Remote locations: show as unknown but available for selection
            location_availability[location_name] = (available, total, can_check)

        return location_availability

    def get_locations_ui(self, event):
        # Get selected entities to determine available locations
        selection = event.get('data', {}).get('selection', [])

        # Extract components from selection
        components = []
        for item in selection:
            entity_type = item.get('entityType') or item.get('entity_type')
            entity_id = item.get('entityId') or item.get('entity_id')

            try:
                entity_type = self._get_entity_type(item)
            except (ValueError, KeyError):
                continue

            if entity_type == 'AssetVersion':
                # Get all components for this asset version
                version = self.session.get('AssetVersion', entity_id)
                if version:
                    components.extend(version.get('components', []))
            elif entity_type == 'FileComponent':
                # Direct component selection
                components.append(entity_id)

        # Get location availability for these components
        location_availability = self.get_component_locations(components)

        menu = {
            'type': 'form',
            'items': [],
            'title': 'Sync Tool - {} component(s) selected'.format(len(components)),
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

        # Pass location availability to filter source locations
        menu['items'].append(
            self.get_locations_menu(
                'source_location',
                label='Source',
                default_value=self.get_current_location(name=True),
                filter_by_availability=location_availability
            )
        )

        menu['items'].append(
            self.get_locations_menu(
                'dest_location',
                label='Destination',
                filter_by_availability=None  # Show all for destination
            )
        )

        event.update(menu)
        return event

    def handle_ping(self, event):
        """Respond to ping requests to indicate this location is online.

        Args:
            event: The ping event

        Returns:
            dict: Pong response
        """
        location_name = event['data'].get('location')
        requestor = event['data'].get('requestor')

        self.logger.debug(
            f"[handle_ping] Received ping from {requestor} for {location_name}"
        )

        # Respond with pong
        pong_topic = f'ftrack.location.ping.response.{location_name}'
        pong_event = {
            'topic': pong_topic,
            'source': {},  # Event hub will populate with connection ID
            'data': {
                'location': location_name,
                'online': True,
                'requestor': requestor
            }
        }
        self.session.event_hub.publish(pong_event)

        self.logger.debug(
            f"[handle_ping] Sent pong response to {requestor}"
        )

        return {'success': True}

    def sync_here(self, event=None):
        """Handle ftrack.sync event - downloads FROM ftrack.server TO local."""
        self.logger.info(
            f"[sync_here] Received ftrack.sync event "
            f"[actionIdentifier={event['data'].get('actionIdentifier')}, "
            f"location={self.location['name']}]"
        )
        self.logger.debug(f"[sync_here] Event data: {event['data']}")

        try:
            source_id = event['data']['locations']['sync']
            dest_id = event['data']['locations']['destination']
            components = event['data']['components']
            user_id = event['source']['user']['id']

            # Debug: Log location IDs to diagnose report issue
            self.logger.info(
                f"[sync_here] Location IDs: source_id={source_id}, dest_id={dest_id}"
            )

            self.logger.info(
                f"[sync_here] Starting sync: ftrack.server → {self.location['name']} "
                f"[components={len(components)}, user={user_id}]"
            )

            sync.on_sync_to_destination(
                self.session,
                source_id,
                dest_id,
                components,
                user_id
            )

            self.logger.info(f"[sync_here] Sync completed successfully")
            return {
                'success': True,
                'message': 'Sync completed'
            }
        except Exception as error:
            import traceback
            self.logger.error(f"[sync_here] Sync failed: {error}")
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': (
                    'Something failed,'
                    ' please check the logs'
                    )
            }

    def sync_there(self, event):
        """Handle {location}-to-ftrack event - uploads FROM local TO ftrack.server."""
        action_id = event['data'].get('actionIdentifier', 'unknown')
        self.logger.info(
            f"[sync_there] Received sync event "
            f"[actionIdentifier={action_id}, location={self.location['name']}]"
        )
        self.logger.debug(f"[sync_there] Event data: {event['data']}")

        try:
            _id = event['source']['id']
            source_location = event['data']['values']['source_location']
            dest_location = event['data']['values']['dest_location']
            # Use AdvancedBaseAction's selection extraction pattern
            selection = self._get_selection_(event)
            user_id = event['source']['user']['id']

            self.logger.info(
                f"[sync_there] Starting sync: {source_location} → {dest_location} "
                f"[asset_versions={len(selection)}, user={user_id}]"
            )

            # Verify this is the right machine to handle this event
            if source_location != self.location['name']:
                self.logger.warning(
                    f"[sync_there] Event routing mismatch! "
                    f"This machine has location '{self.location['name']}' "
                    f"but event is for '{source_location}'. This should not happen!"
                )

            sync.on_sync_to_remote(
                self.session,
                source_location,
                dest_location,
                user_id,
                selection
            )
            self._location_data.pop(_id) if _id in self._location_data else None

            self.logger.info(f"[sync_there] Sync completed successfully")
            return {
                'success': True,
                'message': 'Sync completed'
            }

        except Exception as error:
            import traceback
            self.logger.error(f"[sync_there] Sync failed: {error}")
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': (
                    'Something failed,'
                    ' please check the logs'
                    )
            }

    def discover(self, session, entities, event):
        """Return True if action should be discoverable.

        Note: AdvancedBaseAction already filtered by allowed_types=['AssetVersion'],
        so we only get AssetVersion entities here.

        Only show action for the current session user to avoid duplicates when
        multiple users have Connect running.
        """
        if not entities:
            self.logger.debug("[discover] No entities selected, not discoverable")
            return False

        # Only show action for the current session user (user running this Connect)
        event_user = event.get('source', {}).get('user', {}).get('username')
        session_user = session.api_user

        if event_user and event_user != session_user:
            self.logger.debug(
                f"[discover] Action not discoverable - event from different user "
                f"[event_user={event_user}, session_user={session_user}]"
            )
            return False

        self.logger.debug(
            f"[discover] Action discoverable for {len(entities)} AssetVersion(s) "
            f"[user={session_user}]"
        )
        return True

    def _discover(self, event):
        """Override to add location to discovered action items."""
        accepts = super(SyncAction, self)._discover(event)

        # Add location to discovered item so UI knows which machine this action is from
        if accepts:
            for item in accepts['items']:
                item['location'] = self.location['name']
                self.logger.debug(
                    f"[_discover] Action discovered for location: {self.location['name']}"
                )

        return accepts

    def check_components_availability(self, components, location_name):
        """Check how many components are available in a location.

        Args:
            components: List of component dicts with 'entityId' and 'entityType'
            location_name: Name of location to check

        Returns:
            tuple: (available_count, total_count, available_component_ids)
        """
        location = self.session.query(
            f'Location where name is "{location_name}"'
        ).first()

        if not location:
            self.logger.warning(
                f"[check_availability] Location not found: {location_name}"
            )
            return 0, 0, []

        available_ids = []
        total = 0

        for item in components:
            # Use BaseAction's _get_entity_type() to translate entity type properly
            # This handles 'assetversion' → 'AssetVersion' and other schema lookups
            try:
                entity_type = self._get_entity_type(item)
            except (ValueError, KeyError) as e:
                self.logger.warning(
                    f"[check_availability] Could not determine entity type for item: {item}, error: {e}"
                )
                continue

            entity_id = item.get('entity_id') or item.get('entityId')
            if not entity_id:
                self.logger.warning(
                    f"[check_availability] No entity ID in selection: {item}"
                )
                continue

            entity = self.session.get(entity_type, entity_id)
            if entity and entity.entity_type == 'AssetVersion':
                for component in entity.get('components', []):
                    total += 1
                    if 'ftrackreview' in component['name']:
                        continue

                    try:
                        availability = location.get_component_availability(component)
                        if availability == 100.0:
                            available_ids.append(component['id'])
                    except Exception as e:
                        self.logger.debug(
                            f"[check_availability] Error checking component "
                            f"{component['name']}: {e}"
                        )

        return len(available_ids), total, available_ids

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
                    'message': str(e)
                }

            source_location = event['data']['values']['source_location']
            dest_location = event['data']['values']['dest_location']
            # Use AdvancedBaseAction's selection extraction pattern
            selection = self._get_selection_(event)

            # SMART SYNC: Check if components already available in ftrack.server
            # This allows sync even if remote machine is offline
            if source_location != 'ftrack.server' and source_location != self.location['name']:
                self.logger.info(
                    f"[launch] Smart sync: Checking ftrack.server availability first "
                    f"(source={source_location}, requesting_machine={self.location['name']})"
                )

                available, total, available_ids = self.check_components_availability(
                    selection, 'ftrack.server'
                )

                self.logger.info(
                    f"[launch] ftrack.server has {available}/{total} components available "
                    f"({available/total*100:.1f}% if total > 0 else 0)"
                )

                if available == total and total > 0:
                    # ALL components available in ftrack.server - sync directly!
                    self.logger.info(
                        f"[launch] ✅ All components available in ftrack.server - "
                        f"syncing directly (remote machine not needed)"
                    )

                    # Trigger direct sync from ftrack.server to local
                    sync.on_sync_to_destination(
                        self.session,
                        self.session.query('Location where name is "ftrack.server"').first()['id'],
                        self.location['id'],
                        [{'id': cid} for cid in available_ids],
                        event['source']['user']['id']
                    )

                    return {
                        'success': True,
                        'message': (
                            f'Synced {available} components from ftrack.server to '
                            f'{self.location["name"]} (remote machine not needed)'
                        )
                    }

                elif available > 0:
                    # PARTIAL availability - sync available ones now, request missing ones
                    self.logger.info(
                        f"[launch] ⚠️ Partial availability: {available}/{total} components "
                        f"in ftrack.server. Syncing available components now, "
                        f"then requesting missing from remote machine."
                    )

                    # Sync available components immediately
                    sync.on_sync_to_destination(
                        self.session,
                        self.session.query('Location where name is "ftrack.server"').first()['id'],
                        self.location['id'],
                        [{'id': cid} for cid in available_ids],
                        event['source']['user']['id']
                    )

                    # Publish event for remote machine to upload missing components
                    event['data']['actionIdentifier'] = '{}-to-ftrack'.format(source_location)
                    self.logger.info(
                        f"[launch] Publishing event to remote machine for missing "
                        f"{total - available} components"
                    )
                    self.session.event_hub.publish(event)

                    return {
                        'success': True,
                        'message': (
                            f'Synced {available} components from ftrack.server. '
                            f'Requested {total - available} missing components from '
                            f'remote machine.'
                        )
                    }

                else:
                    # NO components in ftrack.server - must use remote machine
                    self.logger.info(
                        f"[launch] ❌ No components in ftrack.server - "
                        f"must request from remote machine {source_location}"
                    )

            # Standard event-based sync (remote machine or local location)
            event['data']['actionIdentifier'] = '{}-to-ftrack'.format(source_location)
            self.logger.info(
                f"Publishing sync event: {source_location} → ftrack.server "
                f"(triggered by {self.location['name']})"
            )
            self.session.event_hub.publish(event)

            return {
                'success': True,
                'message': f'Sync request published: {source_location} → ftrack.server (will be executed by remote machine)'
            }

    def register(self):
        # ensure session has been finishing to load and discovered locations.
        self.session.event_hub.subscribe(
            'topic=ftrack.api.session.ready',
            self._register
        )

    def _register(self, event):
        self.logger.info(
            f"[_register] Registering sync action for location: {self.location['name']}"
        )

        # discover action
        self.session.event_hub.subscribe(
            'topic=ftrack.action.discover',
            self._discover
        )
        self.logger.debug("[_register] Subscribed to: topic=ftrack.action.discover")

        # launch action
        launch_topic = (
            'topic=ftrack.action.launch and data.actionIdentifier={0}'
            ' and data.location="{1}"'.format(
                self.identifier,
                self.location['name']
            )
        )
        self.session.event_hub.subscribe(launch_topic, self._launch)
        self.logger.debug(f"[_register] Subscribed to: {launch_topic}")

        # register event for every accessible location
        accessible_locations = [loc for loc in self.get_locations() if loc.accessor]
        self.logger.info(
            f"[_register] Found {len(accessible_locations)} accessible locations "
            f"on this machine: {[loc['name'] for loc in accessible_locations]}"
        )

        # Subscribe to ping requests for this location's presence check
        ping_topic = f'topic=ftrack.location.ping.{self.location["name"]}'
        self.session.event_hub.subscribe(ping_topic, self.handle_ping)
        self.logger.info(
            f"[_register] Subscribed to PING requests: {ping_topic}"
        )

        for location in accessible_locations:
            # listen to transfer events: uploads FROM this location TO ftrack.server
            upload_topic = 'data.actionIdentifier={0}-to-ftrack'.format(location['name'])
            self.session.event_hub.subscribe(upload_topic, self.sync_there)
            self.logger.info(
                f"[_register] Subscribed to UPLOAD events: {upload_topic} "
                f"(will handle uploads from {location['name']})"
            )

            # listen to download events: downloads FROM ftrack.server TO this location
            download_topic = 'topic=ftrack.sync and data.actionIdentifier=ftrack-to-{0}'.format(location['name'])
            self.session.event_hub.subscribe(download_topic, self.sync_here)
            self.logger.info(
                f"[_register] Subscribed to DOWNLOAD events: {download_topic} "
                f"(will handle downloads to {location['name']})"
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