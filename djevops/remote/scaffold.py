from os.path import dirname, join, realpath

import json
import os
import pickle
import yaml

REPO_DIR = '/srv/app'
# manage.py may not lie at the top level of the Git repository. This symlink
# records where it is. Resolve the symlink before starting anything. Otherwise,
# path calculations in the Django app can see the wrong parent directory.
MANAGE_PY = '/srv/manage.py'

# All services are in this group. It lets them access each other's files.
SERVICES_GROUP = 'djevops'

STATE_DIR = '/root/.djevops'
DEPLOY_CONFIG_PATH = join(STATE_DIR, 'deploy.yml')
SECRETS_PATH = join(STATE_DIR, 'secrets.json')
HOOK_NAMES = ('pre-install', 'post-install')
COMPONENTS_PATH = join(STATE_DIR, 'components.pickle')

# We have /srv/venv/bin/python on the server, but that's the Django app's
# virtual environment. It does not necessarily have djevops and certainly does
# not have a development version of djevops.
DJEVOPS_PYTHON = '/opt/djevops/.venv/bin/python'

# When the Django app has a .python-version that is different from what the
# server ships, then uv by default installs that Python version into
# /root/.local. The djevops service users do not have permission to access this
# directory. In order to work around this, we instruct uv to install Python in a
# world-readable location.
UV_PYTHON_INSTALL_DIR = '/opt/uv/python'

def get_uv_env(python_install_dir=UV_PYTHON_INSTALL_DIR):
    return os.environ | {'UV_PYTHON_INSTALL_DIR': python_install_dir}

def get_deploy_config():
    with open(DEPLOY_CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_secrets():
    with open(SECRETS_PATH) as f:
        return json.load(f)

def load_components():
    try:
        with open(COMPONENTS_PATH, 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        return {}

def save_components(components):
    with open(COMPONENTS_PATH, 'wb') as f:
        pickle.dump(components, f)

def get_hook_path(name):
    return join(STATE_DIR, name)

def get_django_project_dir():
    return dirname(realpath(MANAGE_PY))
