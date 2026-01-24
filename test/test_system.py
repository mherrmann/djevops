from contextlib import contextmanager
from djevops.__main__ import CommandError, init, setup
from djevops.util import git
from dnsimple import Client as DNSimpleClient
from dnsimple.struct.zone_record import ZoneRecordInput
from hcloud import Client as HetznerClient
from hcloud._exceptions import APIException
from hcloud.images import Image
from hcloud.server_types import ServerType
from os import remove, chdir
from pathlib import Path
from subprocess import DEVNULL, run, CalledProcessError
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import time, sleep
from unittest import TestCase

import django
import os
import requests
import yaml


class SystemTest(TestCase):

    TEST_DIR = Path(__file__).parent

    SSH_PUBLIC_KEY = TEST_DIR / 'id_rsa.pub'
    SSH_PRIVATE_KEY = TEST_DIR / 'id_rsa'
    DEPLOY_YML = TEST_DIR / 'deploy.yml'

    @classmethod
    def setUpClass(cls):
        ssh_key_content = cls.SSH_PUBLIC_KEY.read_text().strip()
        cls.ssh_key = ensure_hetzner_ssh_key_exists(
            os.environ['HETZNER_API_TOKEN'], ssh_key_content,
            f'djevops-test-{int(time())}'
        )
    
    @classmethod
    def tearDownClass(cls):
        try:
            cls.ssh_key.delete()
        except Exception as e:
            print(f'Warning: Failed to delete SSH key: {e}')

    def setUp(self):
        self.server = self.dns_record = None
        self.test_name = f'djevops-test-{int(time())}'
        self.test_domain = os.environ['DNSIMPLE_TEST_DOMAIN']
        self.server_hostname = f'{self.test_name}.{self.test_domain}'
        with NamedTemporaryFile(delete=False) as known_hosts_file:
            self.known_hosts_file = known_hosts_file.name
        self.temp_dir = TemporaryDirectory()
        self.cwd_before = os.getcwd()
        chdir(self.temp_dir.name)
        os.environ['DJEVOPS_SSH_COMMAND'] = \
            f'ssh -i {self.SSH_PRIVATE_KEY} ' \
            f'-o UserKnownHostsFile={self.known_hosts_file}'

    def create_server(self):
        self.server = create_hetzner_server(
            os.environ['HETZNER_API_TOKEN'], self.ssh_key, self.test_name
        )
        server_ip = self.server.public_net.ipv4.ip
        self.dns_record = DNSimpleARecord.create(
            os.environ['DNSIMPLE_API_TOKEN'], os.environ['DNSIMPLE_ACCOUNT_ID'],
            self.test_domain, self.test_name, server_ip
        )
        wait_for_server_to_be_ready(
            'root', server_ip, self.SSH_PRIVATE_KEY, self.known_hosts_file
        )
        return server_ip

    def tearDown(self):
        self.delete_remote_branch_if_exists(self.test_name)
        remove(self.known_hosts_file)
        chdir(self.cwd_before)
        self.temp_dir.cleanup()
        os.environ.pop('DJEVOPS_SSH_COMMAND')
        if self.dns_record:
            try:
                self.dns_record.delete()
            except Exception as e:
                print(
                    f'Warning: Failed to delete DNS record {self.dns_record}: '
                    f'{e}'
                )
        if self.server:
            try:
                self.server.delete()
            except Exception as e:
                print(f'Warning: Failed to delete server {self.server}: {e}')

    def test_init(self):
        self.expect_init_error(
            'There is no manage.py file in the current directory. Do you '
            'already have a Django project?'
        )
        run(['django-admin', 'startproject', 'testapp', '.'], check=True)

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
            f.write('\ngunicorn==24.1.1')

        self.expect_init_error('This directory is not a Git repository.')
        git('init', '-q', '-b', self.test_name)
        git('add', '.')
        git('commit', '-m', 'Initial commit')

        self.expect_init_error(
            "This Git repository has no remotes. If you add one, don't forget "
            "to run `git push` after."
        )
        git('remote', 'add', 'origin', os.environ['TEST_REPO_URL'])
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

        with open('testapp/settings.py', 'a') as f:
            f.write(
                'import os\n'
                'ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(" ")'
            )

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['domains'] = [self.server_hostname]
            deploy_yml['services']['web']['env'] = {
                'clear': {
                    'ALLOWED_HOSTS': self.server_hostname
                }
            }

        # TODO: Catch it when the necessary files are not committed.
        git('add', 'testapp/settings.py')
        git('commit', '-m', 'Make ready for djevops setup')
        git('push')

        server_ip = self.create_server()
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['server'] = server_ip

        setup()

        response = requests.get(f'https://{self.server_hostname}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('The install worked', response.text)

    def expect_init_error(self, message):
        with self.expect_command_error(message):
            init()

    def expect_setup_error(self, message):
        with self.expect_command_error(message):
            setup()

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
