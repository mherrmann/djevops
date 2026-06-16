from contextlib import contextmanager
from djevops.__main__ import CommandError, init, deploy
from djevops.util import run_silently
from unittest import TestCase
from test.util import commit

import yaml


class SystemTest(TestCase):

    QUIET = True
    
    DJANGO_PROJECT_NAME = 'testproject'
    DJANGO_APP_NAME = 'testapp'

    GUNICORN_VERSION = '24.1.1'

    SETTINGS_PY_RELPATH = f'{DJANGO_PROJECT_NAME}/settings.py'

    def expect_init_error(self, message):
        with self._expect_command_error(message):
            init()

    def expect_deploy_error(self, message):
        with self._expect_command_error(message):
            deploy(self.QUIET)

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
