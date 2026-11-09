from collections import deque
from datetime import datetime
from ipaddress import ip_address
from os import scandir
from os.path import join
from subprocess import run, PIPE, CalledProcessError

import re
import sys

TERMINAL_COLOR_SUCCESS = 93
TERMINAL_COLOR_ERROR = 91

# Automatic OS updates can hold apt's lock for several minutes. We wait for them
# because otherwise, apt-get fails right away.
APT_GET = 'apt-get -o DPkg::Lock::Timeout=600'

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
    cmds, executable=sys.executable, manage_py='manage.py', env=None, **kwargs
):
    args = [executable, manage_py, 'shell', '-v', '0', '-c', ' ; '.join(cmds)]
    return run_silently(args, env=env, **kwargs)

def run_silently(*args, **kwargs):
    # Only return stdout. Stderr may contain noise such as SyntaxWarnings
    # emitted while byte-compiling third-party packages on first import.
    try:
        return run(
            *args, **kwargs, stdout=PIPE, stderr=PIPE, text=True, check=True
        ).stdout.strip()
    except CalledProcessError as e:
        raise CalledProcessErrorShowingOutput(
            e.returncode, e.cmd, e.stdout + e.stderr
        ) from None

class CalledProcessErrorShowingOutput(CalledProcessError):
    def __str__(self):
        result = super().__str__()
        if self.output:
            result += f' Its output was:\n"""\n{self.output}\n"""'
        return result

def get_apt_install_cmd(*packages):
    packages_str = ' '.join(packages)
    # Use `dpkg -s` to check if the packages are already installed, because it
    # is faster than apt-get.
    return (
        f'dpkg -s {packages_str} >/dev/null 2>&1 || '
        f'DEBIAN_FRONTEND=noninteractive '
        f'{APT_GET} install -yqq {packages_str} >/dev/null 2>&1'
    )

def get_apt_uninstall_cmd(package):
    # As above, ask dpkg first because it is faster than apt-get and does not
    # wait for apt's lock.
    return (
        f"if dpkg-query -W -f='${{Status}}' {package} 2>/dev/null | "
        f"grep -q '^install ok installed$'; then "
        f'DEBIAN_FRONTEND=noninteractive '
        f'{APT_GET} purge -yqq {package} >/dev/null 2>&1; fi'
    )

def get_initial_apt_update_cmd():
    # New servers have no package lists. After that, the OS's timers keep them
    # up to date. We retry because the timers may be updating the lists at this
    # moment, and apt-get update does not wait for this like other commands do.
    return (
        'ls /var/lib/apt/lists/*_Packages* >/dev/null 2>&1 || '
        'apt-get update -qq || { sleep 30 && apt-get update -qq; }'
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

def walk_breadth_first(root):
    queue = deque([root])
    while queue:
        dir_path = queue.popleft()
        yield dir_path
        for entry in sorted(scandir(dir_path), key=lambda e: e.name):
            is_hidden = entry.name.startswith('.')
            if not is_hidden and entry.is_dir(follow_symlinks=False):
                queue.append(
                    entry.name if dir_path == '.' else join(dir_path, entry.name)
                )

def log(message):
    _log(message, TERMINAL_COLOR_SUCCESS)

def error(message):
    _log(message, TERMINAL_COLOR_ERROR)
    sys.exit(1)

def _log(message, color):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f'\033[0;32m{timestamp}\033[0m \033[0;{color}m{message}\033[0m')
