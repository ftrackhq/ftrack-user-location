# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

"""
Two-Hop Sync Pattern Test

Tests the event-based remote commanding workflow:
1. User A wants asset from User B's machine (not in ftrack.server)
2. System checks ftrack.server first - NOT AVAILABLE
3. System emits event to User B's machine to upload
4. User B's machine receives event and uploads to ftrack.server
5. User B publishes 'component in location' event
6. User A's machine receives event and downloads from ftrack.server

This is the CRITICAL two-hop pattern: Remote → ftrack.server → Local
"""

import pytest
import tempfile
import shutil
import os
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from threading import Event as ThreadingEvent

try:
    import ftrack_api
    from ftrack_api.accessor.disk import DiskAccessor
    FTRACK_AVAILABLE = True
except ImportError:
    FTRACK_AVAILABLE = False


@pytest.mark.skipif(not FTRACK_AVAILABLE, reason="ftrack_api not available")
class TestTwoHopSync:
    """Test two-hop sync pattern with event-based remote commanding."""

    @pytest.fixture
    def temp_storage_paths(self):
        """Create temporary storage directories for two users."""
        temp_dir = tempfile.mkdtemp(prefix='ftrack_test_two_hop_')

        user_a_storage = os.path.join(temp_dir, 'user_a_storage')
        user_b_storage = os.path.join(temp_dir, 'user_b_storage')
        server_storage = os.path.join(temp_dir, 'server_storage')

        os.makedirs(user_a_storage)
        os.makedirs(user_b_storage)
        os.makedirs(server_storage)

        yield {
            'user_a': user_a_storage,
            'user_b': user_b_storage,
            'server': server_storage,
            'temp_dir': temp_dir
        }

        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def event_hub(self):
        """Create a shared event hub for cross-session events."""
        # Simulate event hub that delivers events to all sessions
        published_events = []
        event_handlers = []  # [(topic_filter, handler_func, session)]

        class MockEventHub:
            def __init__(self, session):
                self.session = session

            def subscribe(self, topic, handler):
                """Subscribe to events."""
                event_handlers.append((topic, handler, self.session))

            def publish(self, event):
                """Publish event to all subscribers."""
                published_events.append(event)

                # Deliver to matching handlers
                for topic_filter, handler, handler_session in event_handlers:
                    if self._matches_filter(event, topic_filter):
                        try:
                            handler(event)
                        except Exception as e:
                            print(f"Handler error: {e}")

            def _matches_filter(self, event, topic_filter):
                """Check if event matches topic filter."""
                # Simple topic matching
                if 'topic=' in topic_filter:
                    required_topic = topic_filter.split('topic=')[1].split(' ')[0]
                    if event.get('topic') != required_topic:
                        return False

                # Check data.actionIdentifier
                if 'data.actionIdentifier=' in topic_filter:
                    required_id = topic_filter.split('data.actionIdentifier=')[1].split(' ')[0]
                    if event.get('data', {}).get('actionIdentifier') != required_id:
                        return False

                return True

        return {
            'published_events': published_events,
            'event_handlers': event_handlers,
            'MockEventHub': MockEventHub
        }

    @pytest.fixture
    def mock_sessions(self, event_hub):
        """Create two mock sessions with shared event hub."""
        # User A session
        session_a = Mock(spec=ftrack_api.Session)
        session_a.api_user = 'user_a'
        session_a.server_url = 'https://test.ftrack.com'
        session_a._commit_count = 0
        session_a.event_hub = event_hub['MockEventHub'](session_a)

        # User B session
        session_b = Mock(spec=ftrack_api.Session)
        session_b.api_user = 'user_b'
        session_b.server_url = 'https://test.ftrack.com'
        session_b._commit_count = 0
        session_b.event_hub = event_hub['MockEventHub'](session_b)

        # Mock users
        user_a = {
            'id': 'user-a-123',
            'username': 'user_a',
            'email': 'user_a@test.com'
        }

        user_b = {
            'id': 'user-b-456',
            'username': 'user_b',
            'email': 'user_b@test.com'
        }

        # Setup queries
        def query_a(query_string):
            result = Mock()
            if 'User' in query_string and 'user_a' in query_string:
                result.first = Mock(return_value=user_a)
            return result
        session_a.query = query_a

        def query_b(query_string):
            result = Mock()
            if 'User' in query_string and 'user_b' in query_string:
                result.first = Mock(return_value=user_b)
            return result
        session_b.query = query_b

        # Mock commit with counter
        def make_commit(session):
            def commit():
                session._commit_count += 1
            return commit

        session_a.commit = make_commit(session_a)
        session_b.commit = make_commit(session_b)

        # Shared Jobs store
        jobs_store = {}

        def make_create_job(session, user):
            def create(entity_type, data):
                if entity_type == 'Job':
                    job_id = f"job-{len(jobs_store)}"
                    job_data = {
                        'id': job_id,
                        'status': data.get('status', 'running'),
                        'data': data.get('data', '{}'),
                        'user': data.get('user'),
                        'user_id': data.get('user', {}).get('id')
                    }
                    jobs_store[job_id] = job_data
                    job = Mock()
                    job.__getitem__ = lambda self, key: job_data[key]
                    job.__setitem__ = lambda self, key, value: job_data.__setitem__(key, value)
                    job.get = lambda key, default=None: job_data.get(key, default)
                    return job
            return create

        session_a.create = make_create_job(session_a, user_a)
        session_b.create = make_create_job(session_b, user_b)

        def make_get_job(session):
            def get(entity_type, entity_id):
                if entity_type == 'Job' and entity_id in jobs_store:
                    job_data = jobs_store[entity_id]
                    job = Mock()
                    job.__getitem__ = lambda self, key: job_data[key]
                    job.__setitem__ = lambda self, key, value: job_data.__setitem__(key, value)
                    job.get = lambda key, default=None: job_data.get(key, default)
                    return job
            return get

        session_a.get = make_get_job(session_a)
        session_b.get = make_get_job(session_b)

        return {
            'session_a': session_a,
            'session_b': session_b,
            'user_a': user_a,
            'user_b': user_b,
            'jobs_store': jobs_store
        }

    @pytest.fixture
    def mock_locations(self, temp_storage_paths):
        """Create mock locations with component tracking."""
        # Track which components are in which locations
        components_in_locations = {
            'location-a': set(),
            'location-b': set(),
            'location-server': set()
        }

        # Create location mocks
        def create_location(location_id, location_name, storage_path):
            location_data = {'id': location_id, 'name': location_name}
            location = Mock()
            location.__getitem__ = lambda self, key: location_data[key]
            location.__setitem__ = lambda self, key, value: location_data.__setitem__(key, value)
            location.get = lambda key, default=None: location_data.get(key, default)
            location.accessor = DiskAccessor(prefix=storage_path)

            def get_availability(component):
                component_id = component.get('id', component)
                return 100.0 if component_id in components_in_locations[location_id] else 0.0

            location.get_component_availability = get_availability

            def add_component(component, source_location):
                component_id = component.get('id', component)
                source_location_id = source_location['id']

                if component_id not in components_in_locations[source_location_id]:
                    raise Exception(f"Component {component_id} not in source")

                # Copy file
                component_name = component.get('name', f'file_{component_id}')
                source_path = os.path.join(source_location.accessor.prefix, component_name)
                dest_path = os.path.join(location.accessor.prefix, component_name)

                if os.path.exists(source_path):
                    shutil.copy2(source_path, dest_path)
                else:
                    with open(dest_path, 'w') as f:
                        f.write(f"Content from {source_location_id}")

                components_in_locations[location_id].add(component_id)

            location.add_component = add_component
            return location

        location_a = create_location('location-a', 'user_a.machine', temp_storage_paths['user_a'])
        location_b = create_location('location-b', 'user_b.machine', temp_storage_paths['user_b'])
        location_server = create_location('location-server', 'ftrack.server', temp_storage_paths['server'])

        return {
            'user_a': location_a,
            'user_b': location_b,
            'server': location_server,
            'components_in_locations': components_in_locations
        }

    def test_two_hop_sync_remote_to_local(
        self, temp_storage_paths, mock_sessions, mock_locations, event_hub
    ):
        """
        Test two-hop sync: User A requests asset from User B's machine.

        Workflow:
        1. User B has remote_asset.txt on their machine
        2. User A requests it (not in ftrack.server yet)
        3. Check ftrack.server - NOT AVAILABLE
        4. Emit event to User B's machine: "upload remote_asset.txt"
        5. User B's event handler uploads to ftrack.server
        6. User B publishes 'component in location' event
        7. User A's event handler downloads from ftrack.server
        8. Verify User A has the file with correct content
        """
        from ftrack_user_location.sync import on_sync_to_destination

        # Step 1: User B has remote_asset.txt locally
        remote_asset_path = os.path.join(temp_storage_paths['user_b'], 'remote_asset.txt')
        with open(remote_asset_path, 'w') as f:
            f.write("Remote asset from User B's machine")

        component_remote = {
            'id': 'component-remote-asset',
            'name': 'remote_asset.txt',
            'size': os.path.getsize(remote_asset_path),
            'version': None
        }

        # Mark component in User B's location ONLY
        mock_locations['components_in_locations']['location-b'].add('component-remote-asset')

        # Step 2: User A wants this file (check ftrack.server first)
        session_a = mock_sessions['session_a']
        original_get_a = mock_sessions['session_a'].get

        def get_location_a(entity_type, entity_id):
            if entity_type == 'Location':
                if entity_id == 'location-a':
                    return mock_locations['user_a']
                elif entity_id == 'location-b':
                    return mock_locations['user_b']
                elif entity_id == 'location-server':
                    return mock_locations['server']
            elif entity_type == 'Component':
                return component_remote
            return original_get_a(entity_type, entity_id)

        session_a.get = get_location_a

        # Step 3: Check if component available in ftrack.server
        server_availability = mock_locations['server'].get_component_availability(component_remote)
        assert server_availability == 0.0, "Component should NOT be in ftrack.server initially"

        # Step 4: Component not in server - emit event to User B to upload
        # This simulates the sync action emitting an event
        upload_event = {
            'topic': 'ftrack.sync',
            'data': {
                'actionIdentifier': 'user_b.machine-to-ftrack',
                'selection': [{'entityId': 'component-remote-asset', 'entityType': 'Component'}],
                'source_location': 'user_b.machine',
                'destination_location': 'ftrack.server',
                'requester': 'user-a-123'
            },
            'source': {'user': {'id': 'user-a-123'}}
        }

        # Step 5: User B's session has handler registered
        session_b = mock_sessions['session_b']
        original_get_b = mock_sessions['session_b'].get

        def get_location_b(entity_type, entity_id):
            if entity_type == 'Location':
                if entity_id == 'location-b':
                    return mock_locations['user_b']
                elif entity_id == 'location-server':
                    return mock_locations['server']
            elif entity_type == 'Component':
                return component_remote
            return original_get_b(entity_type, entity_id)

        session_b.get = get_location_b

        # Simulate User B's upload handler
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-b-upload'):
            # User B uploads to server (triggered by event)
            on_sync_to_destination(
                session=session_b,
                source_id='location-b',
                destination_id='location-server',
                components=[{'id': 'component-remote-asset'}],
                requesting_user_id='user-a-123'  # Requested by User A
            )

        # Verify file uploaded to server
        server_file = os.path.join(temp_storage_paths['server'], 'remote_asset.txt')
        assert os.path.exists(server_file), "File should be uploaded to ftrack.server"
        with open(server_file, 'r') as f:
            content = f.read()
            assert "Remote asset from User B's machine" in content

        # Verify component now available in server
        server_availability_after = mock_locations['server'].get_component_availability(component_remote)
        assert server_availability_after == 100.0, "Component should be in ftrack.server after upload"

        # Step 6: User B publishes 'component in location' event (handled automatically in real code)
        component_available_event = {
            'topic': 'ftrack.location.component-added',
            'data': {
                'component_id': 'component-remote-asset',
                'location_id': 'location-server',
                'location_name': 'ftrack.server'
            }
        }

        # Step 7: User A downloads from ftrack.server
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-a-download'):
            # User A downloads from server
            on_sync_to_destination(
                session=session_a,
                source_id='location-server',
                destination_id='location-a',
                components=[{'id': 'component-remote-asset'}],
                requesting_user_id='user-a-123'
            )

        # Step 8: Verify User A has the file
        user_a_file = os.path.join(temp_storage_paths['user_a'], 'remote_asset.txt')
        assert os.path.exists(user_a_file), "User A should have the remote asset"

        with open(user_a_file, 'r') as f:
            content = f.read()
            assert "Remote asset from User B's machine" in content, \
                "User A should have User B's original content"

        # Verify two-hop worked: User B's machine → ftrack.server → User A's machine
        assert os.path.exists(os.path.join(temp_storage_paths['user_b'], 'remote_asset.txt')), \
            "Original on User B"
        assert os.path.exists(os.path.join(temp_storage_paths['server'], 'remote_asset.txt')), \
            "Intermediate on server"
        assert os.path.exists(os.path.join(temp_storage_paths['user_a'], 'remote_asset.txt')), \
            "Final on User A"

        # Verify Job ownership
        jobs_store = mock_sessions['jobs_store']
        assert len(jobs_store) == 2, "Two Jobs: upload and download"

        upload_job = jobs_store['job-0']
        download_job = jobs_store['job-1']

        # Upload Job owned by User B (executor), requested by User A
        assert upload_job['user_id'] == 'user-b-456', "Upload Job owned by User B (executor)"
        upload_data = json.loads(upload_job['data'])
        assert upload_data['requested_by'] == 'user-a-123', "Upload requested by User A"

        # Download Job owned by User A (executor)
        assert download_job['user_id'] == 'user-a-123', "Download Job owned by User A (executor)"

    def test_smart_sync_fallback_to_server(
        self, temp_storage_paths, mock_sessions, mock_locations
    ):
        """
        Test smart sync: If component already in ftrack.server, skip remote machine.

        Workflow:
        1. User B has asset on their machine
        2. Asset already uploaded to ftrack.server (previous sync)
        3. User A requests asset from User B
        4. System checks ftrack.server - AVAILABLE
        5. System downloads directly from ftrack.server (User B's machine not needed)
        6. Verify User A gets the file without emitting event to User B
        """
        from ftrack_user_location.sync import on_sync_to_destination

        # Step 1 & 2: Asset exists on User B AND ftrack.server
        asset_path_b = os.path.join(temp_storage_paths['user_b'], 'already_synced.txt')
        asset_path_server = os.path.join(temp_storage_paths['server'], 'already_synced.txt')

        with open(asset_path_b, 'w') as f:
            f.write("Already synced asset")
        with open(asset_path_server, 'w') as f:
            f.write("Already synced asset")

        component_synced = {
            'id': 'component-already-synced',
            'name': 'already_synced.txt',
            'size': os.path.getsize(asset_path_server),
            'version': None
        }

        # Mark in both User B and server
        mock_locations['components_in_locations']['location-b'].add('component-already-synced')
        mock_locations['components_in_locations']['location-server'].add('component-already-synced')

        # Step 3-5: User A requests from "User B" but gets from server
        session_a = mock_sessions['session_a']
        original_get_a = mock_sessions['session_a'].get

        def get_location_a(entity_type, entity_id):
            if entity_type == 'Location':
                if entity_id == 'location-a':
                    return mock_locations['user_a']
                elif entity_id == 'location-server':
                    return mock_locations['server']
            elif entity_type == 'Component':
                return component_synced
            return original_get_a(entity_type, entity_id)

        session_a.get = get_location_a

        # Check server availability FIRST
        server_availability = mock_locations['server'].get_component_availability(component_synced)
        assert server_availability == 100.0, "Component should be in ftrack.server"

        # Download directly from server (no event to User B needed)
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-direct'):
            on_sync_to_destination(
                session=session_a,
                source_id='location-server',
                destination_id='location-a',
                components=[{'id': 'component-already-synced'}],
                requesting_user_id='user-a-123'
            )

        # Step 6: Verify User A has the file
        user_a_file = os.path.join(temp_storage_paths['user_a'], 'already_synced.txt')
        assert os.path.exists(user_a_file), "User A should have the file from server"

        with open(user_a_file, 'r') as f:
            content = f.read()
            assert "Already synced asset" in content

        # Verify only ONE Job created (download from server)
        # NO upload Job because file already in server
        jobs_store = mock_sessions['jobs_store']
        assert len(jobs_store) == 1, "Only one Job: direct download from server"

        download_job = jobs_store['job-0']
        assert download_job['user_id'] == 'user-a-123', "Download Job owned by User A"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
