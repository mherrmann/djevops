def get_django_service(config):
    for service_name, service in config['services'].items():
        if service['type'] == 'django':
            return service_name, service
    raise LookupError('No Django service found')
