from djevops.config import get_services_users_envs, get_django_service
from djevops.remote.scaffold import get_deploy_config, get_secrets
from djevops.util import run_in_django_shell
from subprocess import run

import json

MANAGE_SH = '/opt/djevops/bin/manage.sh'

def migrate_db():
    _run_manage_sh('migrate')

def collect_static_files():
    static_root = get_django_setting('STATIC_ROOT', {})
    if static_root:
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
    run([MANAGE_SH] + list(args), env=_get_django_env(), check=True)

def _get_django_env(config=None, secrets=None):
    if config is None:
        config = get_deploy_config()
    if secrets is None:
        secrets = get_secrets()
    django_service_name = get_django_service(config)[0]
    user_envs = get_services_users_envs(config, secrets)
    return user_envs[django_service_name][1]
