from django.conf import settings

import os
import sys

def main(domains, has_db):
    check_allowed_hosts(domains)
    check_staticfiles()
    if has_db:
        check_databases()

def check_staticfiles():
    if 'django.contrib.staticfiles' in settings.INSTALLED_APPS:
        static_root = settings.STATIC_ROOT
        if static_root and static_root != os.getenv('STATIC_ROOT'):
            error(
                'Please set Django setting STATIC_ROOT to the value of '
                'environment variable STATIC_ROOT. For example, in '
                'settings.py:\n\n'
                '    import os\n'
                '    STATIC_ROOT = os.getenv("STATIC_ROOT")'
            )

def check_allowed_hosts(domains):
    # TODO: Allow wildcards in ALLOWED_HOSTS.
    if settings.ALLOWED_HOSTS != domains:
        error(
            'Please set Django setting ALLOWED_HOSTS to the list of domains '
            'under which your server is accessible. For example, in '
            'settings.py:\n\n'
            '    import os\n'
            '    ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(" ")\n\n'
            'And in deploy.yml:\n\n'
            '    services:\n'
            '      web:\n'
            '        type: django\n'
            '        domains: [my.website.com]\n'
            '      env:\n'
            '        clear:\n'
            '          ALLOWED_HOSTS: my.website.com'
        )

def check_databases():
    if settings.DATABASES['default']['NAME'] != os.environ['SQLITE_DB_FILE']:
        error(
            "Please set DATABASES['default']['NAME'] in settings.py to the "
            "value of environment variable SQLITE_DB_FILE. A good expression "
            "is:\n"
            "    os.getenv('SQLITE_DB_FILE') or <what you had before>"
        )

def error(message):
    sys.stderr.write(message)
    sys.exit(0)
