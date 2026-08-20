from djevops.util import is_domain, run_in_django_shell
from os.path import join
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory
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

class RunInDjangoShellTest(TestCase):
    def test_returns_stdout_only(self):
        # Simulate a manage.py whose startup writes to stderr, as happens for
        # instance when a third-party package emits a SyntaxWarning while being
        # byte-compiled on first import.
        output = self._run_with_manage_py(
            'import sys\n'
            'sys.stderr.write("some warning\\n")\n'
            'exec(sys.argv[-1])\n',
            ['print("hello")']
        )
        self.assertEqual('hello', output)
    def test_error_shows_stderr(self):
        with self.assertRaises(CalledProcessError) as cm:
            self._run_with_manage_py(
                'import sys\n'
                'print("on stdout")\n'
                'sys.exit("on stderr")\n',
                ['pass']
            )
        self.assertIn('on stdout', str(cm.exception))
        self.assertIn('on stderr', str(cm.exception))
    def _run_with_manage_py(self, manage_py_contents, cmds):
        with TemporaryDirectory() as tmp_dir:
            manage_py = join(tmp_dir, 'manage.py')
            with open(manage_py, 'w') as f:
                f.write(manage_py_contents)
            return run_in_django_shell(cmds, manage_py=manage_py)
