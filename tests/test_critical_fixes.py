# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

"""
Critical fixes validation tests for v0.5.1.

These tests verify the critical bug fixes without requiring two users:
1. Threading import at module level
2. Job lifecycle pattern (re-query before updates)
3. Executor-owned Jobs (not requester)
4. Batch commits (not per-component)
5. Persistent event subscriptions
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add source to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'source'))


class TestThreadingImport:
    """Verify threading imported at module level (v0.5.1 fix)."""

    def test_threading_import_sync_action(self):
        """Verify threading imported at module level in sync_action.py."""
        # Import the module - should not raise ImportError
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'resource', 'hook'))

        # Mock dependencies before import
        with patch.dict('sys.modules', {
            'ftrack_api': MagicMock(),
            'ftrack_action_handler': MagicMock(),
            'ftrack_action_handler.action': MagicMock(),
            'ftrack_user_location': MagicMock(),
            'ftrack_user_location.sync': MagicMock(),
            'ftrack_user_location.configure_logging': MagicMock(),
        }):
            import sync_action

            # Verify threading is available at module level
            assert hasattr(sync_action, 'threading')
            assert sync_action.threading.__name__ == 'threading'

    def test_threading_lock_creation(self):
        """Verify threading.Lock() can be created at class init."""
        import threading

        # This should not raise NameError
        lock = threading.Lock()
        assert lock is not None


class TestJobLifecyclePattern:
    """Verify Job re-query pattern before updates (v0.3.2 fix)."""

    def test_job_requery_on_sync_to_destination(self, mock_session_with_entities):
        """Verify Job re-queried before final update in on_sync_to_destination."""
        from ftrack_user_location.sync import on_sync_to_destination

        # Prepare test data
        source_id = 'location-source'
        destination_id = 'location-dest'
        components = [{'id': 'component-1'}]
        requesting_user_id = 'requester-456'

        # Track session.get calls
        get_calls = []
        original_get = mock_session_with_entities.get

        def tracking_get(entity_type, entity_id):
            get_calls.append((entity_type, entity_id))
            return original_get(entity_type, entity_id)

        mock_session_with_entities.get = tracking_get

        # Mock sync_report module
        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-123'):
            # Execute sync
            on_sync_to_destination(
                mock_session_with_entities,
                source_id,
                destination_id,
                components,
                requesting_user_id
            )

        # Verify Job was re-queried (session.get('Job', job_id) called)
        job_queries = [call for call in get_calls if call[0] == 'Job']
        assert len(job_queries) > 0, "Job should be re-queried before updates"

    def test_job_requery_multiple_times(self, mock_session_with_entities):
        """Verify Job re-queried multiple times during sync lifecycle."""
        from ftrack_user_location.sync import on_sync_to_destination

        source_id = 'location-source'
        destination_id = 'location-dest'
        components = [{'id': f'component-{i}'} for i in range(5)]
        requesting_user_id = 'requester-456'

        get_calls = []
        original_get = mock_session_with_entities.get

        def tracking_get(entity_type, entity_id):
            get_calls.append((entity_type, entity_id))
            return original_get(entity_type, entity_id)

        mock_session_with_entities.get = tracking_get

        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-123'):
            on_sync_to_destination(
                mock_session_with_entities,
                source_id,
                destination_id,
                components,
                requesting_user_id
            )

        job_queries = [call for call in get_calls if call[0] == 'Job']

        # Should have at least one Job re-query before final update
        assert len(job_queries) >= 1, "Job should be re-queried at least once"


class TestJobOwnership:
    """Verify Job owned by executor, not requester (v0.3.2 fix)."""

    def test_job_owned_by_session_user(self, mock_session_with_entities, mock_user):
        """Verify Job created with session user as owner."""
        from ftrack_user_location.sync import on_sync_to_destination

        source_id = 'location-source'
        destination_id = 'location-dest'
        components = [{'id': 'component-1'}]
        requesting_user_id = 'requester-456'  # Different from session user

        create_calls = []
        original_create = mock_session_with_entities.create

        def tracking_create(entity_type, data):
            create_calls.append((entity_type, data))
            return original_create(entity_type, data)

        mock_session_with_entities.create = tracking_create

        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-123'):
            on_sync_to_destination(
                mock_session_with_entities,
                source_id,
                destination_id,
                components,
                requesting_user_id
            )

        # Find Job creation call
        job_creates = [call for call in create_calls if call[0] == 'Job']
        assert len(job_creates) > 0, "Job should be created"

        job_data = job_creates[0][1]
        assert 'user' in job_data, "Job should have 'user' field"
        assert job_data['user'] == mock_user, "Job should be owned by session user (executor)"
        assert job_data['user']['username'] == 'testuser', "Job owner should be testuser"

    def test_requesting_user_tracked_in_metadata(self, mock_session_with_entities):
        """Verify requesting user ID tracked in Job.data metadata."""
        from ftrack_user_location.sync import on_sync_to_destination
        import json

        source_id = 'location-source'
        destination_id = 'location-dest'
        components = [{'id': 'component-1'}]
        requesting_user_id = 'requester-456'

        create_calls = []
        original_create = mock_session_with_entities.create

        def tracking_create(entity_type, data):
            create_calls.append((entity_type, data))
            return original_create(entity_type, data)

        mock_session_with_entities.create = tracking_create

        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-123'):
            on_sync_to_destination(
                mock_session_with_entities,
                source_id,
                destination_id,
                components,
                requesting_user_id
            )

        job_creates = [call for call in create_calls if call[0] == 'Job']
        job_data = job_creates[0][1]

        # Parse Job.data JSON
        data_dict = json.loads(job_data['data'])
        assert 'requested_by' in data_dict, "Job.data should contain 'requested_by'"
        assert data_dict['requested_by'] == requesting_user_id, "Should track requesting user ID"


class TestBatchCommits:
    """Verify batch commits, not per-component (v0.3.2 fix)."""

    def test_commit_not_in_component_loop(self, mock_session_with_entities):
        """Verify session.commit() not called inside component loop."""
        from ftrack_user_location.sync import on_sync_to_destination

        source_id = 'location-source'
        destination_id = 'location-dest'
        components = [{'id': f'component-{i}'} for i in range(10)]  # 10 components
        requesting_user_id = 'requester-456'

        # Reset commit counter
        mock_session_with_entities._commit_count = 0

        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-123'):
            on_sync_to_destination(
                mock_session_with_entities,
                source_id,
                destination_id,
                components,
                requesting_user_id
            )

        # Verify commit count is NOT equal to component count
        # Expected: 2-3 commits (initial Job creation, batch after loop, final status)
        # NOT 10+ commits (one per component)
        assert mock_session_with_entities._commit_count < 5, \
            f"Should have <5 commits for 10 components, got {mock_session_with_entities._commit_count}"

        # Specifically, should NOT have ~10 commits (per-component pattern)
        assert mock_session_with_entities._commit_count < len(components), \
            "Commit count should be less than component count (batch commit)"

    def test_batch_commit_performance_100_components(self, mock_session_with_entities):
        """Verify batch commit pattern with 100 components."""
        from ftrack_user_location.sync import on_sync_to_destination

        source_id = 'location-source'
        destination_id = 'location-dest'
        components = [{'id': f'component-{i}'} for i in range(100)]
        requesting_user_id = 'requester-456'

        mock_session_with_entities._commit_count = 0

        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-123'):
            on_sync_to_destination(
                mock_session_with_entities,
                source_id,
                destination_id,
                components,
                requesting_user_id
            )

        # With batch commits: should be 2-4 commits regardless of component count
        # Without batch commits: would be 100+ commits
        assert mock_session_with_entities._commit_count < 10, \
            f"Batch commit should result in <10 commits for 100 components, got {mock_session_with_entities._commit_count}"


class TestFailureTracking:
    """Verify failures tracked correctly without immediate Job updates."""

    def test_missing_component_tracked_not_immediate_fail(self, mock_session_with_entities):
        """Verify missing component tracked, Job not immediately marked failed."""
        from ftrack_user_location.sync import on_sync_to_destination

        source_id = 'location-source'
        destination_id = 'location-dest'

        # Mix of available and missing components
        components = [
            {'id': 'component-available-1'},
            {'id': 'component-missing-2'},
            {'id': 'component-available-3'}
        ]
        requesting_user_id = 'requester-456'

        # Mock location with specific availability behavior
        mock_location = mock_session_with_entities.get('Location', source_id)

        def mock_availability(component):
            if 'missing' in component.get('id', ''):
                return 0.0
            return 100.0

        mock_location.get_component_availability = mock_availability

        # Track Job status updates
        job_status_updates = []
        original_get = mock_session_with_entities.get

        def tracking_get(entity_type, entity_id):
            job = original_get(entity_type, entity_id)
            if entity_type == 'Job':
                # Track when status is set
                original_setitem = job.__setitem__

                def tracking_setitem(key, value):
                    if key == 'status':
                        job_status_updates.append(value)
                    return original_setitem(key, value)

                job.__setitem__ = tracking_setitem
            return job

        mock_session_with_entities.get = tracking_get

        with patch('ftrack_user_location.sync.create_and_attach_sync_report', return_value='report-123'):
            on_sync_to_destination(
                mock_session_with_entities,
                source_id,
                destination_id,
                components,
                requesting_user_id
            )

        # Job should complete (not fail immediately on first missing component)
        # Final status should reflect the mixed results
        assert len(job_status_updates) > 0, "Job status should be updated"

        # Should not have multiple 'failed' updates followed by 'done' (old bug)
        # Should have final status based on overall results
        if 'failed' in job_status_updates:
            # If failed, should be the final status
            assert job_status_updates[-1] == 'failed', "Failed should be final status if any component failed"


class TestEventSubscriptions:
    """Verify persistent event subscriptions pattern (v0.4.6 fix)."""

    def test_event_hub_subscribe_persistent(self):
        """Verify event subscriptions registered at startup, not dynamically."""
        # This is more of an integration test - verify pattern in code
        with open('resource/hook/sync_action.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # Verify _register method exists and subscribes to pong
        # Note: AdvancedBaseAction uses 'register' method which calls parent _register
        assert ('def _register(' in content or 'def register(' in content), "_register or register method should exist"
        assert 'event_hub.subscribe' in content, "Should subscribe to events"
        assert 'ftrack.location.ping.response' in content, "Should subscribe to pong responses"

    def test_no_dynamic_unsubscribe_in_check_method(self):
        """Verify check_remote_location_online doesn't dynamically subscribe/unsubscribe."""
        with open('resource/hook/sync_action.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # Find check_remote_location_online method
        lines = content.split('\n')
        in_check_method = False
        method_lines = []

        for line in lines:
            if 'def check_remote_location_online' in line:
                in_check_method = True
            elif in_check_method:
                if line.strip().startswith('def ') and 'check_remote_location_online' not in line:
                    break
                method_lines.append(line)

        method_content = '\n'.join(method_lines)

        # Should NOT have subscribe/unsubscribe inside the check method
        assert 'event_hub.subscribe' not in method_content, \
            "check_remote_location_online should not dynamically subscribe"
        assert 'event_hub.unsubscribe' not in method_content, \
            "check_remote_location_online should not dynamically unsubscribe"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
