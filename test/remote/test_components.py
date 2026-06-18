from djevops.remote.components import ServiceUser
from unittest import TestCase

class BashrcContentsTest(TestCase):
    def test_simple_value(self):
        self.assertEqual('export A=b', self._bashrc_contents({'A': 'b'}))

    def test_value_with_spaces(self):
        self.assertEqual(
            "export A='b c'", self._bashrc_contents({'A': 'b c'})
        )

    def test_value_with_special_characters(self):
        self.assertEqual(
            """export A='a"b$c'""", self._bashrc_contents({'A': 'a"b$c'})
        )

    def test_multiple_values(self):
        self.assertEqual(
            'export A=b\nexport C=d',
            self._bashrc_contents({'A': 'b', 'C': 'd'})
        )

    def _bashrc_contents(self, env):
        return ServiceUser('user', env, 'group')._bashrc_contents
