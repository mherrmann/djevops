from djevops.config import get_services_users_envs, get_django_service
from djevops.remote.scaffold import get_deploy_config, get_secrets
from djevops.util import run_in_django_shell, run_silently

import json

MANAGE_SH = '/opt/djevops/bin/manage.sh'

def install_python_deps():
    run_silently([
        '/root/.local/bin/uv', 'pip', 'install', '--python', '/srv/venv',
        '-r', '/srv/app/requirements.txt'
    ])

def migrate_db():
    _run_manage_sh('migrate')

def collect_static_files():
    installed_apps = get_django_setting('INSTALLED_APPS')
    if 'django.contrib.staticfiles' not in installed_apps:
        return
    if get_django_setting('STATIC_ROOT'):
        _run_manage_sh('collectstatic', '--noinput')

def get_django_setting(setting_name, env=None):
    if env is None:
        env = _get_django_env()
    # Use json because it seems a little safer than eval()
    setting_json = run_in_django_shell([
        'from django.conf import settings',
        'import json',
        f'print(json.dumps(settings.{setting_name}))'],
        '/srv/venv/bin/python', '/srv/app/manage.py', env
    )
    return json.loads(setting_json)

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
