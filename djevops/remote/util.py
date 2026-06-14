from grp import getgrnam
from pwd import getpwnam
from subprocess import PIPE, STDOUT, CalledProcessError

import os
import subprocess

def run(cmd, ignore_errors=(), env=None):
    shell = isinstance(cmd, str)
    try:
        return subprocess.run(
            cmd, shell=shell, stdout=PIPE, stderr=STDOUT, text=True, check=True,
            env=env
        ).stdout.strip()
    except CalledProcessError as e:
        if e.returncode not in ignore_errors:
            raise

def chown(path, user_name=None, group_name=None):
    uid = -1 if user_name is None else getpwnam(user_name).pw_uid
    gid = -1 if group_name is None else getgrnam(group_name).gr_gid
    os.chown(path, uid, gid)
