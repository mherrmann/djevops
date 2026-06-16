from botocore.config import Config
from contextlib import closing, contextmanager
from djevops.__main__ import CommandError, init, deploy, getbackup
from djevops.config import SQLITE_DB_FILE
from djevops.remote.actions import MANAGE_SH
from djevops.util import git, run_silently
from dnsimple import Client as DNSimpleClient
from dnsimple.struct.zone_record import ZoneRecordInput
from hcloud import Client as HetznerClient
from hcloud._exceptions import APIException
from hcloud.images import Image
from hcloud.server_types import ServerType
from imaplib import IMAP4_SSL
from os import chdir, makedirs, remove
from os.path import join
from pathlib import Path
from shlex import quote
from subprocess import DEVNULL, run, CalledProcessError
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import time, sleep, monotonic
from unittest import TestCase

import boto3
import celery
import django
import os
import requests
import sqlite3
import tomli_w
import tomllib
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

S3_DB_BACKUP_DIR = 'db-backup'

# Can use (non-business) Gmail for these: smtp.gmail.com, imap.gmail.com.
# The user is the email address. The password is an "app password".
SMTP_HOST = os.environ['SMTP_HOST']
IMAP_HOST = os.environ['IMAP_HOST']
EMAIL_USER = os.environ['EMAIL_USER']
EMAIL_PASSWORD = os.environ['EMAIL_PASSWORD']

QUIET = True

GUNICORN_VERSION = '24.1.1'


class _DjevopsTest(TestCase):

    DJANGO_PROJECT_NAME = 'testproject'
    DJANGO_APP_NAME = 'testapp'

    SETTINGS_PY_RELPATH = f'{DJANGO_PROJECT_NAME}/settings.py'

    def expect_init_error(self, message):
        with self._expect_command_error(message):
            init()

    def expect_deploy_error(self, message):
        with self._expect_command_error(message):
            deploy(QUIET)

    @classmethod
    def start_django_project(cls):
        run_silently([
            'django-admin', 'startproject', cls.DJANGO_PROJECT_NAME, '.'
        ])

    @classmethod
    def start_django_app(cls):
        run_silently([
            'python', 'manage.py', 'startapp', cls.DJANGO_APP_NAME
        ])

    @classmethod
    @contextmanager
    def update_deploy_yml(cls):
        with open('deploy/djevops.yml') as f:
            deploy_yml = yaml.safe_load(f)
        yield deploy_yml
        with open('deploy/djevops.yml', 'w') as f:
            f.write(yaml.dump(deploy_yml))

    @classmethod
    def add_to_settings(cls, lines, do_commit=True):
        with open(cls.SETTINGS_PY_RELPATH, 'a') as f:
            f.write('\n' + '\n'.join(lines))
        if do_commit:
            commit(cls.SETTINGS_PY_RELPATH, 'Add to settings.py')

    def add_to_secrets(self, dict_):
        with open('deploy/secrets.py', 'a') as f:
            for key, value in dict_.items():
                f.write(f'{key} = {value!r}\n')

    @contextmanager
    def _expect_command_error(self, message):
        with self.assertRaises(CommandError) as cm:
            yield
        self.assertEqual(message, cm.exception.args[0])


class OfflineTest(_DjevopsTest):

    def setUp(self):
        super().setUp()
        self.restore_cwd_fn = cd_to_temp_dir()

    def tearDown(self):
        self.restore_cwd_fn()
        super().tearDown()

    def test_init(self):
        self.expect_init_error('This directory is not a Git repository.')
        git('init', '-q')

        self.expect_init_error(
            "This Git repository has no remotes. If you add one, don't forget "
            "to run `git push` after."
        )
        git('remote', 'add', 'origin', 'https://example.com/repo.git')

        self.expect_init_error(
            "There is no manage.py file in the current directory. If you add "
            "one, don't forget to commit *and push* your changes to Git."
        )
        self.start_django_project()

        self.expect_init_error(
            "Please create a pyproject.toml file. Don't forget to commit *and "
            "push* your changes to Git."
        )
        _write_pyproject_toml()

        self.expect_init_error(
            "Please add `django` to [project.dependencies] in pyproject.toml. "
            "Don't forget to commit *and push* your changes to Git."
        )
        _add_dep_to_pyproject_toml(f'Django=={django.get_version()}')

        self.expect_init_error(
            "Please add `gunicorn` to [project.dependencies] in "
            "pyproject.toml. Don't forget to commit *and push* your changes to "
            "Git."
        )
        _add_dep_to_pyproject_toml(f'gunicorn=={GUNICORN_VERSION}')

        git('add', '.')
        git('commit', '-m', 'Initial commit')

        init(quiet=True)

    def test_init_does_not_overwrite(self):
        self.test_init()
        for path in ('deploy/djevops.yml', 'deploy/secrets.py'):
            self.expect_init_error(f'{path} already exists.')
            remove(path)

    def test_deploy(self):
        self.test_init()

        self.expect_deploy_error(
            "Please set your server's IP address in deploy/djevops.yml. For "
            "example:\n"
            "    server: 1.2.3.4"
        )

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['server'] = '1.2.3.4'

        self.expect_deploy_error(
            'Please set Django setting ALLOWED_HOSTS to the list of host '
            'names or IP addresses under which your server is accessible. '
            f'For example, in {self.SETTINGS_PY_RELPATH}:\n\n'
            '    import os\n'
            '    ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(" ")\n\n'
            f'And in deploy/djevops.yml:\n\n'
            '    services:\n'
            '      web:\n'
            '        type: django\n'
            '        env:\n'
            '          clear:\n'
            f'            ALLOWED_HOSTS: "1.2.3.4"\n\n'
            "Don't forget to commit *and push* your changes to Git."
        )

        self.add_to_settings([
            "import os",
            "ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(' ')"
        ])
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['env'] = {
                'clear': {'ALLOWED_HOSTS': '1.2.3.4'}
            }

        expect_deploy_to_succeed = lambda: deploy(QUIET, dry_run=True)
        expect_deploy_to_succeed()

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['env']['clear']['ALLOWED_HOSTS'] = \
                'example.com'

        expect_deploy_to_succeed()

        self.add_to_settings(["STATIC_ROOT = '/some/hardcoded/path'"])

        self.expect_deploy_error(
            'Please set Django setting STATIC_ROOT to the value of '
            'environment variable STATIC_ROOT. For example, in '
            f'{self.SETTINGS_PY_RELPATH}:\n\n'
            '    import os\n'
            '    STATIC_ROOT = os.getenv("STATIC_ROOT")\n\n'
            "Don't forget to commit *and push* your changes to Git."
        )

        self.add_to_settings(["STATIC_ROOT = os.getenv('STATIC_ROOT')"])

        expect_deploy_to_succeed()

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = None

        self.expect_deploy_error(
            "Please remove the `db` section in deploy/djevops.yml or set its "
            "`type` key to `sqlite` or `postgres`. For example:\n"
            "    db:\n"
            "      type: sqlite"
        )
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = {'type': 'sqlite'}

        self.expect_deploy_error(
            "Please set DATABASES['default']['NAME'] in "
            f"{self.SETTINGS_PY_RELPATH} to the value of environment variable "
            "SQLITE_DB_FILE. A good expression is:\n"
            "    os.getenv('SQLITE_DB_FILE') or <what you had before>\n\n"
            "Don't forget to commit *and push* your changes to Git."
        )

        self.add_to_settings([
            "DATABASES['default']['NAME'] = os.getenv('SQLITE_DB_FILE') "
            "or DATABASES['default']['NAME']"
        ])

        expect_deploy_to_succeed()

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = {'type': 'postgres'}
        self.expect_deploy_error(
            f"Please set DATABASES['default']['ENGINE'] in "
            f"{self.SETTINGS_PY_RELPATH} to 'django.db.backends.postgresql'.\n\n"
            f"Don't forget to commit *and push* your changes to Git."
        )


class OnlineTest(_DjevopsTest):

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
            cls.ssh_key = ensure_hetzner_ssh_key_exists(
                HETZNER_API_TOKEN, ssh_key_content, cls.test_name
            )
            cls.cleanup_actions.append(cls.ssh_key.delete)

            with NamedTemporaryFile(delete=False) as known_hosts_file:
                cls.known_hosts_file = known_hosts_file.name
            cls.cleanup_actions.append(lambda: remove(cls.known_hosts_file))

            cls.server = create_hetzner_server(
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
            # In case they're left over from a previous test run:
            cls._delete_db_backups_from_s3()
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
        _write_pyproject_toml()
        _add_dep_to_pyproject_toml(f'django=={django.get_version()}')
        _add_dep_to_pyproject_toml(f'gunicorn=={GUNICORN_VERSION}')
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
    def _delete_remote_branch_if_exists(cls, name):
        try:
            git('push', 'origin', '--delete', name)
        except CalledProcessError:
            pass

    @classmethod
    def _delete_db_backups_from_s3(cls):
        delete_directory_from_s3(
            S3_REGION, S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET,
            S3_DB_BACKUP_DIR
        )

    def tearDown(self):
        super().tearDown()
        # Some tests may set DEBUG to False. Reset it to True.
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['env']['clear']['DEBUG'] = 'True'

    def test_http(self):
        deploy(QUIET)
        response = requests.get(f'http://{self.server_ip}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('The install worked', response.text)

    def test_ssl(self):
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['env']['clear']['ALLOWED_HOSTS'] += \
                f' {self.server_hostname}'
        deploy(QUIET)
        response = requests.get(f'https://{self.server_hostname}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('The install worked', response.text)

    def test_getbackup_without_config(self):
        # `getbackup` should still work without a `backup` entry in the config.
        self._configure_sqlite()
        git('push')
        deploy(QUIET)
        self.assertGreater(
            self._execute_against_sqlite_backup(
                "SELECT COUNT(*) FROM django_migrations"
            ),
            0
        )

    def test_sqlite_backup(self):
        self._configure_sqlite()
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db']['backup'] = \
                self._get_litestream_config(plain_secrets=False)
        self.add_to_secrets({
            'S3_ACCESS_KEY': S3_ACCESS_KEY,
            'S3_SECRET_KEY': S3_SECRET_KEY
        })

        table = self.test_name
        self._upload_mock_sqlite_backup_to_s3(f"CREATE TABLE {table}(id)")

        # The server is shared between tests. An earlier test may have already
        # created the database, in which case the deploy below would skip     
        # restoring our backup. Remove it so the restore actually runs.       
        self._ssh(f'rm -f {SQLITE_DB_FILE}')                                  

        git('push')
        deploy(QUIET)

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
            if self._execute_against_sqlite_backup(count_rows) == 1:
                break
            sleep(1)
        else:
            self.fail(f'Backup was not created')

    def _configure_sqlite(self):
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = {'type': 'sqlite'}
        self.add_to_settings([
            "DATABASES['default']['NAME'] = os.getenv('SQLITE_DB_FILE') "
            "or DATABASES['default']['NAME']"
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
                    'replica': self._get_litestream_config()
                }]
            }))
            run_silently([
                'litestream', 'replicate', '-once', '-config', litestream_yml
            ])

    def _execute_against_sqlite_backup(self, sql):
        getbackup(QUIET, force=True)
        with closing(sqlite3.connect('db.sqlite3')) as connection:
            return connection.execute(sql).fetchone()[0]

    def _get_litestream_config(self, plain_secrets=True):
        return {
            'type': 's3',
            'bucket': S3_BUCKET,
            'access-key-id': \
                S3_ACCESS_KEY if plain_secrets else 'S3_ACCESS_KEY',
            'secret-access-key': \
                S3_SECRET_KEY if plain_secrets else 'S3_SECRET_KEY',
            'path': S3_DB_BACKUP_DIR,
            'region': S3_REGION,
            'endpoint': S3_ENDPOINT,
            'force-path-style': True,
            'sign-payload': True
        }

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
        deploy(QUIET)

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
        deploy(QUIET)

        response = requests.get(
            f'https://{self.server_hostname}/{test_txt_relpath}'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(test_content, response.text)

    def test_celery(self):
        _add_dep_to_pyproject_toml(f'celery[redis]=={celery.__version__}')
        commit('pyproject.toml', 'Add celery')

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['celery'] = {
                'type': 'celery',
                'env': {'inherit': 'web'}
            }
            deploy_yml['redis'] = None

        self.add_to_settings([
            f"CELERY_BROKER_URL = 'redis://localhost'",
            f"CELERY_RESULT_BACKEND = 'redis://localhost'"
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

        tasks_py = Path(self.DJANGO_APP_NAME) / 'tasks.py'
        tasks_py.write_text('\n'.join([
            'from celery import shared_task',
            '@shared_task',
            'def test_task():',
            "    return 'celery works'",
        ]))
        commit(tasks_py, 'Add celery task')

        git('push')
        deploy(QUIET)

        run_task_script = [
            f'from {self.DJANGO_APP_NAME}.tasks import test_task',
            'result = test_task.delay()',
            'print(result.get(timeout=10))'
        ]
        output = self._execute_remote_django_shell(run_task_script, 'web')
        self.assertIn('celery works', output)

    def test_command(self):
        service_name = 'mycmd'
        marker = f'command-works-{self.test_name}'
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services'][service_name] = {
                'type': 'command',
                'command': f"echo {marker} && exec sleep infinity",
                'env': {'inherit': 'web'}
            }

        deploy(QUIET)

        output = self._ssh(f'cat /var/log/{service_name}.log')
        self.assertIn(marker, output)

    def _execute_remote_sql(self, sql, user):
        django_cmd = [
            "from django.db import connection",
            f"result = connection.cursor().execute('{sql}').fetchone()",
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


def ensure_hetzner_ssh_key_exists(api_token, ssh_key_content, name):
    hetzner = HetznerClient(token=api_token)
    try:
        return hetzner.ssh_keys.create(name=name, public_key=ssh_key_content)
    except APIException as e:
        if e.code != 'uniqueness_error':
            raise
        all_keys = hetzner.ssh_keys.get_all()
        for key in all_keys:
            if key.public_key == ssh_key_content:
                return key
        else:
            raise LookupError("SSH key exists but couldn't find it via the API")

def create_hetzner_server(
    api_token, ssh_key, name, server_type='cx23', image='debian-13'
):
    hetzner = HetznerClient(token=api_token)
    response = hetzner.servers.create(
        name=name, server_type=ServerType(name=server_type),
        image=Image(name=image), ssh_keys=[ssh_key]
    )
    return response.server

class DNSimpleARecord:
    @classmethod
    def create(cls, api_token, account_id, domain, subdomain, ip):
        client = DNSimpleClient(access_token=api_token)
        record = client.zones.create_record(
            account_id, domain,
            ZoneRecordInput(subdomain, type='A', content=ip, ttl=60)
        )
        return cls(client, account_id, domain, subdomain, record.data.id)
    def __init__(self, client, account_id, domain, subdomain, record_id):
        self.client = client
        self.account_id = account_id
        self.domain = domain
        self.subdomain = subdomain
        self.record_id = record_id
    def delete(self):
        self.client.zones.delete_record(
            self.account_id, self.domain, self.record_id
        )
    def __str__(self):
        return f'{self.subdomain}.{self.domain}'

def wait_for_server_to_be_ready(
    user, host, ssh_key_path, known_hosts_file, timeout_secs=60
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

def commit(file_path, message):
    if isinstance(file_path, Path):
        file_path = str(file_path)
    git('add', file_path)
    git('commit', '-m', message)

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

def delete_directory_from_s3(
    region, endpoint, access_key, secret_key, bucket, prefix
):
    config = Config(s3={
        'addressing_style': 'path',
        'payload_signing_enabled': True
    })
    s3 = boto3.client(
        's3',
        region_name=region,
        endpoint_url='https://' + endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=config
    )
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = [{'Key': obj['Key']} for obj in page.get('Contents', [])]
        s3.delete_objects(Bucket=bucket, Delete={'Objects': objects})

def _write_pyproject_toml():
    pyproject = {'project': {
        'name': 'test', 'version': '0', 'dependencies': []
    }}
    with open('pyproject.toml', 'wb') as f:
        tomli_w.dump(pyproject, f)

def _add_dep_to_pyproject_toml(dep):
    with open('pyproject.toml', 'rb') as f:
        pyproject = tomllib.load(f)
    pyproject['project']['dependencies'].append(dep)
    with open('pyproject.toml', 'wb') as f:
        tomli_w.dump(pyproject, f)

def cd_to_temp_dir():
    cwd_before = os.getcwd()
    temp_dir = TemporaryDirectory()
    chdir(temp_dir.name)
    def cleanup():
        chdir(cwd_before)
        temp_dir.cleanup()
    return cleanup
