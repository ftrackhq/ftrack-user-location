''':copyright: Copyright (c) 2015 EfestoLab'''

import os
import sys
import imp
from pprint import pformat
import ftrack


# Init paths to dependencies.
_this_dir = os.path.abspath(os.path.dirname(__file__))
_actionutils_path = os.path.join(_this_dir, "..", "..", "..", "efesto-ftrack-base", "efesto-ftrack-config", "source", "efesto_ftrack_config", "actionutils.py")
_configutils_path = os.path.join(_this_dir, "..", "..", "..", "efesto-ftrack-base", "efesto-ftrack-config", "source", "efesto_ftrack_config", "configutils.py")
_sync_module_path = os.path.normpath(os.path.join(_this_dir, "..", "..", "source"))

class Sync(ftrack.Action):
    debug = False

    name = 'efesto_fsync'
    label = 'Efesto Lab'
    identifier = 'efesto_fsync'
    variant = 'Sync To...'

    ALLOWED_ROLES = ['Administrator']
    ALLOWED_GROUPS = None
    IGNORED_TYPES = None
    ALLOWED_TYPES = ['AssetVersion']
    LIMIT_TO_USER = True

    DEFAULT_LOGO = {
        'standard': 'http://www.efestolab.uk/icons/efesto_logo.png',
        'debug': 'http://www.efestolab.uk/icons/efesto_logo_debug.png'
    }
    LOGO = None

    location = None
    location_data = {}
    sync_data = {}

    logger = None

    def __init__(self):
        super(Sync, self).__init__()

    @property
    def identifier(self):
        return 'efesto.%s' % self.name

    def is_debug(self):
        ''':returns: Whether the action is of debug type.
        :rtype: bool'''

        return self.debug

    def get_selection(self, event):
        '''From a raw event dictionary, extract the selected entities.

        :param event: Raw ftrack event
        :type event: dict
        :returns: List of entity dictionaries
        :rtype: List of dict'''

        data = event['data']
        selection = data.get('selection', [])
        seleted_items = ', '.join([s.get('entityId') for s in selection])
        return selection

    def get_user(self, event):
        '''From a raw event dictionary, extract the source user.

        :param event: Raw ftrack event
        :type event: dict
        :returns: Id of the user.
        :rtype: str'''
        return event['source']['user']['username']

    def check_permissions(self, user):
        '''Checks that the specified user has the permissions set in
        ``ALLOWED_GROUPS`` and ``ALLOWED_ROLES``.

        :param user: Id of the desired user to check permissions.
        :type user: str
        :returns: Whether the specified user has permissions or not.
        :rtype: bool'''

        group_valid = True
        role_valid = True

        if not self.ALLOWED_ROLES and not self.ALLOWED_GROUPS:
            return True
        fuser = ftrack.User(user)

        if self.ALLOWED_GROUPS:
            group_users = []
            for group in ftrack.getGroups():
                if group.dict.get('name') not in self.ALLOWED_GROUPS:
                    continue
                for member in group.getMembers():
                    group_users.append(member)
            group_users = [x.getUsername() for x in group_users]
            if fuser.getUsername() not in group_users:
                group_valid = False

        if self.ALLOWED_ROLES:
            _roles = []
            roles = [r.getName() for r in fuser.getRoles()]
            for role in roles:
                _roles.append(role in self.ALLOWED_ROLES)
            role_valid = any(_roles)
        return group_valid and role_valid

    def get_logo(self):
        ''':returns: URL to the efesto logo.
        :rtype: str
        '''
        if self.LOGO:
            return self.LOGO
        if not self.debug:
            key = 'standard'
        else:
            key = 'debug'

        return self.DEFAULT_LOGO.get(key, '')

    def get_locations(self, name=False):
        locations = ftrack.getLocations(True, False)
        if name:
            locations = [x.getName() for x in locations]
        return locations

    def get_current_location(self, name=False):
        location = ftrack.pickLocation()
        if name:
            location = location.getName()
        return location

    def get_locations_menu(
            self, field_id, label=None,
            default_value=None, exclude_self=False):

        from efesto_futils.ftracktools import webui

        location_menu = webui.combo_box(
            label=label,
            field_id=field_id,
            value=default_value or 'Please specify a location'
        )

        locations = self.get_locations(name=True)
        if exclude_self:
            self_loc = self.location
            locations = [x for x in locations if not x == self_loc]

        # filter out ftrack locations from sync
        locations = [x for x in locations if not x.startswith('ftrack')]
        locations = sorted(locations)

        for location in locations:
            location_menu['data'].append(
                webui.combo_box_item(
                    label=location,
                    value=location
                )
            )
        return location_menu

    def location_exists(self, location):
        return location in [x.getName() for x in ftrack.getLocations()]

    def build_sync_event(self, event):
        source_location = event['data']['values']['source_location']
        dest_location = event['data']['values']['dest_location']

        if not self.location_exists(source_location):
            raise ValueError(
                'Source location %s does not exist' % source_location
            )
        if not self.location_exists(dest_location):
            raise ValueError(
                'Destination location %s does not exist' % dest_location
            )

        sync_event = event.copy()
        sync_event['data']['actionIdentifier'] = 'syncto-%s' % dest_location
        sync_event['source']['location'] = self.location
        sync_event['target'] = {'location': dest_location}

        self.logger.debug("Built sync event %s" % sync_event)
        return sync_event

    def get_locations_ui(self, event):
        from efesto_futils.ftracktools import webui

        menu = {'items': []}
        items = []
        items.append(webui.label('## %s ##' % self.location))
        items.append(webui.label('## Locations ##'))

        items.append(
            self.get_locations_menu(
                'source_location',
                label='Source',
                default_value=self.get_current_location(name=True)
            )
        )

        items.append(
            self.get_locations_menu(
                'dest_location',
                label='Destination',
                exclude_self=True
            )
        )

        menu['items'] = items
        event.update(menu)
        return event

    @staticmethod
    def bytes_to_mb(value):
        return value/1024.0/1024.0

    @staticmethod
    def htm_tab(amount=4):
        return '&nbsp;'*amount

    def get_review_ui(self, event):
        from efesto_futils.ftracktools import webui

        _id = event['source']['id']

        menu = {'items': []}

        items = []

        items.append(webui.label('## Sync Review ##'))

        locations = event['data']['values']

        items.append(
            webui.label('**%s** to **%s**' % (
                locations['source_location'], locations['dest_location'])
            )
        )

        items.append(webui.label('## Asset Review ##'))

        data = self.sync_data.get(_id, {})

        total = 0.0
        if data:
            for key, val in sorted(data.items(), key=lambda x: x[0]):
                items.append(webui.label('### %s' % key))
                for comp in val:
                    total += comp['size']

                    size = self.bytes_to_mb(comp['size'])

                    name = '%s%s: %f MB'
                    name = name % (self.htm_tab(12), comp['name'], size)

                    items.append(webui.label(name))
            items.append(webui.label(''))

            total_str = '**Total data**: %fMB' % self.bytes_to_mb(total)
            items.append(webui.label(total_str))

        else:
            items.append(
                webui.label('Detailed asset information is not available.')
            )

        menu['items'] = items

        event.update(menu)

        return event

    def sync_here(self, event=None):
        try:
            sync.on_syncToDestination(
                event['data']['locations']['sync'],
                event['data']['locations']['destination'],
                event['data']['components'],
                event['source']['user']
            )
        except Exception:
            self.logger.error(" event:\n"+pformat(args[1]))
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
            user_id = self.get_user(event)
            selection = self.get_selection(event)
            sync.on_syncToRemote(
                source_location,
                dest_location,
                user_id,
                selection
            )
            self.location_data.pop(_id) if _id in self.location_data else None
        except Exception:
            self.logger.error(" event:\n"+pformat(args[1]))
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

    def discover(self, event):
        print "Discovering Sync action..."
        results = super(Sync, self).discover(event)

        for item in results['items']:
            item['location'] = self.location
            item['icon'] = self.get_logo()

        return results

    def launch(self, event):
        print "Launching Sync action..."

        actionutils = imp.load_source('actionutils', _actionutils_path)

        with actionutils.PythonPathActionHelper() as path_helper:
            if not self.logger:
                self.logger = path_helper.init_logger(__name__)

            self.logger.debug("Sync action launched, location = %s" % self.location)

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
                event['data']['actionIdentifier'] = '%s-to-s3' % self.location
                ftrack.EVENT_HUB.publish(event)

                return {
                    'success': True,
                    'message': 'Sync launched'
                }

    def register(self):
        env_loc = str(os.getenv('STUDIO'))+'.'+str(os.getenv('SITE'))

        if env_loc == self.location:
            ftrack.EVENT_HUB.subscribe(
                'topic=ftrack.action.discover',
                self.discover
            )
            ftrack.EVENT_HUB.subscribe(
                'topic=ftrack.action.launch and data.actionIdentifier={0}'
                ' and data.location={1}'.format(
                    self.identifier,
                    self.location
                ),
                self.launch
            )
            ftrack.EVENT_HUB.subscribe(
                'data.actionIdentifier={0}-to-s3'.format(self.location),
                self.sync_there
            )
            ftrack.EVENT_HUB.subscribe(
                'data.actionIdentifier=syncto-{0}'.format(self.location),
                self.sync_here
            )

def register(registry, **kwargs):
    if registry is not ftrack.EVENT_HANDLERS:
        return

    Sync.location = location.get_location()
    Sync.variant = 'Sync (%s) To... ' % Sync.location

    print "Registering Sync (%s) action" % Sync.location
    action = Sync()
    action.register()
