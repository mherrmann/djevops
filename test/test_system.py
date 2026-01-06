from djevops.util import copy_with_replace
from dnsimple import Client as DNSimpleClient
from dnsimple.struct.zone_record import ZoneRecordInput
from hcloud import Client as HetznerClient
from hcloud._exceptions import APIException
from hcloud.images import Image
from hcloud.server_types import ServerType
from os import remove, mkdir
from os.path import dirname, join
from pathlib import Path
from subprocess import DEVNULL, run, PIPE, STDOUT
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import time, sleep
from unittest import TestCase

import djevops
import os
import requests
import sys


class SystemTest(TestCase):

    TEST_DIR = Path(__file__).parent

    SSH_PUBLIC_KEY = TEST_DIR / 'id_rsa.pub'
    SSH_PRIVATE_KEY = TEST_DIR / 'id_rsa'
    DEPLOY_YML = TEST_DIR / 'djevops' / 'deploy.yml'

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
        test_name = f'djevops-test-{int(time())}'
        self.server = create_hetzner_server(
            os.environ['HETZNER_API_TOKEN'], self.ssh_key, test_name
        )
        self.server_ip = self.server.public_net.ipv4.ip
        test_domain = os.environ['DNSIMPLE_TEST_DOMAIN']
        self.dns_record = DNSimpleARecord.create(
            os.environ['DNSIMPLE_API_TOKEN'], os.environ['DNSIMPLE_ACCOUNT_ID'],
            test_domain, test_name, self.server_ip
        )
        self.server_hostname = f'{test_name}.{test_domain}'
        with NamedTemporaryFile(delete=False) as known_hosts_file:
            self.known_hosts_file = known_hosts_file.name
        wait_for_server_to_be_ready(
            'root', self.server_ip, self.SSH_PRIVATE_KEY, self.known_hosts_file
        )
        self.temp_dir = TemporaryDirectory()
    
    def tearDown(self):
        try:
            self.dns_record.delete()
        except Exception as e:
            print(
                f'Warning: Failed to delete DNS record {self.dns_record}: {e}'
            )
        try:
            self.server.delete()
        except Exception as e:
            print(f'Warning: Failed to delete server {self.server}: {e}')
        remove(self.known_hosts_file)
        self.temp_dir.cleanup()

    def test_setup(self):
        djevops_dir = join(self.temp_dir.name, 'djevops')
        mkdir(djevops_dir)
        copy_with_replace(self.DEPLOY_YML, join(djevops_dir, 'deploy.yml'), {
            '$SERVER': self.server_ip,
            '$DOMAIN': self.server_hostname
        })

        env = os.environ.copy()
        env['DJEVOPS_SSH_COMMAND'] = \
            f'ssh -i {self.SSH_PRIVATE_KEY} ' \
            f'-o UserKnownHostsFile={self.known_hosts_file}'
        env['PYTHONPATH'] = dirname(djevops.__path__[0])

        result = run(
            [sys.executable, '-m', 'djevops', 'setup'], cwd=self.temp_dir.name,
            env=env, stdout=PIPE, stderr=STDOUT, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout)

        response = requests.get(f'https://{self.server_hostname}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('The install worked', response.text)

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
