from contextlib import contextmanager
from djevops.__main__ import CommandError, init, setup
from djevops.remote.actions import MANAGE_SH
from djevops.util import git, run_silently
from dnsimple import Client as DNSimpleClient
from dnsimple.struct.zone_record import ZoneRecordInput
from hcloud import Client as HetznerClient
from hcloud._exceptions import APIException
from hcloud.images import Image
from hcloud.server_types import ServerType
from imaplib import IMAP4_SSL
from os import remove, chdir
from pathlib import Path
from shlex import quote
from subprocess import DEVNULL, run, CalledProcessError
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import time, sleep
from unittest import TestCase

import django
import os
import requests
import yaml


HETZNER_API_TOKEN = os.environ['HETZNER_API_TOKEN']
DNSIMPLE_TEST_DOMAIN = os.environ['DNSIMPLE_TEST_DOMAIN']
DNSIMPLE_API_TOKEN = os.environ['DNSIMPLE_API_TOKEN']
DNSIMPLE_ACCOUNT_ID = os.environ['DNSIMPLE_ACCOUNT_ID']
TEST_REPO_URL = os.environ['TEST_REPO_URL']

# Can use (non-business) Gmail for these: smtp.gmail.com, imap.gmail.com.
# The user is the email address. The password is an "app password".
SMTP_HOST = os.environ['SMTP_HOST']
IMAP_HOST = os.environ['IMAP_HOST']
EMAIL_USER = os.environ['EMAIL_USER']
EMAIL_PASSWORD = os.environ['EMAIL_PASSWORD']

GUNICORN_VERSION = '24.1.1'

VERBOSE = True


class _TestInTempDir(TestCase):

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.cwd_before = os.getcwd()
        chdir(self.temp_dir.name)

    def tearDown(self):
        chdir(self.cwd_before)
        self.temp_dir.cleanup()


class _DjevopsTest(_TestInTempDir):

    def __init__(self, *args, **kwargs):
        self.test_name = f'djevops-test-{int(time())}'
        super().__init__(*args, **kwargs)

    def tearDown(self):
        self.delete_remote_branch_if_exists(self.test_name)
        super().tearDown()

    def expect_init_error(self, message):
        with self.expect_command_error(message):
            init()

    def expect_setup_error(self, message):
        with self.expect_command_error(message):
            setup(VERBOSE)

    @contextmanager
    def expect_command_error(self, message):
        with self.assertRaises(CommandError) as cm:
            yield
        self.assertEqual(message, cm.exception.args[0])

    @contextmanager
    def update_deploy_yml(self):
        with open('djevops/deploy.yml') as f:
            deploy_yml = yaml.safe_load(f)
        yield deploy_yml
        with open('djevops/deploy.yml', 'w') as f:
            f.write(yaml.dump(deploy_yml))

    def delete_remote_branch_if_exists(self, name):
        try:
            git('branch', '--show-current')
        except CalledProcessError as no_git_repo:
            pass
        else:
            try:
                git('remote', 'get-url', 'origin')
            except CalledProcessError as no_remote:
                pass
            else:
                git('push', 'origin', '--delete', name)


class OfflineTest(_DjevopsTest):

    def test_init(self):
        self.expect_init_error(
            'There is no manage.py file in the current directory. Do you '
            'already have a Django project?'
        )
        run_silently(['django-admin', 'startproject', 'testapp', '.'])

        self.expect_init_error(
            'Please create a requirements.txt file. For example, by running:\n'
            '    pip freeze > requirements.txt'
        )
        open('requirements.txt', 'w').close()

        self.expect_init_error(
            'Please add `django` to your requirements.txt file.'
        )
        with open('requirements.txt', 'w') as f:
            f.write('django==' + django.get_version())

        self.expect_init_error(
            'Please add `gunicorn` to your requirements.txt file.'
        )
        with open('requirements.txt', 'a') as f:
            f.write(f'\ngunicorn=={GUNICORN_VERSION}')

        self.expect_init_error('This directory is not a Git repository.')
        git('init', '-q', '-b', self.test_name)
        git('add', '.')
        git('commit', '-m', 'Initial commit')

        self.expect_init_error(
            "This Git repository has no remotes. If you add one, don't forget "
            "to run `git push` after."
        )
        git('remote', 'add', 'origin', TEST_REPO_URL)
        git('push', '-u', 'origin', self.test_name)

        init()

    def test_setup(self):
        self.test_init()

        self.expect_setup_error(
            "Please set your server's IP address in deploy.yml. For example:\n"
            "    server: 1.2.3.4"
        )

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['server'] = '1.2.3.4'

        self.expect_setup_error(
            'Please set Django setting ALLOWED_HOSTS to the list of domains '
            'under which your server is accessible. For example, in '
            'settings.py:\n\n'
            '    import os\n'
            '    ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(" ")\n\n'
            'And in deploy.yml:\n\n'
            '    services:\n'
            '      web:\n'
            '        type: django\n'
            '        domains: [my.website.com]\n'
            '      env:\n'
            '        clear:\n'
            '          ALLOWED_HOSTS: my.website.com'
        )


class OnlineTest(_DjevopsTest):

    TEST_DIR = Path(__file__).parent

    SSH_PUBLIC_KEY = TEST_DIR / 'id_rsa.pub'
    SSH_PRIVATE_KEY = TEST_DIR / 'id_rsa'
    DEPLOY_YML = TEST_DIR / 'deploy.yml'

    @classmethod
    def setUpClass(cls):
        ssh_key_content = cls.SSH_PUBLIC_KEY.read_text().strip()
        cls.ssh_key = ensure_hetzner_ssh_key_exists(
            HETZNER_API_TOKEN, ssh_key_content, f'djevops-test-{int(time())}'
        )
    
    @classmethod
    def tearDownClass(cls):
        try:
            cls.ssh_key.delete()
        except Exception as e:
            print(f'Warning: Failed to delete SSH key: {e}')

    def setUp(self):
        super().setUp()

        with NamedTemporaryFile(delete=False) as known_hosts_file:
            self.known_hosts_file = known_hosts_file.name

        self.server = create_hetzner_server(
            HETZNER_API_TOKEN, self.ssh_key, self.test_name
        )
        self.server_ip = self.server.public_net.ipv4.ip
        wait_for_server_to_be_ready(
            'root', self.server_ip, self.SSH_PRIVATE_KEY, self.known_hosts_file
        )

        self.dns_record = DNSimpleARecord.create(
            DNSIMPLE_API_TOKEN, DNSIMPLE_ACCOUNT_ID, DNSIMPLE_TEST_DOMAIN,
            self.test_name, self.server_ip
        )

        self.ssh_command = \
            f'ssh -i {self.SSH_PRIVATE_KEY} ' \
            f'-o UserKnownHostsFile={self.known_hosts_file}'
        os.environ['DJEVOPS_SSH_COMMAND'] = self.ssh_command

        self.server_hostname = f'{self.test_name}.{DNSIMPLE_TEST_DOMAIN}'
        self.init_test_app()

    def init_test_app(self):
        run_silently(['django-admin', 'startproject', 'testapp', '.'])
        with open('requirements.txt', 'w') as f:
            f.write(f'django=={django.get_version()}\n')
            f.write(f'gunicorn=={GUNICORN_VERSION}')
        git('init', '-q', '-b', self.test_name)
        git('add', '.')
        git('commit', '-m', 'Initial commit')
        git('remote', 'add', 'origin', TEST_REPO_URL)
        git('push', '-u', 'origin', self.test_name)
        init()

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['server'] = self.server_ip
            deploy_yml['services']['web']['domains'] = [self.server_hostname]
            deploy_yml['services']['web']['env'] = {
                'clear': {
                    'ALLOWED_HOSTS': self.server_hostname
                }
            }

        with open('testapp/settings.py', 'a') as f:
            f.write(
                'import os\n'
                'ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(" ")'
            )

        # TODO: Catch it when the necessary files are not committed.
        commit('testapp/settings.py', 'Set Django setting ALLOWED_HOSTS')

    def ssh(self, cmd):
        return run_silently(
            f'{self.ssh_command} root@{self.server_ip} {quote(cmd)}', shell=True
        )

    def tearDown(self):
        os.environ.pop('DJEVOPS_SSH_COMMAND')
        try:
            self.dns_record.delete()
        except Exception as e:
            print(
                f'Warning: Failed to delete DNS record {self.dns_record}: '
                f'{e}'
            )
        try:
            self.server.delete()
        except Exception as e:
            print(f'Warning: Failed to delete server {self.server}: {e}')
        remove(self.known_hosts_file)
        super().tearDown()

    def test_setup(self):
        # It would be nicer to run these as separate test_ methods, but it would
        # be extremely slow to create and delete the server for each test. If
        # `unittest` had support for parallel execution, it would not be too
        # bad. Alas, it doesn't.
        self._test_web_access()
        self._test_db()
        self._test_email()

    def _test_web_access(self):
        setup(VERBOSE)

        response = requests.get(f'https://{self.server_hostname}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('The install worked', response.text)

    def _test_db(self):
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = {'type': 'sqlite'}

        self.expect_setup_error(
            "Please set DATABASES['default']['NAME'] in settings.py to the "
            "value of environment variable SQLITE_DB_FILE. A good expression "
            "is:\n"
            "    os.getenv('SQLITE_DB_FILE') or <what you had before>"
        )

        with open('testapp/settings.py', 'a') as f:
            f.write(
                "\n"
                "DATABASES['default']['NAME'] = os.getenv('SQLITE_DB_FILE') "
                "or DATABASES['default']['NAME']"
            )

        commit('testapp/settings.py', 'Configure SQLite db file path')

        setup(VERBOSE)

        # Test that the `web` user can write to the database:
        create_superuser_cmd = (
            "DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_PASSWORD=admin "
            f"{MANAGE_SH} createsuperuser --email admin@admin.com --noinput"
        )
        self.ssh(f"su -c '{create_superuser_cmd}' - web")

    def _test_email(self):
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['mail'] = {
                'host': SMTP_HOST,
                'user': 'EMAIL_USER',
                'password': 'EMAIL_PASSWORD',
            }

        with open('djevops/secrets.py', 'w') as f:
            f.write(f'EMAIL_USER = {EMAIL_USER!r}\n')
            f.write(f'EMAIL_PASSWORD = {EMAIL_PASSWORD!r}\n')

        setup(VERBOSE)

        send_mail_script = (
            f'from django.core.mail import send_mail; '
            f'send_mail({self.test_name!r}, "Test body", '
            f'{EMAIL_USER!r}, [{EMAIL_USER!r}])'
        )
        remote_cmd = f"{MANAGE_SH} shell -c {quote(send_mail_script)}"
        self.ssh(remote_cmd)

        email_found = wait_for_email(
            IMAP_HOST, EMAIL_USER, EMAIL_PASSWORD, self.test_name, delete=True
        )
        self.assertTrue(email_found, 'Test email was not received')

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
    start_time = time()
    while time() < start_time + timeout_secs:
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
    git('add', file_path)
    git('commit', '-m', message)
    git('push')

def wait_for_email(
    imap_host, user, password, subject, delete=False, timeout_secs=60
):
    start_time = time()
    while time() < start_time + timeout_secs:
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
