SQLITE_DB_FILE = '/var/lib/djevops/db.sqlite3'

DEFAULT_ENV = {
    'SQLITE_DB_FILE': SQLITE_DB_FILE,
    'STATIC_ROOT': '/srv/static',
    'PATH': '/srv/venv/bin:$PATH'
}

def get_services_users_envs(config, secrets):
    result = {}
    services = config['services']
    def resolve(service_name):
        if service_name not in result:
            service = services[service_name]
            env_config = service.get('env', {})
            parent_name = env_config.get('inherit')
            if parent_name:
                user, base = resolve(parent_name)
            else:
                user, base = service_name, DEFAULT_ENV
            given_here = env_config.get('clear', {})
            for secret_name in env_config.get('secret', []):
                given_here[secret_name] = secrets[secret_name]
            if given_here:
                user = service_name
            result[service_name] = (user, {**base, **given_here})
        return result[service_name]
    for service_name in services:
        resolve(service_name)
    return result

def get_django_service(config):
    for service_name, service in config['services'].items():
        if service['type'] == 'django':
            return service_name, service
    raise LookupError('No Django service found')

def interpolate_secrets(dict_, secrets):
    return {
        k: secrets.get(v, v)
        for k, v in dict_.items()
    }
