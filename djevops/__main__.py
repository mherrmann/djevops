from argparse import ArgumentParser
from djevops import GIT_HINT, s3
from djevops.backup import as_cron, parse_sync_interval
from djevops.config import get_backup_config, get_services_users_envs, \
    get_django_service, SQLITE_DB_FILE
from djevops.litestream import get_litestream_config
from djevops.remote.scaffold import STATE_DIR, DEPLOY_CONFIG_PATH, SECRETS_PATH
from djevops.util import git, get_apt_install_cmd, prompt_yes_no, \
    run_in_django_shell, run_silently
from functools import partial
from os import remove, makedirs
from os.path import basename, dirname, exists
from runpy import run_path
from shlex import quote, split
from shutil import which
from subprocess import run
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

import json
import os
import re
import sys
import tomllib
import yaml

SAMPLE_SERVER_IP = '0.0.0.0'

SAMPLE_SECRETS_PY = """
# This file lets you store secrets that you can then refer to from your djevops
# config. For example:
#
# DJANGO_SECRET_KEY = '1234...'
#
# The motivation for keeping secrets in a separate file is that you usually do
# not want to commit them to Git. One approach you can use is to hard-code your
# secrets here and only store djevops' djevops.yml file in Git.
#
# Another approach is to read secrets from environment variables. For example:
#
# import os
# MY_SECRET = os.environ['MY_SECRET']
#
# This works if the environment variables are available when you execute
# `djevops deploy`. The produced values are uploaded as constants to your
# server. If all your secrets are read from environment variables in this way,
# then you can consider committing this file to Git.
#
# (Feel free to remove these comments once you are done reading them.)
""".lstrip()

SECRETS_NAME_RE = r'^[A-Z][A-Z0-9_]+$'

class CommandError(Exception):
    pass

def init(quiet=False):
    if not exists('.git'):
        raise CommandError('This directory is not a Git repository.')
    remotes = git('remote').splitlines()
    if not remotes:
        raise CommandError(
            "This Git repository has no remotes. If you add one, don't forget "
            "to run `git push` after."
        )
    if not exists('manage.py'):
        raise CommandError(
            "There is no manage.py file in the current directory. If you add "
            "one, don't forget to commit *and push* your changes to Git."
        )
    deps = _get_declared_dependencies()
    if deps is None:
        raise CommandError(
            'Please create a pyproject.toml or requirements.txt file. '
            + GIT_HINT
        )
    deps, location = deps
    for dep in ('django', 'gunicorn'):
        if not any(re.match(rf'{dep}\b', d, re.IGNORECASE) for d in deps):
            raise CommandError(f'Please add `{dep}` to {location}. ' + GIT_HINT)
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
    for path in ('deploy/djevops.yml', 'deploy/secrets.py'):
        if exists(path):
            raise CommandError(f'{path} already exists.')
    makedirs('deploy', exist_ok=True)
    with open('deploy/djevops.yml', 'w') as f:
        f.write(yaml.dump(deploy_yml, sort_keys=False))
    with open('deploy/secrets.py', 'w') as f:
        f.write(SAMPLE_SECRETS_PY)
    if not quiet:
        print('Created deploy/djevops.yml')
        print('Created deploy/secrets.py')
        print(f'To deploy your Django app to a server, run: djevops deploy')

def _get_declared_dependencies():
    if exists('pyproject.toml'):
        with open('pyproject.toml', 'rb') as f:
            pyproject = tomllib.load(f)
        deps = pyproject.get('project', {}).get('dependencies', [])
        return deps, '[project.dependencies] in pyproject.toml'
    try:
        with open('requirements.txt') as f:
            result = []
            for line in f:
                line = re.sub(r'(^|\s)#.*$', '', line).strip()
                if line and not line.startswith('-'):
                    result.append(line)
            return result, 'requirements.txt'
    except FileNotFoundError:
        return None

def deploy(quiet=False, dry_run=False):
    config, secrets = load_config()

    check_config(config, secrets)

    if dry_run:
        return

    server = config['server']
    install_djevops_on_server('root', server, quiet)
    ssh('root', server, f'mkdir -p {STATE_DIR}', quiet)
    rsync('-a', 'deploy/djevops.yml', f'root@{server}:{DEPLOY_CONFIG_PATH}')

    secrets_json = NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    json.dump(secrets, secrets_json, indent=2, sort_keys=True)
    secrets_json.close()
    try:
        rsync('-a', secrets_json.name, f'root@{server}:{SECRETS_PATH}')
    finally:
        remove(secrets_json.name)

    run_with_djevops_venv(
        'root', server, 'python -u -m djevops.remote.deploy', quiet
    )

def getbackup(quiet=False, force=False):
    config, secrets = load_config()
    db_type = (config.get('db') or {}).get('type')
    if not db_type:
        raise CommandError(
            "The `db` section in deploy/djevops.yml is not configured."
        )
    backup_config = get_backup_config(config, secrets)
    if not backup_config:
        raise CommandError(
            "The `backup` section in the `db` section in deploy/djevops.yml "
            "is not configured."
        )
    if db_type == 'sqlite':
        remote_path = SQLITE_DB_FILE
    else:
        try:
            remote_path = backup_config['path']
        except KeyError:
            raise CommandError(
                "The `path` key is not set in the `backup` section in the "
                "`db` section in deploy/djevops.yml. For example:\n"
                "    db:\n"
                "      backup:\n"
                "        path: db.sql"
            ) from None
    output = basename(remote_path)
    if exists(output):
        if force:
            remove(output)
        elif sys.stdin.isatty():
            if prompt_yes_no(f'{output} already exists. Overwrite?'):
                remove(output)
            else:
                return
        else:
            raise CommandError(f'{output} already exists. Please remove it.')
    if db_type == 'postgres':
        if not s3.download(backup_config, output, remote_path):
            raise CommandError("No backup found.")
    else:
        _restore_with_litestream(backup_config, output)
    if not quiet:
        print(f'Downloaded backup to {output}')

def _restore_with_litestream(backup_config, output):
    if not which('litestream'):
        raise CommandError('Please install https://litestream.io first')
    litestream_config = get_litestream_config(backup_config)
    config_file = NamedTemporaryFile(mode='w', delete=False, suffix='.yml')
    yaml.safe_dump(litestream_config, config_file)
    config_file.close()
    try:
        run_silently([
            'litestream', 'restore', '-config', config_file.name, '-o', output,
            SQLITE_DB_FILE
        ])
    finally:
        remove(config_file.name)

def shell():
    config, _ = load_config()
    try:
        django_service_name, _ = get_django_service(config)
    except LookupError:
        raise CommandError('No Django service found in deploy/djevops.yml')
    server = config['server']
    remote_cmd = 'cd /srv/app && exec python manage.py shell'
    su_cmd = f'su - {django_service_name} -c {quote(remote_cmd)}'
    ssh_cmd = get_ssh_command()
    run(f'{ssh_cmd} -t root@{server} {quote(su_cmd)}', shell=True)

def load_config():
    with open('deploy/djevops.yml') as f:
        config = yaml.safe_load(f)
    secrets = get_secrets('deploy/secrets.py')
    return config, secrets

def check_config(deploy_config, secrets):
    server_ip = deploy_config.get('server')
    if not server_ip or server_ip == SAMPLE_SERVER_IP:
        raise CommandError(
            "Please set your server's IP address in deploy/djevops.yml. For "
            "example:\n"
            "    server: 1.2.3.4"
        )

    try:
        django_service_name, django_service = get_django_service(deploy_config)
    except LookupError:
        raise CommandError(
            'Please add at least one service of type `django` to '
            'deploy/djevops.yml. For example:\n'
            '    services:\n'
            '      web:\n'
            '        type: django'
        )

    user_envs = get_services_users_envs(deploy_config, secrets)
    django_env = user_envs[django_service_name][1]

    if 'db' in deploy_config:
        db = deploy_config['db'] or {}
        db_type = db.get('type')
        if db_type not in ('sqlite', 'postgres'):
            raise CommandError(
                'Please remove the `db` section in deploy/djevops.yml or set '
                'its `type` key to `sqlite` or `postgres`. For example:\n'
                '    db:\n'
                '      type: sqlite'
            )
        backup = db.get('backup')
        if backup:
            sync_interval_str = backup.get('sync-interval')
            if sync_interval_str:
                error = CommandError(
                    f"Invalid `sync-interval`: {sync_interval_str!r}."
                )
                try:
                    sync_interval_secs = parse_sync_interval(sync_interval_str)
                    # Litestream accepts any interval, but PostgreSQL backups
                    # run from cron, so the interval must also be expressible as
                    # a cron schedule.
                    if db_type == 'postgres':
                        as_cron(sync_interval_secs)
                except ValueError:
                    raise error from None
    else:
        db_type = None

    # Ensure `djevops.check_django_settings` is loadable:
    django_shell_env = django_env | {'PYTHONPATH': ':'.join(sys.path)}
    error_msg = run_in_django_shell([
        'from djevops.check_django_settings import main',
        f'main({server_ip!r}, {db_type!r})',
    ], env=django_shell_env)
    if error_msg:
        raise CommandError(error_msg)

def install_djevops_on_server(user, host, quiet):
    ssh_ = lambda cmd: ssh(user, host, cmd, quiet)
    ssh_(get_apt_install_cmd('rsync'))
    ssh_(
        'command -v uv >/dev/null 2>&1 || '
        'curl -LsSf https://astral.sh/uv/install.sh | '
        'env UV_INSTALL_DIR=/usr/local/bin sh >/dev/null 2>&1'
    )
    rsync(
        '-raL',
        dirname(__file__) + '/',
        f'{user}@{host}:/opt/djevops/',
        "--include=**.gitignore",
        "--filter=:- .gitignore",
        "--delete-after"
    )
    ssh_(
        'ln -sf /opt/djevops/pyproject.toml /opt/pyproject.toml && '
        'ln -sf /opt/djevops/uv.lock /opt/uv.lock && '
        'cd /opt && '
        'UV_PROJECT_ENVIRONMENT=/opt/djevops/.venv uv sync -q && '
        'rm /opt/pyproject.toml /opt/uv.lock'
    )

def get_secrets(path):
    if not exists(path):
        return {}
    return {
        k: v for k, v in run_path(path).items() if re.match(SECRETS_NAME_RE, k)
    }

def run_with_djevops_venv(user, host, cmd, quiet):
    ssh(user, host, f'/opt/djevops/.venv/bin/{cmd}', quiet)

def rsync(*args):
    ssh_cmd = get_ssh_command()
    extra_rsync_args = [] if ssh_cmd == 'ssh' else ['-e', ssh_cmd]
    run_silently(['rsync', *extra_rsync_args, *args])

def ssh(user, host, cmd, quiet):
    ssh_cmd = get_ssh_command()
    run_ = run_silently if quiet else partial(run, check=True)
    run_(f'{ssh_cmd} {user}@{host} {quote(cmd)}', shell=True)

def scp(src, dst):
    ssh_opts = split(get_ssh_command())[1:]
    run_silently(['scp', *ssh_opts, src, dst])

def get_ssh_command():
    try:
        return os.environ['DJEVOPS_SSH_COMMAND']
    except KeyError:
        return 'ssh'

def main():
    parser = ArgumentParser(prog='djevops')
    subs = parser.add_subparsers(dest='command', required=True)

    for sub in (
        subs.add_parser('init'),
        subs.add_parser('deploy'),
        subs.add_parser('getbackup'),
    ):
        sub.add_argument('--quiet', action='store_true')
    subs.choices['deploy'].add_argument('--dry-run', action='store_true')
    subs.choices['getbackup'].add_argument('--force', action='store_true')
    subs.add_parser('shell')

    args = parser.parse_args()
    try:
        if args.command == 'init':
            init(args.quiet)
        elif args.command == 'deploy':
            deploy(args.quiet, args.dry_run)
        elif args.command == 'getbackup':
            getbackup(args.quiet, args.force)
        elif args.command == 'shell':
            shell()
    except CommandError as e:
        sys.stderr.write(e.args[0] + '\n')
        sys.exit(1)

if __name__ == '__main__':
    main()
