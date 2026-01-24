import json
import yaml

def get_deploy_config():
    with open('/root/deploy.yml') as f:
        return yaml.safe_load(f)

def get_secrets():
    with open('/root/secrets.json') as f:
        return json.load(f)
