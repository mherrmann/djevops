from subprocess import run, PIPE, STDOUT

import sys

def copy_with_replace(source, target, replacements):
    with open(source, 'r') as f:
        content = f.read()
    for key, value in replacements.items():
        content = content.replace(key, value)
    with open(target, 'w') as f:
        f.write(content)

def git(*args):
    return run(
        ['git', *args], stdout=PIPE, stderr=STDOUT, text=True, check=True
    ).stdout.strip()

def run_in_django_shell(
    cmds, executable=sys.executable, manage_py='manage.py', env=None
):
    args = [executable, manage_py, 'shell', '-v', '0', '-c', ' ; '.join(cmds)]
    cp = run(args, env=env, stdout=PIPE, stderr=STDOUT, text=True, check=True)
    return cp.stdout.strip()
