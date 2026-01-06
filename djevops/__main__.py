from os import remove
from os.path import dirname, exists
from runpy import run_path
from shlex import quote
from subprocess import run
from tempfile import NamedTemporaryFile

import json
import os
import sys
import yaml

def main():
    assert sys.argv[1] == 'setup'

    deploy_yml = 'djevops/deploy.yml'
    with open(deploy_yml) as f:
        server = yaml.safe_load(f)['server']

    install_djevops_on_server('root', server)
    rsync('-a', deploy_yml, f'root@{server}:/root/deploy.yml')

    secrets = get_secrets('djevops/secrets.py')
    secrets_json = NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    json.dump(secrets, secrets_json, indent=2, sort_keys=True)
    secrets_json.close()
    try:
        rsync('-a', secrets_json.name, f'root@{server}:/root/secrets.json')
    finally:
        remove(secrets_json.name)

    run_with_djevops_venv('root', server, 'python -m djevops.remote.setup')

def install_djevops_on_server(user, host):
    ssh_ = lambda cmd: ssh(user, host, cmd)
    print('Updating system...')
    ssh_('apt-get update -qq')
    print('Installing rsync and python3-venv...')
    ssh_(
        'DEBIAN_FRONTEND=noninteractive '
        'apt-get install rsync python3-venv -yqq > /dev/null'
    )
    print('Copying djevops to server...')
    rsync(
        '-ra',
        dirname(dirname(__file__)) + '/',
        f'{user}@{host}:/opt/djevops/',
        "--include=**.gitignore",
        "--exclude=/.git",
        "--filter=:- .gitignore",
        "--delete-after"
    )
    print('Creating virtual environment...')
    ssh_(
        'cd /opt/djevops && ' +
        'python3 -m venv venv && ' +
        'venv/bin/pip install -qqq -r requirements/base.txt'
    )

def get_secrets(path):
    if not exists(path):
        return {}
    return run_path(path)

def run_with_djevops_venv(user, host, cmd):
    ssh(
        user, host,
        f'source /opt/djevops/venv/bin/activate && '
        f'PYTHONPATH=/opt/djevops {cmd}'
    )

def rsync(*args):
    ssh_cmd = get_ssh_command()
    extra_rsync_args = [] if ssh_cmd == 'ssh' else ['-e', ssh_cmd]
    run(['rsync', *extra_rsync_args, *args], check=True)

def ssh(user, host, cmd):
    ssh_cmd = get_ssh_command()
    return run(f'{ssh_cmd} {user}@{host} {quote(cmd)}', shell=True, check=True)

def get_ssh_command():
    try:
        return os.environ['DJEVOPS_SSH_COMMAND']
    except KeyError:
        return 'ssh'

if __name__ == '__main__':
    main()
