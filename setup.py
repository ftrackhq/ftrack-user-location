# :coding: utf-8
# :copyright: Copyright (c) 2014-2021 ftrack

import sys
import os
import re
import shutil
from setuptools import Command, setup
import subprocess

# Python 3.11+ has tomllib built-in, older versions need tomli
try:
    import tomllib
except ImportError:
    import tomli as tomllib


ROOT_PATH = os.path.dirname(os.path.realpath(__file__))
BUILD_PATH = os.path.join(ROOT_PATH, 'build')
SOURCE_PATH = os.path.join(ROOT_PATH, 'source')
RESOURCE_PATH = os.path.join(ROOT_PATH, 'resource')
HOOK_PATH = os.path.join(RESOURCE_PATH, 'hook')
LOCATION_PATH = os.path.join(RESOURCE_PATH, 'location')

# Read version from pyproject.toml
with open(os.path.join(ROOT_PATH, 'pyproject.toml'), 'rb') as f:
    VERSION = tomllib.load(f)['project']['version']

STAGING_PATH = os.path.join(
    BUILD_PATH, 'ftrack-user-location-{0}'.format(VERSION)
)


class BuildPlugin(Command):
    '''Build plugin.'''

    description = 'Download dependencies and build plugin .'

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        '''Run the build step.'''
        # Clean staging path
        shutil.rmtree(STAGING_PATH, ignore_errors=True)

        # Copy hook files
        shutil.copytree(
            HOOK_PATH,
            os.path.join(STAGING_PATH, 'hook')
        )

        shutil.copytree(
            LOCATION_PATH,
            os.path.join(STAGING_PATH, 'location')
        )

        # Install dependencies using uv
        subprocess.check_call(
            [
                'uv', 'pip', 'install', '.', '--target',
                os.path.join(STAGING_PATH, 'dependencies'),
                '--python', sys.executable
            ]
        )

        shutil.make_archive(
            os.path.join(
                BUILD_PATH,
                'ftrack-user-location-{0}'.format(VERSION)
            ),
            'zip',
            STAGING_PATH
        )


# Minimal setup.py shim for custom build_plugin command
# All package metadata is in pyproject.toml
setup(
    cmdclass={
        'build_plugin': BuildPlugin,
    }
)
