from djevops.config import get_services_users_envs, get_django_service
from djevops.util import git, get_apt_install_cmd, run_in_django_shell, \
    run_silently
from functools import partial
from os import remove, makedirs
from os.path import dirname, exists
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

SECRETS_NAME_RE = r'^[A-Z][A-Z0-9_]+$'

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
                'type': 'django'
            }
        }
    }
    makedirs('djevops', exist_ok=True)
    with open('djevops/deploy.yml', 'w') as f:
        f.write(yaml.dump(deploy_yml))
    print('Created djevops/deploy.yml')
    print('Created djevops/secrets.py')
    print(f'To deploy your Django app to a server, run: djevops deploy')

def deploy(verbose=False, dry_run=False):
    deploy_yml = 'djevops/deploy.yml'
    with open(deploy_yml) as f:
        deploy_config = yaml.safe_load(f)
    secrets = get_secrets('djevops/secrets.py')

    check_config(deploy_config, secrets)

    if dry_run:
        return

    server = deploy_config['server']
    install_djevops_on_server('root', server, verbose)
    rsync('-a', deploy_yml, f'root@{server}:/root/deploy.yml')

    secrets_json = NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    json.dump(secrets, secrets_json, indent=2, sort_keys=True)
    secrets_json.close()
    try:
        rsync('-a', secrets_json.name, f'root@{server}:/root/secrets.json')
    finally:
        remove(secrets_json.name)

    run_with_djevops_venv(
        'root', server, 'python -m djevops.remote.deploy', verbose
    )

def check_config(deploy_config, secrets):
    server_ip = deploy_config.get('server')
    if not server_ip or server_ip == SAMPLE_SERVER_IP:
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

    user_envs = get_services_users_envs(deploy_config, secrets)
    django_env = user_envs[django_service_name][1]

    has_db = bool(deploy_config.get('db'))

    # Ensure `djevops.check_django_settings` is loadable:
    django_shell_env = django_env | {'PYTHONPATH': ':'.join(sys.path)}
    error_msg = run_in_django_shell([
        'from djevops.check_django_settings import main',
        f'main({server_ip!r}, {has_db})',
    ], env=django_shell_env)
    if error_msg:
        raise CommandError(error_msg)

def install_djevops_on_server(user, host, verbose):
    ssh_ = lambda cmd: ssh(user, host, cmd, verbose)
    ssh_(get_apt_install_cmd('rsync'))
    ssh_(
        'command -v uv >/dev/null 2>&1 || '
        'curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1'
    )
    rsync(
        '-ra',
        dirname(__file__) + '/',
        f'{user}@{host}:/opt/djevops/',
        "--include=**.gitignore",
        "--exclude=/.git",
        "--exclude=.venv",
        "--filter=:- .gitignore",
        "--delete-after"
    )
    ssh_('cd /opt/djevops && ~/.local/bin/uv sync')

def get_secrets(path):
    if not exists(path):
        return {}
    return {
        k: v for k, v in run_path(path).items() if re.match(SECRETS_NAME_RE, k)
    }

def run_with_djevops_venv(user, host, cmd, verbose):
    ssh(user, host, f'/opt/djevops/.venv/bin/{cmd}', verbose)

def rsync(*args):
    ssh_cmd = get_ssh_command()
    extra_rsync_args = [] if ssh_cmd == 'ssh' else ['-e', ssh_cmd]
    run_silently(['rsync', *extra_rsync_args, *args])

def ssh(user, host, cmd, verbose):
    ssh_cmd = get_ssh_command()
    run_ = partial(run, check=True) if verbose else run_silently
    run_(f'{ssh_cmd} {user}@{host} {quote(cmd)}', shell=True)

def get_ssh_command():
    try:
        return os.environ['DJEVOPS_SSH_COMMAND']
    except KeyError:
        return 'ssh'

def main():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print('Usage: djevops init|deploy [--verbose]')
        sys.exit(0)
    command = sys.argv[1]
    verbose = len(sys.argv) == 3 and sys.argv[2] == '--verbose'
    try:
        if command == 'init':
            init()
        elif command == 'deploy':
            deploy(verbose)
        else:
            raise CommandError(f'Unknown command: {command}')
    except CommandError as e:
        sys.stderr.write(e.args[0] + '\n')
        sys.exit(1)

if __name__ == '__main__':
    main()
