#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for validating Job permission and lifecycle fixes.

This script tests the official ftrack pattern implementation:
1. Session user ownership (executor owns Jobs)
2. Job ID storage and re-query pattern
3. Requesting user tracked in Job.data

Usage:
    python test_job_fixes.py

Requirements:
    - ftrack_api installed
    - Valid ftrack credentials (FTRACK_SERVER, FTRACK_API_USER, FTRACK_API_KEY)
"""

import ftrack_api
import json
import os
import sys


def test_job_ownership_pattern():
    """Test that Jobs can be created and updated without permission errors."""

    print("=" * 70)
    print("Testing Job Ownership and Lifecycle Pattern")
    print("=" * 70)

    # Connect to ftrack
    try:
        session = ftrack_api.Session()
        print(f"✓ Connected to ftrack: {session.server_url}")
    except Exception as e:
        print(f"✗ Failed to connect to ftrack: {e}")
        print("\nPlease ensure environment variables are set:")
        print("  - FTRACK_SERVER")
        print("  - FTRACK_API_USER")
        print("  - FTRACK_API_KEY")
        return False

    # Get session user (executor)
    try:
        session_user = session.query(
            'User where username is "{}"'.format(session.api_user)
        ).first()
        print(f"✓ Session user: {session_user['username']} (id: {session_user['id']})")
    except Exception as e:
        print(f"✗ Failed to query session user: {e}")
        return False

    # Simulate a different requesting user (for multi-user test)
    # In real scenario, this would come from event['source']['user']['id']
    requesting_user_id = session_user['id']  # Same user for this test
    print(f"✓ Requesting user ID: {requesting_user_id}")

    # Test 1: Create Job owned by executor
    print("\n" + "-" * 70)
    print("Test 1: Create Job with executor ownership")
    print("-" * 70)

    try:
        job = session.create('Job', {
            'user': session_user,  # Executor owns Job
            'status': 'running',
            'data': json.dumps({
                'description': 'Test sync operation',
                'requested_by': requesting_user_id
            })
        })
        session.commit()

        job_id = job['id']
        print(f"✓ Job created: {job_id}")
        print(f"✓ Job owner: {job['user']['username']}")

        job_data = json.loads(job['data'])
        print(f"✓ Job description: {job_data['description']}")
        print(f"✓ Requesting user tracked: {job_data['requested_by']}")

    except Exception as e:
        print(f"✗ Failed to create Job: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test 2: Re-query Job before updating (lifecycle pattern)
    print("\n" + "-" * 70)
    print("Test 2: Re-query Job before update (official pattern)")
    print("-" * 70)

    try:
        # ✅ Official ftrack pattern: session.get('Job', job_id)
        job = session.get('Job', job_id)
        print(f"✓ Job re-queried successfully")

        # Update Job properties
        job['status'] = 'done'
        job['data'] = json.dumps({
            'description': 'Test sync completed successfully',
            'requested_by': requesting_user_id,
            'components_synced': ['test_component_1', 'test_component_2'],
            'components_failed': []
        })
        session.commit()

        print(f"✓ Job updated successfully")
        print(f"✓ Final status: {job['status']}")

        job_data = json.loads(job['data'])
        print(f"✓ Final description: {job_data['description']}")
        print(f"✓ Components synced: {len(job_data['components_synced'])}")

    except Exception as e:
        print(f"✗ Failed to update Job: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test 3: Multiple updates in sequence
    print("\n" + "-" * 70)
    print("Test 3: Multiple sequential Job updates")
    print("-" * 70)

    try:
        # First update
        job = session.get('Job', job_id)
        job['data'] = json.dumps({
            'description': 'Update 1',
            'requested_by': requesting_user_id
        })
        session.commit()
        print(f"✓ First update successful")

        # Second update
        job = session.get('Job', job_id)
        job['data'] = json.dumps({
            'description': 'Update 2',
            'requested_by': requesting_user_id
        })
        session.commit()
        print(f"✓ Second update successful")

        # Third update
        job = session.get('Job', job_id)
        job['data'] = json.dumps({
            'description': 'Final update',
            'requested_by': requesting_user_id
        })
        session.commit()
        print(f"✓ Third update successful")

    except Exception as e:
        print(f"✗ Failed sequential updates: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Cleanup: Delete test Job
    print("\n" + "-" * 70)
    print("Cleanup")
    print("-" * 70)

    try:
        session.delete(job)
        session.commit()
        print(f"✓ Test Job deleted: {job_id}")
    except Exception as e:
        print(f"⚠ Warning: Could not delete test Job: {e}")
        print(f"  Please manually delete Job {job_id} from ftrack UI")

    return True


def main():
    """Main test runner."""

    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  Job Permission & Lifecycle Fix Validation Test".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "═" * 68 + "╝")
    print("\n")

    success = test_job_ownership_pattern()

    print("\n")
    print("=" * 70)
    if success:
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
        print("\nThe Job ownership and lifecycle fixes are working correctly.")
        print("\nNext steps:")
        print("  1. Test multi-user scenario with two different ftrack users")
        print("  2. Test with actual sync operations (100+ components)")
        print("  3. Verify performance improvements (should be <2 minutes)")
        print("  4. Deploy to pilot users")
        return 0
    else:
        print("❌ TESTS FAILED")
        print("=" * 70)
        print("\nPlease review the errors above and ensure:")
        print("  1. ftrack credentials are valid")
        print("  2. User has permission to create Jobs")
        print("  3. ftrack API version is compatible")
        return 1


if __name__ == '__main__':
    sys.exit(main())
