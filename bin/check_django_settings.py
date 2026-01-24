from django.conf import settings

import sys

def main(domains):
    check_allowed_hosts(domains)

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

def error(message):
    sys.stderr.write(message)
    sys.exit(0)
