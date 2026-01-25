from subprocess import run, PIPE, STDOUT, CalledProcessError

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
            result += f' Output:\n{self.output}'
        return result
