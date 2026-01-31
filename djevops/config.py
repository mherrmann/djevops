SQLITE_DB_FILE = '/var/lib/django/db.sqlite3'

DEFAULT_ENV = {
    'SQLITE_DB_FILE': SQLITE_DB_FILE,
    'STATIC_ROOT': '/srv/static',
    'PATH': '/srv/venv/bin:$PATH'
}

def get_services_users_envs(config, secrets):
    result = {}
    services = config['services'].items()
    for service_name, service in services:
        env_config = service.get('env', {})
        if list(env_config) == ['inherit']:
            # Handled further below.
            continue
        user = service_name
        env = DEFAULT_ENV.copy()
        env.update(env_config.get('clear', {}))
        for secret_name in env_config.get('secret', []):
            env[secret_name] = secrets[secret_name]
        result[service_name] = (user, env)
    # Do a second pass to handle `inherit`.
    for service_name, service in services:
        env_config = service.get('env', {})
        if list(env_config) != ['inherit']:
            continue
        user, env = result[env_config['inherit']]
        result[service_name] = (user, env)
    return result

def get_django_service(config):
    for service_name, service in config['services'].items():
        if service['type'] == 'django':
            return service_name, service
    raise LookupError('No Django service found')
