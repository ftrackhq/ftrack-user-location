#!/usr/bin/env python
# :coding: utf-8
"""Test logging configuration to verify logs go to correct files."""

import logging
import sys
import os

# Add source to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'source'))

# Import the module (this triggers configure_logging)
import ftrack_user_location

# Get loggers
plugin_logger = logging.getLogger('ftrack_user_location')
plugin_sync_logger = logging.getLogger('ftrack_user_location.sync')
ftrack_api_logger = logging.getLogger('ftrack_api')
other_logger = logging.getLogger('some_other_module')

print("\n" + "="*80)
print("LOGGING CONFIGURATION TEST")
print("="*80)

print("\n1. Testing ftrack_user_location logger:")
plugin_logger.debug("DEBUG message from ftrack_user_location")
plugin_logger.info("INFO message from ftrack_user_location")
plugin_logger.warning("WARNING message from ftrack_user_location")
plugin_logger.error("ERROR message from ftrack_user_location")

print("\n2. Testing ftrack_user_location.sync logger (child):")
plugin_sync_logger.debug("DEBUG message from ftrack_user_location.sync")
plugin_sync_logger.info("INFO message from ftrack_user_location.sync")
plugin_sync_logger.warning("WARNING message from ftrack_user_location.sync")
plugin_sync_logger.error("ERROR message from ftrack_user_location.sync")

print("\n3. Testing ftrack_api logger (should NOT go to plugin log):")
ftrack_api_logger.info("INFO message from ftrack_api")
ftrack_api_logger.warning("WARNING message from ftrack_api")

print("\n4. Testing other logger (should NOT go to plugin log):")
other_logger.info("INFO message from some_other_module")
other_logger.warning("WARNING message from some_other_module")

print("\n" + "="*80)
print("LOGGER CONFIGURATION DETAILS")
print("="*80)

def print_logger_info(logger_name):
    logger = logging.getLogger(logger_name)
    print(f"\nLogger: {logger_name}")
    print(f"  Level: {logging.getLevelName(logger.level)}")
    print(f"  Effective Level: {logging.getLevelName(logger.getEffectiveLevel())}")
    print(f"  Propagate: {logger.propagate}")
    print(f"  Handlers: {len(logger.handlers)}")
    for i, handler in enumerate(logger.handlers):
        print(f"    Handler {i+1}: {handler.__class__.__name__}")
        if hasattr(handler, 'baseFilename'):
            print(f"      File: {handler.baseFilename}")
        print(f"      Level: {logging.getLevelName(handler.level)}")
        print(f"      Filters: {len(handler.filters)}")

print_logger_info('ftrack_user_location')
print_logger_info('ftrack_user_location.sync')
print_logger_info('ftrack_api')
print_logger_info('some_other_module')
print_logger_info('')  # Root logger

print("\n" + "="*80)
print("EXPECTED RESULTS")
print("="*80)
print("""
✅ ftrack_user_location logs should:
   - Appear in console
   - Appear in ftrack_user_location.log
   - NOT propagate to root logger (propagate=False)

✅ ftrack_user_location.sync logs should:
   - Appear in console (via parent)
   - Appear in ftrack_user_location.log (via parent)
   - NOT have their own handlers (inherit from parent)

❌ ftrack_api and other logs should:
   - NOT appear in ftrack_user_location.log
   - Use their own handlers (from ftrack Connect or Python defaults)
   - NOT be affected by our configuration
""")

print("\n" + "="*80)
print("CHECK LOG FILE")
print("="*80)

from ftrack_user_location.configure_logging import get_log_directory
log_dir = get_log_directory()
log_file = os.path.join(log_dir, 'ftrack_user_location.log')

print(f"\nLog file location: {log_file}")

if os.path.exists(log_file):
    print("\nLast 20 lines of ftrack_user_location.log:")
    print("-" * 80)
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for line in lines[-20:]:
            print(line.rstrip())
    print("-" * 80)
else:
    print("\n❌ Log file not found!")

print("\n✅ Test complete!")
