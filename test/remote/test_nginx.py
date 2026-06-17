from djevops.remote.nginx import get_header_name_from_meta_key
from unittest import TestCase

class GetHeaderNameFromMetaKeyTest(TestCase):
    def test_forwarded_proto(self):
        self.assertEqual(
            'X-Forwarded-Proto',
            get_header_name_from_meta_key('HTTP_X_FORWARDED_PROTO')
        )
