from subprocess import run, PIPE, STDOUT

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
