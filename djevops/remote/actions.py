from djevops.remote.scaffold import MANAGE_PY, SERVICES_GROUP, \
    get_django_project_dir, get_uv_env
from djevops.util import run_in_django_shell, run_silently
from os.path import exists, join, realpath

import json

MANAGE_SH = '/opt/djevops/bin/manage.sh'

def install_python_deps():
    project_dir = get_django_project_dir()
    if exists(join(project_dir, 'pyproject.toml')):
        cmd = 'UV_PROJECT_ENVIRONMENT=/srv/venv uv sync -q --no-install-project'
    else:
        cmd = 'uv pip install -q --python /srv/venv/bin/python -r ' \
              'requirements.txt'
    # We need to pass get_uv_env in case the project's .python-version has
    # changed.
    run_silently(cmd, shell=True, cwd=project_dir, env=get_uv_env())

def migrate_db(user, env):
    _run_manage_sh(['migrate'], user, env)

def collect_static_files(user, env):
    settings = get_django_settings(['INSTALLED_APPS', 'STATIC_ROOT'], user, env)
    if 'django.contrib.staticfiles' not in settings['INSTALLED_APPS']:
        return
    if settings['STATIC_ROOT']:
        _run_manage_sh(['collectstatic', '--noinput'], user, env)

def get_django_setting(setting_name, user, env):
    return get_django_settings([setting_name], user, env)[setting_name]

# Batched version of get_django_setting for improved performance.
def get_django_settings(setting_names, user, env):
    items = ', '.join(f'{name!r}: settings.{name}' for name in setting_names)
    return _eval_in_django_shell(
        'from django.conf import settings', f'{{{items}}}', user, env
    )

def get_public_media_url(user, env):
    # djevops may not be installed in the Django app's venv. We could `import`
    # from djevops in the call below. But it would pollute (and potentially
    # clash with) the Django app's namespace. We therefore use run_path(...)
    # instead. This requires that media.py has no dependencies other than Django
    # and the standard library.
    return _eval_in_django_shell(
        'from runpy import run_path',
        "run_path('/opt/djevops/media.py')['get_public_media_url']()",
        user,
        env
    )

def _eval_in_django_shell(import_statement, expression, user, env):
    # Use json because it seems a little safer than eval()
    result_json = run_in_django_shell([
        import_statement,
        'import json',
        f'print(json.dumps({expression}))'],
        '/srv/venv/bin/python',
        # We use realpath(...) because manage.py would otherwise see the symlink
        # as its __file__ and calculate paths relative to where the symlink is.
        realpath(MANAGE_PY),
        env,
        **_get_kwargs_for_running_as(user)
    )
    return json.loads(result_json)

def _run_manage_sh(args, user, env):
    run_silently(
        [MANAGE_SH] + args, env=env, **_get_kwargs_for_running_as(user)
    )

def _get_kwargs_for_running_as(user):
    # Deploys run as root. Files that the Django app creates while it runs would
    # then belong to root, and the app could not access them when it later runs
    # as its service.
    return {'user': user, 'group': user, 'extra_groups': [SERVICES_GROUP]}
