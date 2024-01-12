# coding: utf-8
from __future__ import absolute_import
from __future__ import unicode_literals

import atexit
import os
import time
import unittest
import platform

import docker
import fs
import semantic_version
import six

try:
    docker_client = docker.from_env(version='auto')
    docker_client.info()
except Exception:
    DOCKER = False
else:
    DOCKER = True

try:
    from unittest import mock   # pylint: disable=unused-import
except ImportError:
    import mock                 # pylint: disable=unused-import

CI = os.getenv('CI', '').lower() == 'true'
FSVERSION = semantic_version.Version(fs.__version__)

if platform.system() == "Windows":
    # When running "pwntr/samba-alpine" docket container on Windows,
    # we cannot bind to ports 135-139, 445 because such ports
    # are used by Windows hosts itself.
    # On Windows, we can only test direct_tcp connection over 
    # the non-standard port, like 10445
    DIRECT_TCP_PORT = 10445
    ports_mapping = {
        '445/tcp': DIRECT_TCP_PORT,
    }
else:
    DIRECT_TCP_PORT = 445
    ports_mapping = {
        '139/tcp': 139, 
        '137/udp': 137, 
        '445/tcp': DIRECT_TCP_PORT,
    }

def get_connection_url(anonymous=False, direct_tcp=False, dir=None):
    if platform.system() == 'Windows' and not direct_tcp:
        raise ValueError("On Windows, only direct_tcp is supported for unit testing")

    if direct_tcp:
        if DIRECT_TCP_PORT == 445:
            # default port can be ommited
            host = f'127.0.0.1'
        else:
            host = f'127.0.0.1:{DIRECT_TCP_PORT}'
    else:
        host = 'SAMBAALPINE'

    if anonymous:
        connection_url = f"msmb://{host}/"
    else:
        user = 'rio'
        passw = 'letsdance'
        connection_url = f"msmb://{user}:{passw}@{host}/"

    if dir:
        connection_url += dir

    if direct_tcp:
        connection_url += '?direct-tcp=True'

    return connection_url


if DOCKER:
    smb_container = docker_client.containers.run(
        "pwntr/samba-alpine", detach=True, remove=True, tty=True, auto_remove=True,
        ports=ports_mapping,
        tmpfs={'/shared': 'size=3G,uid=1000'},
        volumes={
            os.path.abspath(os.path.realpath(os.path.join(__file__, os.path.pardir, "smb.conf"))): {"bind": "/config/smb.conf", "mode": "ro"}
        }
    )
    atexit.register(smb_container.kill)
    time.sleep(5)
