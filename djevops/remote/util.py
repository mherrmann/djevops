from subprocess import PIPE, STDOUT, CalledProcessError

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
