from ipaddress import ip_address
from subprocess import run, PIPE, STDOUT, CalledProcessError

import re
import sys

def copy_with_replace(source, target, replacements):
    with open(source, 'r') as f:
        content = f.read()
    for key, value in replacements.items():
        content = content.replace(key, value)
    with open(target, 'w') as f:
        f.write(content)

def git(*args):
    return run_silently(['git', *args])

def run_in_django_shell(
    cmds, executable=sys.executable, manage_py='manage.py', env=None
):
    args = [executable, manage_py, 'shell', '-v', '0', '-c', ' ; '.join(cmds)]
    return run_silently(args, env=env)

def run_silently(*args, **kwargs):
    try:
        return run(
            *args, **kwargs, stdout=PIPE, stderr=STDOUT, text=True, check=True
        ).stdout.strip()
    except CalledProcessError as e:
        raise CalledProcessErrorShowingOutput(e.returncode, e.cmd, e.output) \
            from None

class CalledProcessErrorShowingOutput(CalledProcessError):
    def __str__(self):
        result = super().__str__()
        if self.output:
            result += f' Its output was:\n"""\n{self.output}\n"""'
        return result

def get_apt_install_cmd(*packages):
    packages_str = ' '.join(packages)
    install_cmd = \
        f'DEBIAN_FRONTEND=noninteractive ' \
        f'apt-get install -yqq {packages_str} >/dev/null 2>&1'
    # Use `dpkg -s` to check if the packages are already installed, because it
    # is faster than apt-get. Also call `apt-get update`, but only if necessary.
    return (
        'dpkg -s %s >/dev/null 2>&1 || { %s || { apt-get update -qq && %s; }; }'
        % (packages_str, install_cmd, install_cmd)
    )

def is_domain(host):
    return re.match(r'[a-zA-Z][a-zA-Z0-9-]*(\.[a-zA-Z][a-zA-Z0-9-]*)+', host)

def is_ip(host):
    try:
        ip_address(host)
        return True
    except ValueError:
        return False

def prompt_yes_no(question):
    while True:
        answer = input(question + ' [y/n] ')
        if answer.lower() == 'y':
            return True
        elif answer.lower() == 'n':
            return False
        else:
            print('Please answer y or n.')
