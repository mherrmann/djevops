from django.conf import settings, global_settings
from djevops import GIT_HINT
from djevops.util import is_domain, is_ip

import os
import sys

SETTINGS_PY = settings.SETTINGS_MODULE.replace('.', '/') + '.py'

def main(server_ip, db_type, mail_configured):
    check_allowed_hosts(server_ip)
    check_staticfiles()
    if db_type:
        check_databases(db_type)
    if mail_configured:
        check_server_email()

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
            '    ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split()\n\n'
            'And in deploy/djevops.yml:\n\n'
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

def check_databases(db_type):
    if db_type == 'postgres':
        check_postgres()
    else:
        check_sqlite()

def check_postgres():
    default = settings.DATABASES['default']
    if default.get('ENGINE') != 'django.db.backends.postgresql':
        error(
            f"Please set DATABASES['default']['ENGINE'] in {SETTINGS_PY} to "
            f"'django.db.backends.postgresql'."
        )

def check_sqlite():
    if settings.DATABASES['default']['NAME'] != os.environ['SQLITE_DB_FILE']:
        error(
            f"Please set DATABASES['default']['NAME'] in {SETTINGS_PY} to the "
            "value of environment variable SQLITE_DB_FILE. A good expression "
            "is:\n"
            "    os.getenv('SQLITE_DB_FILE') or <what you had before>"
        )

def check_server_email():
    if settings.ADMINS and \
        settings.SERVER_EMAIL == global_settings.SERVER_EMAIL:
        error(
            "Because ADMINS is set, please also set Django setting "
            "SERVER_EMAIL to an address from which your SMTP server lets you "
            f"send emails. For example, in {SETTINGS_PY}:\n\n"
            "    SERVER_EMAIL = 'sender@your.website.com'\n\n"
            "Your server uses this as the sender address for error emails."
        )

def error(message):
    # Write to stdout because that is what run_in_django_shell(...) returns.
    sys.stdout.write(message + '\n\n' + GIT_HINT)
    sys.exit(0)
