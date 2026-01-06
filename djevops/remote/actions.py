from djevops.remote.scaffold import get_deploy_config, get_secrets, \
    get_services_users_envs
from subprocess import run, PIPE

import json

MANAGE_SH = '/opt/djevops/bin/manage.sh'

def migrate_db():
    _run_manage_sh('migrate')

def collect_static_files():
    static_root = get_django_setting('STATIC_ROOT', {})
    if static_root:
        _run_manage_sh('collectstatic', '--noinput')

def get_django_setting(setting_name, env=None):
    # Use json because it seems a little safer than eval()
    setting_json = run_in_django_shell([
        'from django.conf import settings',
        'import json',
        f'print(json.dumps(settings.{setting_name}))'],
        env
    )
    return json.loads(setting_json)

def run_in_django_shell(cmds, env=None):
    if env is None:
        env = _get_django_env()
    args = [MANAGE_SH, 'shell', '-v', '0', '-c', ' ; '.join(cmds)]
    cp = run(args, env=env, check=True, stdout=PIPE, stderr=PIPE, text=True)
    return cp.stdout.strip()

def _run_manage_sh(*args):
    run([MANAGE_SH] + list(args), env=_get_django_env(), check=True)

def _get_django_env():
    config = get_deploy_config()
    for service_name, service in config['services'].items():
        if service['type'] == 'django':
            django_service = service_name
            break
    else:
        raise LookupError('No Django service found')
    secrets = get_secrets()
    user_envs = get_services_users_envs(config, secrets)
    return user_envs[django_service][1]
