import json
import yaml

SQLITE_DB_FILE = '/var/lib/django/db.sqlite3'

def get_deploy_config():
    with open('/root/deploy.yml') as f:
        return yaml.safe_load(f)

def get_secrets():
    with open('/root/secrets.json') as f:
        return json.load(f)

# TODO: Move this out of remote.
def get_services_users_envs(config, secrets):
    result = {}
    for service_name, service in config['services'].items():
        env_config = service.get('env', {})
        if list(env_config) == ['inherit']:
            user, env = result[env_config['inherit']]
        else:
            user = service_name
            env = {
                'SQLITE_DB_FILE': SQLITE_DB_FILE,
                'STATIC_ROOT': '/srv/static',
                'PATH': '/srv/venv/bin:$PATH'
            }
            env.update(env_config.get('clear', {}))
            for secret_name in env_config.get('secret', []):
                env[secret_name] = secrets[secret_name]
        result[service_name] = (user, env)
    return result
