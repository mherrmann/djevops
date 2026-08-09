from os.path import join

import json
import pickle
import yaml

STATE_DIR = '/root/.djevops'
DEPLOY_CONFIG_PATH = join(STATE_DIR, 'deploy.yml')
SECRETS_PATH = join(STATE_DIR, 'secrets.json')
COMPONENTS_PATH = join(STATE_DIR, 'components.pickle')

# We have /srv/venv/bin/python on the server, but that's the Django app's
# virtual environment. It does not necessarily have djevops and certainly does
# not have a development version of djevops.
DJEVOPS_PYTHON = '/opt/djevops/.venv/bin/python'

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
