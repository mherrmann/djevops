SQLITE_DB_FILE = '/var/lib/django/db.sqlite3'

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

def get_django_service(config):
    for service_name, service in config['services'].items():
        if service['type'] == 'django':
            return service_name, service
    raise LookupError('No Django service found')
