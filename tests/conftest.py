# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

"""Pytest fixtures for ftrack-user-location tests."""

import pytest
from unittest.mock import Mock, MagicMock, patch
import json


@pytest.fixture
def mock_session():
    """Create a mock ftrack session."""
    session = Mock()
    session.api_user = 'testuser'
    session.server_url = 'https://test.ftrack.com'

    # Mock commit counter to verify batch commits
    session._commit_count = 0
    original_commit = session.commit

    def counting_commit():
        session._commit_count += 1
        return original_commit()

    session.commit = counting_commit

    return session


@pytest.fixture
def mock_user():
    """Create a mock ftrack user."""
    user = {
        'id': 'user-123',
        'username': 'testuser',
        'email': 'test@example.com'
    }
    return user


@pytest.fixture
def mock_requesting_user():
    """Create a mock requesting user (different from session user)."""
    user = {
        'id': 'requester-456',
        'username': 'requester',
        'email': 'requester@example.com'
    }
    return user


@pytest.fixture
def mock_location():
    """Create a mock ftrack location."""
    location_data = {
        'id': 'location-123',
        'name': 'test.location'
    }

    location = Mock()
    location.__getitem__ = lambda self, key: location_data[key]
    location.__setitem__ = lambda self, key, value: location_data.__setitem__(key, value)
    location.get = lambda key, default=None: location_data.get(key, default)

    # Mock accessor
    accessor = Mock()
    accessor.prefix = '/tmp/test-location'
    location.accessor = accessor

    # Mock component availability
    def mock_availability(component):
        # Return 100% if component name contains "available"
        if 'available' in component.get('name', ''):
            return 100.0
        # Return 0% if component name contains "missing"
        if 'missing' in component.get('name', ''):
            return 0.0
        return 100.0

    location.get_component_availability = mock_availability

    # Mock add_component
    location.add_component = Mock()

    return location


@pytest.fixture
def mock_component():
    """Create a mock ftrack component."""
    component = {
        'id': 'component-123',
        'name': 'main',
        'size': 1024 * 1024,  # 1MB
        'version': {
            'id': 'version-123',
            'version': 1,
            'asset': {
                'id': 'asset-123',
                'name': 'test_asset'
            }
        }
    }
    return component


@pytest.fixture
def mock_components():
    """Create a list of mock components."""
    return [
        {
            'id': f'component-{i}',
            'name': f'component_{i}',
            'size': 1024 * 1024 * i,
            'version': {
                'id': 'version-123',
                'version': 1,
                'asset': {
                    'id': 'asset-123',
                    'name': 'test_asset'
                }
            }
        }
        for i in range(1, 11)  # 10 components
    ]


@pytest.fixture
def mock_job():
    """Create a mock ftrack Job."""
    job_data = {
        'id': 'job-123',
        'status': 'running',
        'data': json.dumps({
            'description': 'Test sync job',
            'requested_by': 'requester-456'
        }),
        'user': {'id': 'user-123', 'username': 'testuser'}
    }

    job = Mock()

    # Make job behave like a dict
    def getitem(key):
        return job_data[key]

    def setitem(key, value):
        job_data[key] = value

    def get(key, default=None):
        return job_data.get(key, default)

    job.__getitem__ = getitem
    job.__setitem__ = setitem
    job.get = get

    return job


@pytest.fixture
def mock_session_with_entities(mock_session, mock_user, mock_location, mock_job):
    """Create a mock session with query/get/create methods."""

    # Mock query to return user
    def mock_query(query_string):
        result = Mock()
        if 'User' in query_string:
            result.first = Mock(return_value=mock_user)
            result.all = Mock(return_value=[mock_user])
        elif 'Location' in query_string:
            result.all = Mock(return_value=[mock_location])
        return result

    mock_session.query = mock_query

    # Mock get to return entities by ID
    def mock_get(entity_type, entity_id):
        if entity_type == 'Job':
            # Return a fresh mock Job each time (simulates re-query)
            fresh_job = Mock()
            fresh_job['id'] = entity_id
            fresh_job['status'] = 'running'
            fresh_job['data'] = '{}'
            fresh_job.__setitem__ = Mock()
            return fresh_job
        elif entity_type == 'Location':
            return mock_location
        elif entity_type == 'Component':
            return {
                'id': entity_id,
                'name': f'component_{entity_id}',
                'size': 1024,
                'version': None
            }
        elif entity_type == 'User':
            return mock_user

    mock_session.get = mock_get

    # Mock create to return new Job
    def mock_create(entity_type, data):
        if entity_type == 'Job':
            job_data = {
                'id': f'job-{id(data)}',
                'status': data.get('status', 'running'),
                'data': data.get('data', '{}'),
                'user': data.get('user')
            }
            new_job = Mock()
            new_job.__getitem__ = lambda self, key: job_data[key]
            new_job.__setitem__ = lambda self, key, value: job_data.__setitem__(key, value)
            new_job.get = lambda key, default=None: job_data.get(key, default)
            return new_job

    mock_session.create = mock_create

    return mock_session
