from djevops.remote.actions import run_in_django_shell, \
    get_django_service
from djevops.remote.scaffold import get_services_users_envs
from djevops.util import git
from os import remove, makedirs
from os.path import dirname, exists, join
from runpy import run_path
from shlex import quote
from subprocess import run
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

import json
import os
import re
import sys
import yaml

SAMPLE_SERVER_IP = '0.0.0.0'
SAMPLE_DOMAIN = 'example.com'

class CommandError(Exception):
    pass

def init():
    if not exists('manage.py'):
        raise CommandError(
            'There is no manage.py file in the current directory. Do you '
            'already have a Django project?'
        )
    if not exists('requirements.txt'):
        raise CommandError(
            'Please create a requirements.txt file. For example, by running:\n'
            '    pip freeze > requirements.txt'
        )
    with open('requirements.txt') as f:
        requirements = f.read()
    for dep in ('django', 'gunicorn'):
        if not re.search(rf'^{dep}\s*\b', requirements, re.MULTILINE):
            raise CommandError(
                f'Please add `{dep}` to your requirements.txt file.'
            )
    if not exists('.git'):
        raise CommandError('This directory is not a Git repository.')
    remotes = git('remote').splitlines()
    if not remotes:
        raise CommandError(
            "This Git repository has no remotes. If you add one, don't forget "
            "to run `git push` after."
        )
    remote = remotes[0]
    remote_url = git('remote', 'get-url', remote)
    if remote_url.startswith('https://'):
        parsed_url = urlparse(remote_url)
        git_server = parsed_url.hostname
        git_repo = parsed_url.path.lstrip('/')
    else:
        m = re.match(r'git@([^:]+):(.*)$', remote_url)
        if not m:
            raise CommandError(f'Invalid Git remote URL: {remote_url}')
        git_server = m.group(1)
        git_repo = m.group(2)
    if git_server == 'github.com' and git_repo.endswith('.git'):
        git_repo = git_repo[:-4]
    git_config = {}
    if git_server != 'github.com':
        git_config['server'] = git_server
    git_config['repo'] = git_repo
    git_config['branch'] = git('branch', '--show-current')
    deploy_yml = {
        'server': SAMPLE_SERVER_IP,
        'git': git_config,
        'services': {
            'web': {
                'type': 'django',
                'domains': [SAMPLE_DOMAIN],
            }
        }
    }
    makedirs('djevops', exist_ok=True)
    with open('djevops/deploy.yml', 'w') as f:
        f.write(yaml.dump(deploy_yml))

def setup():
    deploy_yml = 'djevops/deploy.yml'
    with open(deploy_yml) as f:
        deploy_config = yaml.safe_load(f)
    secrets = get_secrets('djevops/secrets.py')

    check_config(deploy_config, secrets)

    server = deploy_config['server']
    install_djevops_on_server('root', server)
    rsync('-a', deploy_yml, f'root@{server}:/root/deploy.yml')

    secrets_json = NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    json.dump(secrets, secrets_json, indent=2, sort_keys=True)
    secrets_json.close()
    try:
        rsync('-a', secrets_json.name, f'root@{server}:/root/secrets.json')
    finally:
        remove(secrets_json.name)

    run_with_djevops_venv('root', server, 'python -m djevops.remote.setup')

def check_config(deploy_config, secrets):
    server = deploy_config.get('server')
    if not server or server == SAMPLE_SERVER_IP:
        raise CommandError(
            "Please set your server's IP address in deploy.yml. For example:\n"
            "    server: 1.2.3.4"
        )

    try:
        django_service_name, django_service = get_django_service(deploy_config)
    except LookupError:
        raise CommandError(
            'Please add at least one service of type `django` to deploy.yml. '
            'For example:\n'
            '    services:\n'
            '      web:\n'
            '        type: django'
        )

    domains = django_service.get('domains')
    if not domains or not isinstance(domains, list):
        raise CommandError(
            'Please set `domains` on the service of type `django` in '
            'deploy.yml to the list of domains under which your server is '
            'accessible. For example:\n'
            '    services:\n'
            '      web:\n'
            '        type: django\n'
            '        domains: [my.website.com]'
        )

    user_envs = get_services_users_envs(deploy_config, secrets)
    django_env = user_envs[django_service_name][1]

    bin_dir = join(dirname(dirname(__file__)), 'bin')
    error_msg = run_in_django_shell([
        'import sys',
        f"sys.path.append('{bin_dir}')",
        'from check_django_settings import main',
        f'main({domains!r})',
    ], env=django_env)
    if error_msg:
        raise CommandError(error_msg)

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
    if len(sys.argv) != 2:
        print('Usage: djevops init|setup')
        sys.exit(0)
    command = sys.argv[1]
    try:
        if command == 'init':
            init()
        elif command == 'setup':
            setup()
        else:
            raise CommandError(f'Unknown command: {command}')
    except CommandError as e:
        print(e.args[0])
        sys.exit(1)
