from djevops.config import get_services_users_envs, get_django_service
from djevops.remote.scaffold import get_deploy_config, get_secrets
from djevops.util import run_in_django_shell, run_silently
from os.path import exists

import json

MANAGE_SH = '/opt/djevops/bin/manage.sh'

def install_python_deps():
    if exists('/srv/app/pyproject.toml'):
        cmd = 'UV_PROJECT_ENVIRONMENT=/srv/venv uv sync -q --no-install-project'
    else:
        cmd = 'uv pip install -q --python /srv/venv/bin/python -r ' \
              'requirements.txt'
    run_silently(f'cd /srv/app && {cmd}', shell=True)

def migrate_db():
    _run_manage_sh('migrate')

def collect_static_files():
    settings = get_django_settings(['INSTALLED_APPS', 'STATIC_ROOT'])
    if 'django.contrib.staticfiles' not in settings['INSTALLED_APPS']:
        return
    if settings['STATIC_ROOT']:
        _run_manage_sh('collectstatic', '--noinput')

def get_django_setting(setting_name, env=None):
    return get_django_settings([setting_name], env)[setting_name]

# Batched version of get_django_setting for improved performance.
def get_django_settings(setting_names, env=None):
    if env is None:
        env = _get_django_env()
    items = ', '.join(f'{name!r}: settings.{name}' for name in setting_names)
    # Use json because it seems a little safer than eval()
    settings_json = run_in_django_shell([
        'from django.conf import settings',
        'import json',
        f'print(json.dumps({{{items}}}))'],
        '/srv/venv/bin/python', '/srv/app/manage.py', env
    )
    return json.loads(settings_json)

def _run_manage_sh(*args):
    run_silently([MANAGE_SH] + list(args), env=_get_django_env())

def _get_django_env(config=None, secrets=None):
    if config is None:
        config = get_deploy_config()
    if secrets is None:
        secrets = get_secrets()
    django_service_name = get_django_service(config)[0]
    user_envs = get_services_users_envs(config, secrets)
    return user_envs[django_service_name][1]
