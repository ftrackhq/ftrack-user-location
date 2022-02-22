# :coding: utf-8
# :copyright: Copyright (c) 2014-2021 ftrack

import sys
import os
import re
import shutil

from pkg_resources import parse_version
try:
    from pip.__main__ import _main as pip_main
except ImportError:
    from pip import main as pip_main

from setuptools import setup, find_packages, Command
import subprocess


ROOT_PATH = os.path.dirname(os.path.realpath(__file__))
BUILD_PATH = os.path.join(ROOT_PATH, 'build')
SOURCE_PATH = os.path.join(ROOT_PATH, 'source')
README_PATH = os.path.join(ROOT_PATH, 'README.rst')
RESOURCE_PATH = os.path.join(ROOT_PATH, 'resource')
HOOK_PATH = os.path.join(RESOURCE_PATH, 'hook')
LOCATION_PATH = os.path.join(RESOURCE_PATH, 'location')

# Read version from source.
with open(os.path.join(
    SOURCE_PATH, 'ftrack_user_location', '_version.py'
)) as _version_file:
    VERSION = re.match(
        r'.*__version__ = \'(.*?)\'', _version_file.read(), re.DOTALL
    ).group(1)


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

        subprocess.check_call(
            [
                sys.executable, '-m', 'pip', 'install','.','--target',
                os.path.join(STAGING_PATH, 'dependencies')
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


# Call main setup.
setup(
    name='ftrack-user-location',
    version=VERSION,
    description='ftrack user location.',
    long_description=open(README_PATH).read(),
    keywords='ftrack, integration, connect, location, structure',
    url='https://bitbucket.org/ftrack/ftrack-somehwere',
    author='ftrack',
    author_email='support@ftrack.com',
    license='Apache License (2.0)',
    packages=find_packages(SOURCE_PATH),
    package_dir={
        '': 'source'
    },
    install_requires=[
        'ftrack-action-handler',
        'ftrack-python-api',
        'ftrack-s3-accessor'
    ],
    tests_require=[
    ],
    zip_safe=False,
    cmdclass={
        'build_plugin': BuildPlugin,
    },
    python_requires='>= 3.0, < 4.0'
)
