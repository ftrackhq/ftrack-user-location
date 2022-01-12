====================
ftrack user location
====================

Welcome to the ftrack-user-location.
Please read below how to build , install and setup, before start using it.

What is it for
--------------

(ftrack) User location allows artists to publish to their local machine's file system rather 
than to other central storage scenario, opening up the ability to work from remote or 
deatached locations.

The plugin also provide a secondary sync ('ftrack.sync') location based on Amazon S3, as well as a sync action, 
to allow transfer between any available locations, providing a way to exchange or delivery any published 
material with other users or the studio storage. 

How does it work
----------------

This location uses the highest possible priority available ( 1 -sys.maxint ) to ensure it takes precedence over
virtally any other location setup, such as the `ftrack.centralised-storage-scenario`.

.. note:: 

    If you are using custom Location please ensure you don't have any other location set to priority:  -9223372036854775806

During the plugin registration a new location will be created based on the login name profile in the computer (**<username>.local**), and 
it'll be reflected in the component location shown in the server.


How to build and install
-------------------------

Please refer to `our help pages <https://help.ftrack.com/en/articles/3504354-ftrack-connect-plugins-discovery-installation-and-update>`_.


How to set it up 
-----------------
Once installed a number of settings are needed to be provided in order to be able to sync data.


Environment variables
.....................
For the location to be fully operational, some environment variables are needed to be setup.


Mandatory
^^^^^^^^^

Amazon specific
"""""""""""""""
These environment variables should have to be provided by the owner of the Amazon S3 bucket.
Please refer to the `Amazon IAM credentials page <https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users_create.html>`_ to see to what values these should be set to. 

* **FTRACK_USER_SYNC_LOCATION_AWS_ACCESS_KEY**
* **FTRACK_USER_SYNC_LOCATION_AWS_SECRET_KEY**

ftrack 
""""""
This environment variable is ndded to ensure all the users use the same `bucket name <https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html>`_.
 
* **FTRACK_USER_SYNC_LOCATION_BUCKET_NAME**

.. warning:: 

    The bucket should be created before hand, and ensure is unique.


* **FTRACK_USER_SYNC_LOCATION_PRIORITY**

If this environment variable is set will define the sync location priority, by default is set to 1000.


* **FTRACK_USER_MAIN_LOCATION**

If this environment variable is set, the user location won't be registered, laving any other location taking precendece.
This is useful when runnign connect with the plugin in main studio premises, to allow remote users to pull and push data to the central storage scenario.


* **FTRACK_USER_LOCTION_NAME**

If this environment variable is set, the user location will pick the value set to it.
Otherwise the location name will be generated based on the user logged into ftrack and the hostname

Optional
^^^^^^^^
By default the location will try to create a folder under:

*<user>/Document/local_ftrack_projects*

In case you prefer having the folder set somewhere else, please ensure to set the following environment variable to an existing folder.

**FTRACK_USER_LOCTION_PATH**


Checking is all setup
---------------------
Once all the settings are in place, you should be able to start using the location.

How to test is all up and ready.

1) Use connect to publish a file . This should end up in <user>.local
2) Execute actions on an AssetVersion and select the **ftrack sync tool** and run a transfer between your **<user>.local** to **ftrack.sync**
3) As above, but try to transfer file between two **<user>.local** locations.
