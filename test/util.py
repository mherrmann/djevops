from pathlib import Path
from djevops.util import git
from imaplib import IMAP4_SSL
from os import chdir
from subprocess import run, DEVNULL
from time import sleep, monotonic
from tempfile import TemporaryDirectory

import tomli_w
import tomllib
import os

def commit(file_path, message):
    if isinstance(file_path, Path):
        file_path = str(file_path)
    git('add', file_path)
    git('commit', '-m', message)

def cd_to_temp_dir():
    cwd_before = os.getcwd()
    temp_dir = TemporaryDirectory()
    chdir(temp_dir.name)
    def cleanup():
        chdir(cwd_before)
        temp_dir.cleanup()
    return cleanup

def write_pyproject_toml():
    pyproject = {'project': {
        'name': 'test', 'version': '0', 'dependencies': []
    }}
    with open('pyproject.toml', 'wb') as f:
        tomli_w.dump(pyproject, f)

def add_dep_to_pyproject_toml(dep):
    with open('pyproject.toml', 'rb') as f:
        pyproject = tomllib.load(f)
    pyproject['project']['dependencies'].append(dep)
    with open('pyproject.toml', 'wb') as f:
        tomli_w.dump(pyproject, f)

def write_requirements_txt(deps):
    with open('requirements.txt', 'w') as f:
        for dep in deps:
            f.write(dep + '\n')

def wait_for_server_to_be_ready(
    user, host, ssh_key_path, known_hosts_file, timeout_secs=90
):
    end_time = monotonic() + timeout_secs
    while monotonic() < end_time:
        cp = run([
            'ssh', '-i', str(ssh_key_path),
            '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'UserKnownHostsFile=' + known_hosts_file,
            '-o', 'ConnectTimeout=5',
            f'{user}@{host}', 'echo ready'
        ], stdout=DEVNULL, stderr=DEVNULL)
        if cp.returncode == 0:
            break
        sleep(1)
    else:
        raise TimeoutError(f'Server not ready after {timeout_secs} seconds')

def wait_for_email(
    imap_host, user, password, subject, delete=False, timeout_secs=60
):
    end_time = monotonic() + timeout_secs
    while monotonic() < end_time:
        with IMAP4_SSL(imap_host) as imap:
            imap.login(user, password)
            imap.select('INBOX')
            _, message_ids = imap.search(None, 'SUBJECT', subject)
            if message_ids[0]:
                if delete:
                    for msg_id in message_ids[0].split():
                        imap.store(msg_id, '+FLAGS', '\\Deleted')
                    imap.expunge()
                return True
        sleep(1)
    return False
