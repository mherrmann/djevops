from django.conf import settings
from djevops.util import is_domain, is_ip

import os
import sys

SETTINGS_PY = settings.SETTINGS_MODULE.replace('.', '/') + '.py'

GIT_HINT = "Don't forget to commit *and push* your changes to Git."

def main(server_ip, has_db):
    check_allowed_hosts(server_ip)
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
                f'{SETTINGS_PY}:\n\n'
                '    import os\n'
                '    STATIC_ROOT = os.getenv("STATIC_ROOT")'
            )

def check_allowed_hosts(server_ip):
    if not settings.ALLOWED_HOSTS:
        error(
            'Please set Django setting ALLOWED_HOSTS to the list of host names '
            'or IP addresses under which your server is accessible. For '
            f'example, in {SETTINGS_PY}:\n\n'
            '    import os\n'
            '    ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(" ")\n\n'
            'And in djevops/deploy.yml:\n\n'
            '    services:\n'
            '      web:\n'
            '        type: django\n'
            '        env:\n'
            '          clear:\n'
            f'            ALLOWED_HOSTS: "{server_ip}"'
        )
    for host in settings.ALLOWED_HOSTS:
        if not is_domain(host) and not is_ip(host):
            error(
                f'The format of this entry in ALLOWED_HOSTS is not yet '
                f'supported, sorry: {host!r}'
            )

def check_databases():
    if settings.DATABASES['default']['NAME'] != os.environ['SQLITE_DB_FILE']:
        error(
            f"Please set DATABASES['default']['NAME'] in {SETTINGS_PY} to the "
            "value of environment variable SQLITE_DB_FILE. A good expression "
            "is:\n"
            "    os.getenv('SQLITE_DB_FILE') or <what you had before>"
        )

def error(message):
    sys.stderr.write(message + '\n\n' + GIT_HINT)
    sys.exit(0)
