from grp import getgrnam
from os import remove, symlink
from pwd import getpwnam
from subprocess import PIPE, STDOUT, CalledProcessError

import os
import subprocess

_ERROR_ALREADY_EXISTS = 9

def run(cmd, ignore_errors=(), env=None, cwd=None):
    shell = isinstance(cmd, str)
    try:
        return subprocess.run(
            cmd, shell=shell, stdout=PIPE, stderr=STDOUT, text=True, check=True,
            env=env, cwd=cwd
        ).stdout.strip()
    except CalledProcessError as e:
        if e.returncode not in ignore_errors:
            raise

def chown(path, user_name=None, group_name=None):
    uid = -1 if user_name is None else getpwnam(user_name).pw_uid
    gid = -1 if group_name is None else getgrnam(group_name).gr_gid
    os.chown(path, uid, gid)

def symlink_force(source, link_name):
    try:
        symlink(source, link_name)
    except FileExistsError:
        remove(link_name)
        symlink(source, link_name)

def ensure_group_exists(group_name):
    run(
        ['groupadd', '--system', group_name],
        ignore_errors=(_ERROR_ALREADY_EXISTS,)
    )

def ensure_user_exists(user_name, group_name):
    run([
        'useradd', '--system', '--gid', group_name, '--shell', '/bin/bash',
        user_name
    ], ignore_errors=(_ERROR_ALREADY_EXISTS,))
