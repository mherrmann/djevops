from contextlib import chdir
from djevops.__main__ import init, deploy, get_deploy_dir
from djevops.util import git
from os import makedirs, remove, rename
from os.path import join, normpath
from test.base import SystemTest
from test.util import cd_to_temp_dir, write_pyproject_toml, \
    add_dep_to_pyproject_toml, write_requirements_txt

import django

class OfflineTest(SystemTest):

    def setUp(self):
        super().setUp()
        self.restore_cwd_fn = cd_to_temp_dir()
        get_deploy_dir.cache_clear()

    def tearDown(self):
        self.restore_cwd_fn()
        super().tearDown()

    def test_init(self):
        self.expect_init_error(
            'fatal: not a git repository (or any of the parent directories): '
            '.git'
        )
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
        self._test_deploy('deploy')

    def test_deploy_with_files_in_subdirectory(self):
        self._test_deploy('deploy/vps')

    def test_deploy_with_files_next_to_manage_py(self):
        self._test_deploy('.')

    def _test_deploy(self, deploy_dir):
        self.test_init()
        if deploy_dir != 'deploy':
            makedirs(deploy_dir, exist_ok=True)
            for name in ('djevops.yml', 'secrets.py'):
                rename(join('deploy', name), join(deploy_dir, name))
            get_deploy_dir.cache_clear()
        config_path = normpath(join(deploy_dir, 'djevops.yml'))

        self.expect_deploy_error(
            f"Please set your server's IP address in {config_path}. For "
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
            f'And in {config_path}:\n\n'
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
            f"Please remove the `db` section in {config_path} or set its "
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

        self.add_to_settings(["MEDIA_URL = '/media/'"])

        self.expect_deploy_error(
            "Because Django setting MEDIA_URL is '/media/', djevops makes all "
            "files in MEDIA_ROOT publicly accessible at that URL. Please set "
            "Django setting MEDIA_ROOT to the value of environment variable "
            f"MEDIA_ROOT. For example, in {self.SETTINGS_PY_RELPATH}:\n\n"
            '    import os\n'
            '    MEDIA_ROOT = os.getenv("MEDIA_ROOT") or <what you had before>'
            "\n\n"
            "If your uploads must stay private, then remove MEDIA_URL instead."
            "\n\nDon't forget to commit *and push* your changes to Git."
        )

        self.add_to_settings(["MEDIA_ROOT = os.getenv('MEDIA_ROOT')"])

        expect_deploy_to_succeed()

        with self.update_deploy_yml() as deploy_yml:
            env = deploy_yml['services']['web']['env']['clear']
            env['MEDIA_ROOT'] = '/srv/uploads/'

        self.expect_deploy_error(
            "Please remove the trailing slash from MEDIA_ROOT in "
            f"{config_path}.\n\n"
            "Don't forget to commit *and push* your changes to Git."
        )

        with self.update_deploy_yml() as deploy_yml:
            del deploy_yml['services']['web']['env']['clear']['MEDIA_ROOT']

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['max-body-size'] = '4G'
        self.expect_deploy_error(
            f"Please set `max-body-size` of service `web` in {config_path} "
            "to a mapping of URL prefixes to sizes. For example:\n"
            "    max-body-size:\n"
            "      /upload/: 4G"
        )
        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['services']['web']['max-body-size'] = \
                {'/upload/': '4G'}
        expect_deploy_to_succeed()

        with self.update_deploy_yml() as deploy_yml:
            deploy_yml['db'] = {'type': 'postgres'}
        self.expect_deploy_error(
            f"Please set DATABASES['default']['ENGINE'] in "
            f"{self.SETTINGS_PY_RELPATH} to 'django.db.backends.postgresql'.\n\n"
            f"Don't forget to commit *and push* your changes to Git."
        )

    def test_project_in_subdirectory(self):
        git('init', '-q')
        git('remote', 'add', 'origin', 'https://example.com/repo.git')
        makedirs('web')
        with chdir('web'):
            self.start_django_project()
            write_requirements_txt([
                f'Django=={django.get_version()}',
                f'gunicorn=={self.GUNICORN_VERSION}',
            ])
            self.add_to_settings(
                ["ALLOWED_HOSTS = ['example.com']"], do_commit=False
            )
            init(quiet=True)
            with self.update_deploy_yml() as deploy_yml:
                deploy_yml['server'] = '1.2.3.4'
            deploy(self.QUIET, dry_run=True)
