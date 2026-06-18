# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

"""
Integration test: Two users with real event systems and file transfers.

This test simulates the real-world scenario:
1. Two ftrack sessions (user A and user B)
2. Two separate storage locations (temp directories)
3. User A publishes a file locally
4. User A syncs to ftrack.server
5. User B syncs from ftrack.server to local
6. Verify file transferred correctly
7. Verify Job ownership (executor, not requester)
"""

import pytest
import tempfile
import shutil
import os
import time
import threading
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Skip this test if ftrack_api not properly configured
pytest_plugins = []

try:
    import ftrack_api
    FTRACK_AVAILABLE = True
except ImportError:
    FTRACK_AVAILABLE = False


@pytest.mark.skipif(not FTRACK_AVAILABLE, reason="ftrack_api not available")
class TestTwoUserIntegration:
    """End-to-end integration test with two users."""

    @pytest.fixture
    def temp_storage_paths(self):
        """Create two temporary storage directories."""
        temp_dir = tempfile.mkdtemp(prefix='ftrack_test_')

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

        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_sessions(self):
        """Create two mock ftrack sessions for user A and user B."""
        # User A session
        session_a = Mock(spec=ftrack_api.Session)
        session_a.api_user = 'user_a'
        session_a.server_url = 'https://test.ftrack.com'
        session_a._commit_count = 0

        # User B session
        session_b = Mock(spec=ftrack_api.Session)
        session_b.api_user = 'user_b'
        session_b.server_url = 'https://test.ftrack.com'
        session_b._commit_count = 0

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

        # Setup session_a queries
        def query_a(query_string):
            result = Mock()
            if 'User' in query_string and 'user_a' in query_string:
                result.first = Mock(return_value=user_a)
            return result
        session_a.query = query_a

        # Setup session_b queries
        def query_b(query_string):
            result = Mock()
            if 'User' in query_string and 'user_b' in query_string:
                result.first = Mock(return_value=user_b)
            return result
        session_b.query = query_b

        # Mock commit with counter
        def make_commit_counter(session):
            def commit():
                session._commit_count += 1
            return commit

        session_a.commit = make_commit_counter(session_a)
        session_b.commit = make_commit_counter(session_b)

        # Shared state for Jobs (simulates ftrack server)
        jobs_store = {}

        # Mock create Job
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

                    # Return mock Job
                    job = Mock()
                    job.__getitem__ = lambda self, key: job_data[key]
                    job.__setitem__ = lambda self, key, value: job_data.__setitem__(key, value)
                    job.get = lambda key, default=None: job_data.get(key, default)
                    return job
            return create

        session_a.create = make_create_job(session_a, user_a)
        session_b.create = make_create_job(session_b, user_b)

        # Mock get Job (re-query)
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
        """Create three mock locations: user_a.location, user_b.location, ftrack.server."""
        from ftrack_api.accessor.disk import DiskAccessor

        # User A location
        location_a_data = {'id': 'location-a', 'name': 'user_a.machine'}
        location_a = Mock()
        location_a.__getitem__ = lambda self, key: location_a_data[key]
        location_a.__setitem__ = lambda self, key, value: location_a_data.__setitem__(key, value)
        location_a.get = lambda key, default=None: location_a_data.get(key, default)
        location_a.accessor = DiskAccessor(prefix=temp_storage_paths['user_a'])

        # User B location
        location_b_data = {'id': 'location-b', 'name': 'user_b.machine'}
        location_b = Mock()
        location_b.__getitem__ = lambda self, key: location_b_data[key]
        location_b.__setitem__ = lambda self, key, value: location_b_data.__setitem__(key, value)
        location_b.get = lambda key, default=None: location_b_data.get(key, default)
        location_b.accessor = DiskAccessor(prefix=temp_storage_paths['user_b'])

        # ftrack.server location
        location_server_data = {'id': 'location-server', 'name': 'ftrack.server'}
        location_server = Mock()
        location_server.__getitem__ = lambda self, key: location_server_data[key]
        location_server.__setitem__ = lambda self, key, value: location_server_data.__setitem__(key, value)
        location_server.get = lambda key, default=None: location_server_data.get(key, default)
        location_server.accessor = DiskAccessor(prefix=temp_storage_paths['server'])

        # Track which components are in which locations
        components_in_locations = {
            'location-a': set(),
            'location-b': set(),
            'location-server': set()
        }

        # Mock get_component_availability
        def make_availability_checker(location_id):
            def check_availability(component):
                component_id = component.get('id', component)
                if component_id in components_in_locations[location_id]:
                    return 100.0
                return 0.0
            return check_availability

        location_a.get_component_availability = make_availability_checker('location-a')
        location_b.get_component_availability = make_availability_checker('location-b')
        location_server.get_component_availability = make_availability_checker('location-server')

        # Mock add_component (transfers file)
        def make_add_component(dest_location_id, dest_accessor, source_locations):
            def add_component(component, source_location):
                component_id = component.get('id', component)
                source_location_id = source_location['id']

                # Check component exists in source
                if component_id not in components_in_locations[source_location_id]:
                    raise Exception(f"Component {component_id} not in source {source_location_id}")

                # Get source accessor
                source_accessor = source_locations[source_location_id].accessor

                # Build file paths
                component_name = component.get('name', f'file_{component_id}')
                source_path = os.path.join(source_accessor.prefix, component_name)
                dest_path = os.path.join(dest_accessor.prefix, component_name)

                # Copy file
                if os.path.exists(source_path):
                    shutil.copy2(source_path, dest_path)
                else:
                    # Create empty file for test
                    with open(dest_path, 'w') as f:
                        f.write(f"Test content for {component_name}")

                # Mark component in destination
                components_in_locations[dest_location_id].add(component_id)

            return add_component

        source_locations = {
            'location-a': location_a,
            'location-b': location_b,
            'location-server': location_server
        }

        location_a.add_component = make_add_component('location-a', location_a.accessor, source_locations)
        location_b.add_component = make_add_component('location-b', location_b.accessor, source_locations)
        location_server.add_component = make_add_component('location-server', location_server.accessor, source_locations)

        return {
            'user_a': location_a,
            'user_b': location_b,
            'server': location_server,
            'components_in_locations': components_in_locations
        }

    def test_two_user_file_transfer(self, temp_storage_paths, mock_sessions, mock_locations):
        """
        End-to-end test: User A publishes → syncs to server → User B downloads.

        Workflow:
        1. User A publishes test.txt to user_a.machine
        2. User A triggers sync: user_a.machine → ftrack.server
        3. User B triggers sync: ftrack.server → user_b.machine
        4. Verify test.txt exists in user_b.machine
        5. Verify Jobs owned by executors (not requesters)
        """
        from ftrack_user_location.sync import on_sync_to_destination

        # Step 1: User A publishes a file locally
        test_file = os.path.join(temp_storage_paths['user_a'], 'test.txt')
        with open(test_file, 'w') as f:
            f.write("Hello from User A!")

        # Create test component
        test_component = {
            'id': 'component-test-file',
            'name': 'test.txt',
            'size': os.path.getsize(test_file),
            'version': None
        }

        # Mark component as in user_a location
        mock_locations['components_in_locations']['location-a'].add('component-test-file')

        # Step 2: User A syncs to ftrack.server
        # User A executes sync on their machine
        session_a = mock_sessions['session_a']
        user_a = mock_sessions['user_a']

        # Save original get for Job queries
        original_get_a = mock_sessions['session_a'].get

        # Mock session.get for locations
        def get_location_a(entity_type, entity_id):
            if entity_type == 'Location':
                if entity_id == 'location-a':
                    return mock_locations['user_a']
                elif entity_id == 'location-server':
                    return mock_locations['server']
            elif entity_type == 'Component':
                return test_component
            # Fallback to Job get
            return original_get_a(entity_type, entity_id)

        session_a.get = get_location_a

        # Mock create_and_attach_sync_report
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-123'):
            # User A runs sync
            on_sync_to_destination(
                session=session_a,
                source_id='location-a',
                destination_id='location-server',
                components=[{'id': 'component-test-file'}],
                requesting_user_id='user-a-123'  # User A requests their own sync
            )

        # Verify file copied to server
        server_file = os.path.join(temp_storage_paths['server'], 'test.txt')
        assert os.path.exists(server_file), "File should be copied to ftrack.server"
        with open(server_file, 'r') as f:
            content = f.read()
            assert "Hello from User A!" in content, "File content should match"

        # Verify Job created and owned by user_a (executor)
        jobs_store = mock_sessions['jobs_store']
        assert len(jobs_store) == 1, "One Job should be created"

        job_1 = list(jobs_store.values())[0]
        assert job_1['user_id'] == 'user-a-123', "Job should be owned by executor (user A)"

        job_data_1 = json.loads(job_1['data'])
        assert job_data_1['requested_by'] == 'user-a-123', "Requester tracked in metadata"

        # Step 3: User B syncs from ftrack.server to local
        # User B executes sync on their machine
        session_b = mock_sessions['session_b']
        user_b = mock_sessions['user_b']

        # Save original get for Job queries
        original_get_b = mock_sessions['session_b'].get

        # Mock session.get for locations
        def get_location_b(entity_type, entity_id):
            if entity_type == 'Location':
                if entity_id == 'location-server':
                    return mock_locations['server']
                elif entity_id == 'location-b':
                    return mock_locations['user_b']
            elif entity_type == 'Component':
                return test_component
            # Fallback to Job get
            return original_get_b(entity_type, entity_id)

        session_b.get = get_location_b

        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-456'):
            # User B runs sync (downloading from server)
            on_sync_to_destination(
                session=session_b,
                source_id='location-server',
                destination_id='location-b',
                components=[{'id': 'component-test-file'}],
                requesting_user_id='user-b-456'  # User B requests download
            )

        # Step 4: Verify file arrived at user B's location
        user_b_file = os.path.join(temp_storage_paths['user_b'], 'test.txt')
        assert os.path.exists(user_b_file), "File should be copied to user_b.machine"

        with open(user_b_file, 'r') as f:
            content = f.read()
            assert "Hello from User A!" in content, "File content should match original"

        # Verify second Job created and owned by user_b (executor)
        assert len(jobs_store) == 2, "Two Jobs should be created (one per sync)"

        job_2 = list(jobs_store.values())[1]
        assert job_2['user_id'] == 'user-b-456', "Job should be owned by executor (user B)"

        job_data_2 = json.loads(job_2['data'])
        assert job_data_2['requested_by'] == 'user-b-456', "Requester tracked in metadata"

        # Step 5: Verify batch commits (not per-component)
        assert session_a._commit_count < 5, \
            f"User A should have <5 commits (batch), got {session_a._commit_count}"
        assert session_b._commit_count < 5, \
            f"User B should have <5 commits (batch), got {session_b._commit_count}"

    def test_cross_user_sync_job_ownership(self, temp_storage_paths, mock_sessions, mock_locations):
        """
        Test cross-user scenario: User A requests, User B executes.

        Scenario: User A asks User B to upload B's file to server.
        - Requester: User A (user-a-123)
        - Executor: User B (user-b-456)
        - Job should be owned by User B (executor), with A tracked in metadata
        """
        from ftrack_user_location.sync import on_sync_to_destination

        # Setup: User B has a file
        test_file = os.path.join(temp_storage_paths['user_b'], 'user_b_asset.txt')
        with open(test_file, 'w') as f:
            f.write("Asset from User B")

        test_component = {
            'id': 'component-b-asset',
            'name': 'user_b_asset.txt',
            'size': os.path.getsize(test_file),
            'version': None
        }

        mock_locations['components_in_locations']['location-b'].add('component-b-asset')

        # User B's session (executor)
        session_b = mock_sessions['session_b']

        original_get_b2 = mock_sessions['session_b'].get

        def get_location_b(entity_type, entity_id):
            if entity_type == 'Location':
                if entity_id == 'location-b':
                    return mock_locations['user_b']
                elif entity_id == 'location-server':
                    return mock_locations['server']
            elif entity_type == 'Component':
                return test_component
            return original_get_b2(entity_type, entity_id)

        session_b.get = get_location_b

        # User A requests, User B executes
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-cross'):
            on_sync_to_destination(
                session=session_b,  # B's session (executor)
                source_id='location-b',
                destination_id='location-server',
                components=[{'id': 'component-b-asset'}],
                requesting_user_id='user-a-123'  # A requests (different from executor)
            )

        # Verify Job ownership
        jobs_store = mock_sessions['jobs_store']
        assert len(jobs_store) == 1, "One Job should be created"

        job = list(jobs_store.values())[0]

        # CRITICAL: Job owned by executor (User B), NOT requester (User A)
        assert job['user_id'] == 'user-b-456', \
            "Job MUST be owned by executor (User B), not requester (User A)"

        # Requester tracked in metadata
        job_data = json.loads(job['data'])
        assert job_data['requested_by'] == 'user-a-123', \
            "Requester (User A) should be tracked in Job.data"

        # Verify file uploaded
        server_file = os.path.join(temp_storage_paths['server'], 'user_b_asset.txt')
        assert os.path.exists(server_file), "File should be uploaded to server"

    def test_batch_commit_with_multiple_components(self, temp_storage_paths, mock_sessions, mock_locations):
        """
        Test batch commits with 50 components.

        Verify:
        - Commits << component count (batch commit working)
        - Expected: ~3 commits (create Job, batch after loop, final status)
        - NOT expected: 50+ commits (per-component pattern)
        """
        from ftrack_user_location.sync import on_sync_to_destination

        # Create 50 test files
        components = []
        for i in range(50):
            filename = f'file_{i}.txt'
            filepath = os.path.join(temp_storage_paths['user_a'], filename)
            with open(filepath, 'w') as f:
                f.write(f"Test content {i}")

            component_id = f'component-{i}'
            components.append({'id': component_id})
            mock_locations['components_in_locations']['location-a'].add(component_id)

        # Mock component getter
        session_a = mock_sessions['session_a']

        original_get_a3 = mock_sessions['session_a'].get

        def get_entity(entity_type, entity_id):
            if entity_type == 'Location':
                if entity_id == 'location-a':
                    return mock_locations['user_a']
                elif entity_id == 'location-server':
                    return mock_locations['server']
            elif entity_type == 'Component':
                comp_num = entity_id.split('-')[1] if '-' in entity_id else '0'
                return {
                    'id': entity_id,
                    'name': f'file_{comp_num}.txt',
                    'size': 100,
                    'version': None
                }
            return original_get_a3(entity_type, entity_id)

        session_a.get = get_entity
        session_a._commit_count = 0  # Reset counter

        # Execute sync
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-batch'):
            on_sync_to_destination(
                session=session_a,
                source_id='location-a',
                destination_id='location-server',
                components=components,
                requesting_user_id='user-a-123'
            )

        # Verify batch commits
        assert session_a._commit_count < 10, \
            f"Batch commit should result in <10 commits for 50 components, got {session_a._commit_count}"

        # Verify all files transferred
        for i in range(50):
            server_file = os.path.join(temp_storage_paths['server'], f'file_{i}.txt')
            assert os.path.exists(server_file), f"file_{i}.txt should be copied to server"


    def test_bidirectional_push_pull(self, temp_storage_paths, mock_sessions, mock_locations):
        """
        Test bidirectional push/pull: Both users can push to and pull from each other.

        Workflow:
        1. User A publishes asset_a.txt locally
        2. User B publishes asset_b.txt locally
        3. User A pushes to server (asset_a.txt)
        4. User B pushes to server (asset_b.txt)
        5. User A pulls asset_b.txt from server (gets User B's file)
        6. User B pulls asset_a.txt from server (gets User A's file)
        7. Verify both users have both files
        """
        from ftrack_user_location.sync import on_sync_to_destination

        # Step 1: User A creates asset_a.txt
        asset_a_path = os.path.join(temp_storage_paths['user_a'], 'asset_a.txt')
        with open(asset_a_path, 'w') as f:
            f.write("Asset from User A")

        component_a = {
            'id': 'component-asset-a',
            'name': 'asset_a.txt',
            'size': os.path.getsize(asset_a_path),
            'version': None
        }
        mock_locations['components_in_locations']['location-a'].add('component-asset-a')

        # Step 2: User B creates asset_b.txt
        asset_b_path = os.path.join(temp_storage_paths['user_b'], 'asset_b.txt')
        with open(asset_b_path, 'w') as f:
            f.write("Asset from User B")

        component_b = {
            'id': 'component-asset-b',
            'name': 'asset_b.txt',
            'size': os.path.getsize(asset_b_path),
            'version': None
        }
        mock_locations['components_in_locations']['location-b'].add('component-asset-b')

        # Setup session A
        session_a = mock_sessions['session_a']
        original_get_a = mock_sessions['session_a'].get

        def get_location_a(entity_type, entity_id):
            if entity_type == 'Location':
                if entity_id == 'location-a':
                    return mock_locations['user_a']
                elif entity_id == 'location-server':
                    return mock_locations['server']
            elif entity_type == 'Component':
                if entity_id == 'component-asset-a':
                    return component_a
                elif entity_id == 'component-asset-b':
                    return component_b
            return original_get_a(entity_type, entity_id)

        session_a.get = get_location_a

        # Setup session B
        session_b = mock_sessions['session_b']
        original_get_b = mock_sessions['session_b'].get

        def get_location_b(entity_type, entity_id):
            if entity_type == 'Location':
                if entity_id == 'location-b':
                    return mock_locations['user_b']
                elif entity_id == 'location-server':
                    return mock_locations['server']
            elif entity_type == 'Component':
                if entity_id == 'component-asset-a':
                    return component_a
                elif entity_id == 'component-asset-b':
                    return component_b
            return original_get_b(entity_type, entity_id)

        session_b.get = get_location_b

        # Step 3: User A pushes asset_a.txt to server
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-a-push'):
            on_sync_to_destination(
                session=session_a,
                source_id='location-a',
                destination_id='location-server',
                components=[{'id': 'component-asset-a'}],
                requesting_user_id='user-a-123'
            )

        # Verify asset_a on server
        server_asset_a = os.path.join(temp_storage_paths['server'], 'asset_a.txt')
        assert os.path.exists(server_asset_a), "User A's asset should be on server"
        with open(server_asset_a, 'r') as f:
            assert "Asset from User A" in f.read()

        # Step 4: User B pushes asset_b.txt to server
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-b-push'):
            on_sync_to_destination(
                session=session_b,
                source_id='location-b',
                destination_id='location-server',
                components=[{'id': 'component-asset-b'}],
                requesting_user_id='user-b-456'
            )

        # Verify asset_b on server
        server_asset_b = os.path.join(temp_storage_paths['server'], 'asset_b.txt')
        assert os.path.exists(server_asset_b), "User B's asset should be on server"
        with open(server_asset_b, 'r') as f:
            assert "Asset from User B" in f.read()

        # Step 5: User A pulls asset_b.txt from server (gets User B's file)
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-a-pull'):
            on_sync_to_destination(
                session=session_a,
                source_id='location-server',
                destination_id='location-a',
                components=[{'id': 'component-asset-b'}],
                requesting_user_id='user-a-123'
            )

        # Verify User A now has User B's asset
        user_a_asset_b = os.path.join(temp_storage_paths['user_a'], 'asset_b.txt')
        assert os.path.exists(user_a_asset_b), "User A should have User B's asset"
        with open(user_a_asset_b, 'r') as f:
            content = f.read()
            assert "Asset from User B" in content, "User A should have User B's content"

        # Step 6: User B pulls asset_a.txt from server (gets User A's file)
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-b-pull'):
            on_sync_to_destination(
                session=session_b,
                source_id='location-server',
                destination_id='location-b',
                components=[{'id': 'component-asset-a'}],
                requesting_user_id='user-b-456'
            )

        # Verify User B now has User A's asset
        user_b_asset_a = os.path.join(temp_storage_paths['user_b'], 'asset_a.txt')
        assert os.path.exists(user_b_asset_a), "User B should have User A's asset"
        with open(user_b_asset_a, 'r') as f:
            content = f.read()
            assert "Asset from User A" in content, "User B should have User A's content"

        # Step 7: Verify final state - both users have both assets
        assert os.path.exists(os.path.join(temp_storage_paths['user_a'], 'asset_a.txt')), \
            "User A should have own asset"
        assert os.path.exists(os.path.join(temp_storage_paths['user_a'], 'asset_b.txt')), \
            "User A should have User B's asset"
        assert os.path.exists(os.path.join(temp_storage_paths['user_b'], 'asset_b.txt')), \
            "User B should have own asset"
        assert os.path.exists(os.path.join(temp_storage_paths['user_b'], 'asset_a.txt')), \
            "User B should have User A's asset"

        # Verify 4 Jobs created (2 pushes, 2 pulls)
        jobs_store = mock_sessions['jobs_store']
        assert len(jobs_store) == 4, "Should have 4 Jobs (A push, B push, A pull, B pull)"

        # Verify Job ownership
        jobs = list(jobs_store.values())
        assert jobs[0]['user_id'] == 'user-a-123', "Job 1 owned by User A"
        assert jobs[1]['user_id'] == 'user-b-456', "Job 2 owned by User B"
        assert jobs[2]['user_id'] == 'user-a-123', "Job 3 owned by User A"
        assert jobs[3]['user_id'] == 'user-b-456', "Job 4 owned by User B"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
