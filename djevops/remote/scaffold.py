from os.path import join

import json
import yaml

STATE_DIR = '/root/.djevops'
DEPLOY_CONFIG_PATH = join(STATE_DIR, 'deploy.yml')
SECRETS_PATH = join(STATE_DIR, 'secrets.json')
COMPONENTS_PATH = join(STATE_DIR, 'components.json')

def get_deploy_config():
    with open(DEPLOY_CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_secrets():
    with open(SECRETS_PATH) as f:
        return json.load(f)

def load_components():
    try:
        with open(COMPONENTS_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_components(components):
    with open(COMPONENTS_PATH, 'w') as f:
        json.dump(components, f, indent=2, sort_keys=True)
