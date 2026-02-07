from djevops.util import is_domain
from unittest import TestCase

class IsDomainTest(TestCase):
    def test_valid_domain(self):
        self.assertTrue(is_domain('example.com'))
    def test_valid_domain_with_subdomain(self):
        self.assertTrue(is_domain('www.example.com'))
    def test_ip_address(self):
        self.assertFalse(is_domain('1.2.3.4'))
    def test_domain_starting_with_dot(self):
        self.assertFalse(is_domain('.example.com'))
    def test_domain_starting_with_slash(self):
        self.assertFalse(is_domain('-example.com'))
    def test_domain_with_slash(self):
        self.assertTrue(is_domain('my-test-123.example.com'))
