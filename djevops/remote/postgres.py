from djevops import s3
from djevops.config import get_backup_config
from djevops.remote.actions import get_django_setting
from djevops.remote.scaffold import get_deploy_config, get_secrets
from djevops.remote.util import run as _run
from os import remove
from subprocess import run
from tempfile import NamedTemporaryFile

import os
import sys

def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'backup'
    config = get_deploy_config()
    secrets = get_secrets()
    db_config = get_django_setting('DATABASES')['default']
    if command == 'dump':
        _pg_dump(db_config, sys.stdout)
    elif command == 'backup':
        backup_config = get_backup_config(config, secrets)
        backup(db_config, backup_config)
    else:
        raise SystemExit(f'Unknown command: {command}')

def provision(db_config):
    name = db_config['NAME']
    user = db_config['USER']
    db_existed = _superuser_query(
        f'SELECT 1 FROM pg_database WHERE datname = {_literal(name)}'
    )
    if not _superuser_query(
        f'SELECT 1 FROM pg_roles WHERE rolname = {_literal(user)}'
    ):
        _superuser_query(f'CREATE ROLE {_ident(user)} LOGIN')
    _superuser_query(
        f'ALTER ROLE {_ident(user)} PASSWORD {_literal(db_config["PASSWORD"])}'
    )
    if not db_existed:
        _superuser_query(
            f'CREATE DATABASE {_ident(name)} OWNER {_ident(user)}'
        )
    return bool(db_existed)

def restore(db_config, backup_config):
    dump_file = NamedTemporaryFile(mode='w', delete=False, suffix='.sql')
    try:
        remote_path = backup_config['path']
        if not s3.download(backup_config, dump_file.name, remote_path):
            return False
        _run(
            ['psql', *_conn_args(db_config), '-d', db_config['NAME'],
             '-v', 'ON_ERROR_STOP=1', '-f', dump_file.name],
            env=_password_env(db_config)
        )
    finally:
        remove(dump_file.name)
    return True

def backup(db_config, backup_config):
    dump_file = NamedTemporaryFile(mode='w', delete=False, suffix='.sql')
    try:
        _pg_dump(db_config, dump_file)
        remote_path = backup_config['path']
        s3.upload(backup_config, dump_file.name, remote_path)
    finally:
        remove(dump_file.name)

def _pg_dump(db_config, output):
    run(
        ['pg_dump', *_conn_args(db_config), db_config['NAME']],
        stdout=output, check=True, env=_password_env(db_config)
    )

def _superuser_query(sql):
    return _run(['runuser', '-u', 'postgres', '--', 'psql', '-tAc', sql])

def _conn_args(db_config):
    result = ['-h', db_config.get('HOST') or 'localhost']
    port = db_config.get('PORT')
    if port:
        result += ['-p', str(port)]
    result += ['-U', db_config['USER']]
    return result

def _password_env(db_config):
    return {**os.environ, 'PGPASSWORD': db_config['PASSWORD']}

def _ident(name):
    return '"' + name.replace('"', '""') + '"'

def _literal(value):
    return "'" + value.replace("'", "''") + "'"

if __name__ == '__main__':
    main()
