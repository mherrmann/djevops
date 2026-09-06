from djevops.__main__ import init, deploy
from djevops.util import git
from os import remove
from test.base import SystemTest
from test.util import cd_to_temp_dir, write_pyproject_toml, \
    add_dep_to_pyproject_toml, write_requirements_txt

import django

class OfflineTest(SystemTest):

    def setUp(self):
        super().setUp()
        self.restore_cwd_fn = cd_to_temp_dir()

    def tearDown(self):
        self.restore_cwd_fn()
        super().tearDown()

    def test_init(self):
        self.expect_init_error('This directory is not a Git repository.')
        git('init', '-q')

        self.expect_init_error(
            "This Git repository has no remotes. If you add one, don't forget "
            "to run `git push` after."
        )
        git('remote', 'add', 'origin', 'https://example.com/repo.git')

        self.expect_init_error(
            "There is no manage.py file in the current directory. If you add "
            "one, don't forget to commit *and push* your changes to Git."
        )
        self.start_django_project()

        self.expect_init_error(
            "Please create a pyproject.toml or requirements.txt file. Don't "
            "forget to commit *and push* your changes to Git."
        )
        write_pyproject_toml()

        self.expect_init_error(
            "Please add `django` to [project.dependencies] in pyproject.toml. "
            "Don't forget to commit *and push* your changes to Git."
        )
        add_dep_to_pyproject_toml(f'Django=={django.get_version()}')

        self.expect_init_error(
            "Please add `gunicorn` to [project.dependencies] in "
            "pyproject.toml. Don't forget to commit *and push* your changes to "
            "Git."
        )
        add_dep_to_pyproject_toml(f'gunicorn=={self.GUNICORN_VERSION}')

        git('add', '.')
        git('commit', '-m', 'Initial commit')

        init(quiet=True)

    def test_init_with_requirements_txt(self):
        git('init', '-q')
        git('remote', 'add', 'origin', 'https://example.com/repo.git')
        self.start_django_project()

        self.expect_init_error(
            "Please create a pyproject.toml or requirements.txt file. Don't "
            "forget to commit *and push* your changes to Git."
        )
        write_requirements_txt([])

        self.expect_init_error(
            "Please add `django` to requirements.txt. Don't forget to commit "
            "*and push* your changes to Git."
        )
        write_requirements_txt([f'Django=={django.get_version()}'])

        self.expect_init_error(
            "Please add `gunicorn` to requirements.txt. Don't forget to commit "
            "*and push* your changes to Git."
        )
        write_requirements_txt([
            f'Django=={django.get_version()}',
            f'gunicorn=={self.GUNICORN_VERSION}',
        ])

        git('add', '.')
        git('commit', '-m', 'Initial commit')

        init(quiet=True)

    def test_init_does_not_overwrite(self):
        self.test_init()
        for path in ('deploy/djevops.yml', 'deploy/secrets.py'):
            self.expect_init_error(f'{path} already exists.')
            remove(path)

    def test_deploy(self):
        self.test_init()

        self.expect_deploy_error(
            "Please set your server's IP address in deploy/djevops.yml. For "
            "example:\n"
            "    server: 1.2.3.4"
        )

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['server'] = '1.2.3.4'

        self.expect_deploy_error(
            'Please set Django setting ALLOWED_HOSTS to the list of host '
            'names or IP addresses under which your server is accessible. '
            f'For example, in {self.SETTINGS_PY_RELPATH}:\n\n'
            '    import os\n'
            '    ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split()\n\n'
            f'And in deploy/djevops.yml:\n\n'
            '    services:\n'
            '      web:\n'
            '        type: django\n'
            '        env:\n'
            '          clear:\n'
            f'            ALLOWED_HOSTS: "1.2.3.4"\n\n'
            "Don't forget to commit *and push* your changes to Git."
        )

        self.add_to_settings([
            "import os",
            "ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(' ')"
        ])
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['env'] = {
                'clear': {'ALLOWED_HOSTS': '1.2.3.4'}
            }

        expect_deploy_to_succeed = lambda: deploy(self.QUIET, dry_run=True)
        expect_deploy_to_succeed()

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['env']['clear']['ALLOWED_HOSTS'] = \
                'example.com'

        expect_deploy_to_succeed()

        self.add_to_settings(["STATIC_ROOT = '/some/hardcoded/path'"])

        self.expect_deploy_error(
            'Please set Django setting STATIC_ROOT to the value of '
            'environment variable STATIC_ROOT. For example, in '
            f'{self.SETTINGS_PY_RELPATH}:\n\n'
            '    import os\n'
            '    STATIC_ROOT = os.getenv("STATIC_ROOT")\n\n'
            "Don't forget to commit *and push* your changes to Git."
        )

        self.add_to_settings(["STATIC_ROOT = os.getenv('STATIC_ROOT')"])

        expect_deploy_to_succeed()

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = None

        self.expect_deploy_error(
            "Please remove the `db` section in deploy/djevops.yml or set its "
            "`type` key to `sqlite` or `postgres`. For example:\n"
            "    db:\n"
            "      type: sqlite"
        )
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = {'type': 'sqlite'}

        self.expect_deploy_error(
            "Please set DATABASES['default']['NAME'] in "
            f"{self.SETTINGS_PY_RELPATH} to the value of environment variable "
            "SQLITE_DB_FILE. A good expression is:\n"
            "    os.getenv('SQLITE_DB_FILE') or <what you had before>\n\n"
            "Don't forget to commit *and push* your changes to Git."
        )

        self.add_to_settings([
            "DATABASES['default']['NAME'] = os.getenv('SQLITE_DB_FILE') "
            "or DATABASES['default']['NAME']"
        ])

        expect_deploy_to_succeed()

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = {'type': 'postgres'}
        self.expect_deploy_error(
            f"Please set DATABASES['default']['ENGINE'] in "
            f"{self.SETTINGS_PY_RELPATH} to 'django.db.backends.postgresql'.\n\n"
            f"Don't forget to commit *and push* your changes to Git."
        )
