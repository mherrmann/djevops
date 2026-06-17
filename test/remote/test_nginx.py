from djevops.remote.nginx import get_header_name_from_meta_key, \
    get_nginx_size_from_bytes
from unittest import TestCase

class GetHeaderNameFromMetaKeyTest(TestCase):
    def test_forwarded_proto(self):
        self.assertEqual(
            'X-Forwarded-Proto',
            get_header_name_from_meta_key('HTTP_X_FORWARDED_PROTO')
        )

class GetNginxSizeFromBytesTest(TestCase):
    def test_gigabytes(self):
        self.assertEqual('4G', get_nginx_size_from_bytes(4 * 2 ** 30))
    def test_megabytes(self):
        self.assertEqual('2M', get_nginx_size_from_bytes(2 * 2 ** 20))
    def test_kilobytes(self):
        self.assertEqual('2560K', get_nginx_size_from_bytes(2621440))
    def test_bytes(self):
        self.assertEqual('1234', get_nginx_size_from_bytes(1234))
