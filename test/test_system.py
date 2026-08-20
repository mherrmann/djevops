from contextlib import closing
from djevops.__main__ import init, deploy, getbackup
from djevops.config import SQLITE_DB_FILE
from djevops.remote.actions import MANAGE_SH
from djevops import s3
from djevops.util import git, run_silently
from os import remove
from os.path import basename
from pathlib import Path
from shlex import quote
from stat import S_IXUSR
from subprocess import CalledProcessError
from tempfile import NamedTemporaryFile, TemporaryDirectory
from test import hetzner
from test.base import SystemTest
from test.dnsimple import DNSimpleARecord
from test.postgres import query_postgres_dump
from test.s3 import delete_prefix_from_s3
from test.util import commit, cd_to_temp_dir, write_pyproject_toml, \
    add_dep_to_pyproject_toml, wait_for_server_to_be_ready, wait_for_email
from time import time, sleep, monotonic

import celery
import django
import os
import requests
import sqlite3
import yaml


HETZNER_API_TOKEN = os.environ['HETZNER_API_TOKEN']
DNSIMPLE_TEST_DOMAIN = os.environ['DNSIMPLE_TEST_DOMAIN']
DNSIMPLE_API_TOKEN = os.environ['DNSIMPLE_API_TOKEN']
DNSIMPLE_ACCOUNT_ID = os.environ['DNSIMPLE_ACCOUNT_ID']
TEST_REPO_URL = os.environ['TEST_REPO_URL']

S3_BUCKET = os.environ['S3_BUCKET']
S3_ACCESS_KEY = os.environ['S3_ACCESS_KEY']
S3_SECRET_KEY = os.environ['S3_SECRET_KEY']
S3_REGION = os.environ['S3_REGION']
S3_ENDPOINT = os.environ['S3_ENDPOINT']

# Can use (non-business) Gmail for these: smtp.gmail.com, imap.gmail.com.
# The user is the email address. The password is an "app password".
SMTP_HOST = os.environ['SMTP_HOST']
IMAP_HOST = os.environ['IMAP_HOST']
EMAIL_USER = os.environ['EMAIL_USER']
EMAIL_PASSWORD = os.environ['EMAIL_PASSWORD']

MB = 2 ** 20

class OnlineTest(SystemTest):

    TEST_DIR = Path(__file__).parent

    SSH_PUBLIC_KEY = TEST_DIR / 'id_rsa.pub'
    SSH_PRIVATE_KEY = TEST_DIR / 'id_rsa'
    DEPLOY_YML = TEST_DIR / 'deploy.yml'

    @classmethod
    def setUpClass(cls):
        cls.test_name = f'djevopstest{int(time())}'
        cls.cleanup_actions = []
        try:
            ssh_key_content = cls.SSH_PUBLIC_KEY.read_text().strip()
            cls.ssh_key = hetzner.ensure_ssh_key_exists(
                HETZNER_API_TOKEN, ssh_key_content, cls.test_name
            )
            cls.cleanup_actions.append(cls.ssh_key.delete)

            with NamedTemporaryFile(delete=False) as known_hosts_file:
                cls.known_hosts_file = known_hosts_file.name
            cls.cleanup_actions.append(lambda: remove(cls.known_hosts_file))

            cls.server = hetzner.create_server(
                HETZNER_API_TOKEN, cls.ssh_key, cls.test_name
            )
            cls.cleanup_actions.append(cls.server.delete)
            cls.server_ip = cls.server.public_net.ipv4.ip
            wait_for_server_to_be_ready(
                'root', cls.server_ip, cls.SSH_PRIVATE_KEY, cls.known_hosts_file
            )

            cls.dns_record = DNSimpleARecord.create(
                DNSIMPLE_API_TOKEN, DNSIMPLE_ACCOUNT_ID, DNSIMPLE_TEST_DOMAIN,
                cls.test_name, cls.server_ip
            )
            cls.cleanup_actions.append(cls.dns_record.delete)

            cls.ssh_command = \
                f'ssh -i {cls.SSH_PRIVATE_KEY} ' \
                f'-o UserKnownHostsFile={cls.known_hosts_file}'
            cls.users_with_ssh_access = ['root']
            os.environ['DJEVOPS_SSH_COMMAND'] = cls.ssh_command
            cls.cleanup_actions.append(
                lambda: os.environ.pop('DJEVOPS_SSH_COMMAND')
            )

            cls.server_hostname = f'{cls.test_name}.{DNSIMPLE_TEST_DOMAIN}'
            cls.cleanup_actions.append(cls._delete_db_backups_from_s3)
            cls.cleanup_actions.append(
                lambda: cls._delete_remote_branch_if_exists(cls.test_name)
            )
            restore_cwd = cd_to_temp_dir()
            cls.cleanup_actions.append(restore_cwd)
            cls.init_test_app()
        except:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for action in reversed(cls.cleanup_actions):
            try:
                action()
            except Exception as e:
                print(f'Warning: Cleanup action {action.__name__} failed: {e}')

    @classmethod
    def init_test_app(cls):
        cls.start_django_project()
        cls.start_django_app()
        write_pyproject_toml()
        add_dep_to_pyproject_toml(f'django=={django.get_version()}')
        add_dep_to_pyproject_toml(f'gunicorn=={cls.GUNICORN_VERSION}')
        cls.add_to_settings([
            "import os",
            "DEBUG = os.getenv('DEBUG') == 'True'",
            "ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(' ')",
            f"INSTALLED_APPS += [{cls.DJANGO_APP_NAME!r}]"
        ], do_commit=False)
        git('init', '-q', '-b', cls.test_name)
        git('add', '.')
        git('commit', '-m', 'Initial commit')
        git('remote', 'add', 'origin', TEST_REPO_URL)
        git('push', '-u', 'origin', cls.test_name)
        init(quiet=True)

        with cls.update_deploy_yml() as deploy_yml:
            deploy_yml['server'] = cls.server_ip
            deploy_yml['services']['web']['env'] = {
                'clear': {
                    'ALLOWED_HOSTS': cls.server_ip,
                    'DEBUG': 'True'
                }
            }

    @classmethod
    def _get_backup_config(cls, plain_secrets=True):
        return {
            'type': 's3',
            'bucket': S3_BUCKET,
            'access-key-id': \
                S3_ACCESS_KEY if plain_secrets else 'S3_ACCESS_KEY',
            'secret-access-key': \
                S3_SECRET_KEY if plain_secrets else 'S3_SECRET_KEY',
            'path': 'db.sql',
            'region': S3_REGION,
            'endpoint': S3_ENDPOINT,
            'force-path-style': True,
            'sign-payload': True
        }

    @classmethod
    def _delete_remote_branch_if_exists(cls, name):
        try:
            git('push', 'origin', '--delete', name)
        except CalledProcessError:
            pass

    @classmethod
    def _delete_db_backups_from_s3(cls):
        backup_config = cls._get_backup_config()
        remote_path = backup_config['path']
        # SQLite backups are inside remote_path/, PostgreSQL backups are at
        # remote_path. Deleting the prefix removes both.
        delete_prefix_from_s3(backup_config, remote_path)

    def tearDown(self):
        super().tearDown()
        # Some tests may set DEBUG to False. Reset it to True.
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['env']['clear']['DEBUG'] = 'True'

    def test_http(self):
        deploy(self.QUIET)
        response = requests.get(f'http://{self.server_ip}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('The install worked', response.text)

    def test_exceed_upload_size(self):
        # This test checks whether djevops forwards Django setting
        # DATA_UPLOAD_MAX_MEMORY_SIZE to Nginx as client_max_body_size. It
        # exploits the fact that Nginx's default upload limit is 1 MB while
        # Django's is 2.5 MB. A 2 MB upload should therefore go through if and
        # only if djevops did forward the Django setting to Nginx.
        deploy(self.QUIET)
        response = requests.post(
            f'http://{self.server_ip}', data=b'x' * (2 * MB)
        )
        self.assertEqual(200, response.status_code)

    def test_ssl(self):
        self.add_to_settings([
            "SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')",
            "SECURE_SSL_REDIRECT = True"
        ])
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['env']['clear']['ALLOWED_HOSTS'] += \
                f' {self.server_hostname}'
        git('push')
        deploy(self.QUIET)
        response = requests.get(
            f'https://{self.server_hostname}', allow_redirects=False
        )
        # If you get HTTP 301 here, then djevops didn't wire
        # SECURE_PROXY_SSL_HEADER into the Nginx config.
        self.assertEqual(200, response.status_code)
        self.assertIn('The install worked', response.text)

    def test_sqlite_backup(self):
        self._configure_sqlite()
        # An earlier test may have deployed a database. That would make the
        # restore-on-fresh-install during `deploy()` be skipped. Reset the
        # server and S3 so that the backup we upload is actually restored:
        self._ssh('systemctl stop litestream 2>/dev/null || true')
        self._ssh(f'rm -f {SQLITE_DB_FILE}')
        self._test_backup(
            self._upload_mock_sqlite_backup_to_s3,
            self._execute_against_sqlite_backup,
            sync_interval='1s'
        )

    def test_postgres_backup(self):
        self._configure_postgres()
        self._test_backup(
            self._upload_mock_postgres_backup_to_s3,
            self._execute_against_postgres_backup,
            # PostgreSQL doesn't support sub-minute sync intervals.
            sync_interval='1m'
        )

    def _test_backup(
        self, upload_mock_backup_to_s3, execute_against_backup, sync_interval
    ):
        self._delete_db_backups_from_s3()
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db']['backup'] = {
                **self._get_backup_config(plain_secrets=False),
                'sync-interval': sync_interval
            }
        self.add_to_secrets({
            'S3_ACCESS_KEY': S3_ACCESS_KEY,
            'S3_SECRET_KEY': S3_SECRET_KEY
        })

        table = self.test_name
        upload_mock_backup_to_s3(f"CREATE TABLE {table}(id integer)")

        git('push')
        deploy(self.QUIET)

        count_rows = f"SELECT COUNT(*) FROM {table}"
        # The following line tests that the backup was restored. (If it weren't,
        # then the command would fail because the table wouldn't exist.)
        num = self._execute_remote_sql(count_rows, 'web')
        # Sanity check. We haven't yet inserted any rows.
        self.assertEqual(0, num)

        # Test that the `web` user can write to the database:
        self._execute_remote_sql(f"INSERT INTO {table} VALUES (1)", 'web')

        end_time = monotonic() + 60
        while monotonic() < end_time:
            if execute_against_backup(count_rows) == 1:
                break
            sleep(1)
        else:
            self.fail(f'Backup was not created')

    def test_email(self):
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['mail'] = {
                'host': SMTP_HOST,
                'user': 'EMAIL_USER',
                'password': 'EMAIL_PASSWORD',
            }

        self.add_to_secrets({
            'EMAIL_USER': EMAIL_USER,
            'EMAIL_PASSWORD': EMAIL_PASSWORD
        })

        git('push')
        deploy(self.QUIET)

        send_mail_script = [
            "from django.core.mail import send_mail",
            f"send_mail({self.test_name!r}, 'Test body', {EMAIL_USER!r}, "
            f"[{EMAIL_USER!r}])"
        ]
        self._execute_remote_django_shell(send_mail_script, 'web')

        email_found = wait_for_email(
            IMAP_HOST, EMAIL_USER, EMAIL_PASSWORD, self.test_name, delete=True
        )
        self.assertTrue(email_found, 'Test email was not received')

    def test_static_files(self):
        self.add_to_settings([
            "STATIC_ROOT = os.getenv('STATIC_ROOT')"
        ])
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['env']['clear']['DEBUG'] = 'False'

        test_txt_relpath = f'static/{self.DJANGO_APP_NAME}/test.txt'
        test_txt = Path(self.DJANGO_APP_NAME) / test_txt_relpath
        test_txt.parent.mkdir(parents=True)
        test_content = 'Hello from static file'
        test_txt.write_text(test_content)
        commit(test_txt, 'Add static file')

        git('push')
        deploy(self.QUIET)

        response = requests.get(
            f'https://{self.server_hostname}/{test_txt_relpath}'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(test_content, response.text)

    def test_celery(self):
        add_dep_to_pyproject_toml(f'celery[redis]=={celery.__version__}')
        commit('pyproject.toml', 'Add celery')

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['celery'] = {
                'type': 'celery',
                'env': {'inherit': 'web'}
            }
            deploy_yml['redis'] = None

        self.add_to_settings([
            f"CELERY_BROKER_URL = 'redis://localhost'",
            f"CELERY_RESULT_BACKEND = 'redis://localhost'",
            "CELERY_BEAT_SCHEDULE = {",
            "    'beat-check': {",
            f"        'task': '{self.DJANGO_APP_NAME}.tasks.beat_task',",
            "        'schedule': 5.0,",
            "    },",
            "}",
        ])

        proj = self.DJANGO_PROJECT_NAME
        celery_py = Path(proj) / 'celery.py'
        celery_py.write_text('\n'.join([
            'import os',
            'import django',
            'from celery import Celery',
            f"os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{proj}.settings')",
            'django.setup()',
            f"app = Celery('{proj}')",
            "app.config_from_object('django.conf:settings', namespace='CELERY')",
            'app.autodiscover_tasks()',
        ]))
        commit(celery_py, 'Add celery.py')

        init_py = Path(proj) / '__init__.py'
        init_py.write_text('from .celery import app as celery_app')
        commit(init_py, 'Add __init__.py')

        marker = f'beat-works-{self.test_name}'
        tasks_py = Path(self.DJANGO_APP_NAME) / 'tasks.py'
        tasks_py.write_text('\n'.join([
            'from celery import shared_task',
            '@shared_task',
            'def beat_task():',
            f"    return {marker!r}",
        ]))
        commit(tasks_py, 'Add celery task')

        git('push')
        deploy(self.QUIET)

        self.assertIn('RUNNING', self._ssh('supervisorctl status celery-beat'))

        end_time = monotonic() + 30
        while monotonic() < end_time:
            if marker in self._ssh('cat /var/log/celery.log'):
                break
            sleep(1)
        else:
            self.fail('Celery Beat task did not run')

    def test_command(self):
        service_name = 'mycmd'
        marker = f'command-works-{self.test_name}'
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services'][service_name] = {
                'type': 'command',
                'command': f"echo {marker} && exec sleep infinity",
                'env': {'inherit': 'web'}
            }

        deploy(self.QUIET)

        output = self._ssh(f'cat /var/log/{service_name}.log')
        self.assertIn(marker, output)

    def test_preinstall(self):
        marker = f'/root/preinstall-ran-{self.test_name}'
        preinstall = Path('deploy/preinstall')
        preinstall.write_text(f'#!/bin/bash -e\necho run >> {marker}\n')
        preinstall.chmod(preinstall.stat().st_mode | S_IXUSR)
        try:
            deploy(self.QUIET)
            # A second deploy with an unchanged script must not re-run it.
            deploy(self.QUIET)
            self.assertEqual('1', self._ssh(f'wc -l < {marker}'))
            preinstall.write_text(
                f'#!/bin/bash -e\necho changed run >> {marker}\n'
            )
            deploy(self.QUIET)
            self.assertEqual('2', self._ssh(f'wc -l < {marker}'))
        finally:
            preinstall.unlink()

    def _configure_sqlite(self):
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = {'type': 'sqlite'}
        self.add_to_settings([
            "DATABASES['default'] = {",
            "    'ENGINE': 'django.db.backends.sqlite3',",
            "    'NAME': os.getenv('SQLITE_DB_FILE')",
            "}"
        ])

    def _upload_mock_sqlite_backup_to_s3(self, sql):
        with TemporaryDirectory() as tmp_dir:
            db_file = Path(tmp_dir) / 'db.sqlite3'
            con = sqlite3.connect(db_file)
            con.execute(sql)
            con.commit()
            con.close()
            litestream_yml = Path(tmp_dir) / 'litestream.yml'
            litestream_yml.write_text(yaml.dump({
                'dbs': [{
                    'path': str(db_file),
                    'replica': self._get_backup_config()
                }]
            }))
            run_silently([
                'litestream', 'replicate', '-once', '-config', litestream_yml
            ])

    def _execute_against_sqlite_backup(self, sql):
        getbackup(self.QUIET, force=True)
        with closing(sqlite3.connect('db.sqlite3')) as connection:
            return connection.execute(sql).fetchone()[0]

    def _configure_postgres(self):
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = {'type': 'postgres'}
            deploy_yml['services']['web']['env']['secret'] = ['DB_PASSWORD']
        self.add_to_secrets({'DB_PASSWORD': self.test_name})
        self.add_to_settings([
            "DATABASES['default'] = {",
            "    'ENGINE': 'django.db.backends.postgresql',",
            f"    'NAME': {self.test_name!r},",
            f"    'USER': {self.test_name!r},",
            "    'PASSWORD': os.environ['DB_PASSWORD'],",
            "    'HOST': 'localhost',",
            "}"
        ])
        add_dep_to_pyproject_toml('psycopg[binary]')
        commit('pyproject.toml', 'Add psycopg')

    def _upload_mock_postgres_backup_to_s3(self, sql):
        with NamedTemporaryFile(mode='w', suffix='.sql') as dump_file:
            dump_file.write(sql + ';\n')
            dump_file.flush()
            backup_config = self._get_backup_config()
            remote_path = backup_config['path']
            s3.upload(backup_config, dump_file.name, remote_path)

    def _execute_against_postgres_backup(self, sql):
        getbackup(self.QUIET, force=True)
        sql_file = basename(self._get_backup_config()['path'])
        return query_postgres_dump(sql_file, sql)

    def _execute_remote_sql(self, sql, user):
        django_cmd = [
            "from django.db import connection",
            "cursor = connection.cursor()",
            f"cursor.execute('{sql}')",
            "result = cursor.fetchone() if cursor.description else None",
            "print(result[0] if result is not None else '')"
        ]
        output = self._execute_remote_django_shell(django_cmd, user)
        if output.strip():
            return int(output)

    def _execute_remote_django_shell(self, cmds, user):
        return self._ssh(f"{MANAGE_SH} shell -c {quote('; '.join(cmds))}", user)

    def _ssh(self, cmd, user='root'):
        if user not in self.users_with_ssh_access:
            self._enable_ssh_access(user)
            self.users_with_ssh_access.append(user)
        return run_silently(
            f'{self.ssh_command} {user}@{self.server_ip} {quote(cmd)}',
            shell=True
        )

    def _enable_ssh_access(self, user):
        public_key = Path(self.SSH_PUBLIC_KEY).read_text().strip()
        cmd_as_user = (
            f"cd /home/{user} && mkdir -p .ssh && chmod 700 .ssh && "
            f"echo {quote(public_key)} >> .ssh/authorized_keys && "
            f"chmod 600 .ssh/authorized_keys"
        )
        self._ssh(f'su -c {quote(cmd_as_user)} - {user}')
