from djevops.__main__ import get_secrets
from os import remove
from tempfile import NamedTemporaryFile
from unittest import TestCase


class GetSecretsTest(TestCase):
    def test_nonexistent_file(self):
        self.assertEqual({}, get_secrets('nonexistent.py'))
    def test_empty_file(self):
        self.assertEqual({}, get_secrets(self.temp_file))
    def test_valid_file(self):
        with open(self.temp_file, 'w') as f:
            f.write('MY_SECRET = "1234"')
        self.assertEqual({'MY_SECRET': '1234'}, get_secrets(self.temp_file))
    def setUp(self):
        with NamedTemporaryFile(delete=False, suffix='.py') as f:
            self.temp_file = f.name
    def tearDown(self):
        remove(self.temp_file)
