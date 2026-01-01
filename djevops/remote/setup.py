from datetime import datetime
from grp import getgrnam
from os import chmod, makedirs, remove, chown, symlink
from os.path import exists
from pwd import getpwnam
from shutil import rmtree
from subprocess import PIPE, STDOUT, run, CalledProcessError

import os
import sys


ERROR_ALREADY_EXISTS = 9


def main():
    HOST_NAME = get_env('HOST_NAME', required=True)
    GIT_SERVER = get_env('GIT_SERVER', 'github.com')
    GIT_REPO_NAME = get_env('GIT_REPO_NAME', required=True)
    GIT_REPO_BRANCH = get_env('GIT_REPO_BRANCH', 'main')
    GIT_REPO_PRIVKEY = get_env('GIT_REPO_PRIVKEY')
    SMTP_HOST = get_env('SMTP_HOST')
    ADMIN_EMAIL = get_env('ADMIN_EMAIL')

    if GIT_REPO_PRIVKEY:
        GIT_REPO_URL = f'git@{GIT_SERVER}:{GIT_REPO_NAME}.git'
    else:
        GIT_REPO_URL = f'https://{GIT_SERVER}/{GIT_REPO_NAME}.git'

    log('Setting hostname...')
    _run(['hostnamectl', 'set-hostname', HOST_NAME])

    log('Updating system...')
    _run('apt-get update -qq')
    _run('apt-get upgrade -yqq')

    log('Installing git...')
    install('git-core')

    log('Configuring git to avoid warnings when pulling...')
    _run('git config --global pull.rebase true')

    log('Creating application users...')
    ensure_group_exists('django')
    ensure_user_exists('django', 'django')

    makedirs('/home/django', exist_ok=True)
    _chown('/home/django', 'django', 'django')
    chmod('/home/django', 0o700)

    if GIT_REPO_PRIVKEY:
        log('Setting up SSH keys for cloning the Git repository...')
        makedirs('.ssh', exist_ok=True)
        with open('.ssh/id_rsa', 'w') as f:
            f.write(GIT_REPO_PRIVKEY.replace('\\n', '\n'))
        chmod('.ssh/id_rsa', 0o600)
        _run('ssh-keygen -y -f .ssh/id_rsa > .ssh/id_rsa.pub')
        chmod('.ssh/id_rsa.pub', 0o644)

    log('Adding git repository server to known hosts...')
    _run(f'ssh-keyscan -H {GIT_SERVER} > .ssh/known_hosts 2>/dev/null')
    chmod('.ssh/known_hosts', 0o600)

    log('Cloning the repository...')
    try:
        rmtree('/srv/app')
    except FileNotFoundError:
        pass
    _run(f'git clone -q -b {GIT_REPO_BRANCH} {GIT_REPO_URL} /srv/app')

    if not exists('/srv/app/requirements.txt'):
        error(
            'Please create a requirements.txt file with your dependencies '
            'in your repository.'
        )

    log('Setting up bash profiles...')
    symlink_force('/opt/djevops/conf/.bash_profile', '/root/.bash_profile')
    symlink_force(
        '/opt/djevops/conf/.bash_profile', '/home/django/.bash_profile'
    )

    bashrc_lines = [
        f'export HOST_NAME={HOST_NAME}',
        'export SQLITE_DB_FILE=/var/lib/django/db.sqlite3',
        'export STATIC_ROOT=/srv/static',
        'export PATH="/srv/venv/bin:$PATH"',
    ]
    if exists('/srv/app/conf/django.bashrc'):
        result = run(
            '/usr/bin/envsubst < /srv/app/conf/django.bashrc',
            shell=True,
            capture_output=True,
            text=True
        )
        bashrc_lines.append(result.stdout)

    with open('/home/django/.bashrc', 'w') as f:
        f.write('\n'.join(bashrc_lines) + '\n')
    _chown('/home/django/.bashrc', 'django', 'django')

    log('Creating data directory...')
    makedirs('/var/lib/django', exist_ok=True)
    _chown('/var/lib/django', 'django', 'django')

    if SMTP_HOST:
        log('Installing iptables-persistent...')
        debconf_set_selections(
            'iptables-persistent iptables-persistent/autosave_v4 boolean true'
        )
        debconf_set_selections(
            'iptables-persistent iptables-persistent/autosave_v6 boolean true'
        )
        install('iptables-persistent')

        log('Configuring iptables...')
        _run('iptables -A INPUT -i lo -p tcp --dport 25 -j ACCEPT')
        _run('iptables -A INPUT -p tcp --dport 25 -j REJECT')
        _run('iptables-save > /etc/iptables/rules.v4')

        log('Installing Postfix...')
        debconf_set_selections(f'postfix postfix/mailname string {HOST_NAME}')
        debconf_set_selections(
            "postfix postfix/main_mailer_type string 'Internet Site'"
        )
        install('postfix mailutils libsasl2-2 ca-certificates libsasl2-modules')

        log('Configuring Postfix...')
        with open('/etc/mailname', 'w') as f:
            f.write(HOST_NAME + '\n')
        _chown('/etc/mailname', 'postfix')
        _run(
            f"envsubst '$SMTP_HOST $HOST_NAME' < "
            f"/opt/djevops/conf/postfix/main.cf > /etc/postfix/main.cf"
        )
        _run(
            'envsubst < /opt/djevops/conf/postfix/sasl_passwd > '
            '/etc/postfix/sasl_passwd'
        )
        _chown('/etc/postfix', 'postfix')
        _run('rm /etc/postfix/sasl_passwd.db')
        _run('postmap /etc/postfix/sasl_passwd')
        chmod('/etc/postfix/sasl_passwd', 0o400)
        _chown('/etc/postfix/sasl_passwd', 'postfix')
        _run(
            'envsubst < /opt/djevops/conf/postfix/generic > '
            '/etc/postfix/generic'
        )
        if exists('/etc/postfix/generic.db'):
            remove('/etc/postfix/generic.db')
        _run('postmap /etc/postfix/generic')
        _chown('/etc/postfix/generic', 'postfix')
        _run('/etc/init.d/postfix reload')

    log('Creating directories for static files...')
    makedirs('/srv/static', exist_ok=True)

    log('Installing OS dependencies for our Python environment...')
    install('python3-venv')

    log('Creating virtual environment...')
    _run('python3 -m venv /srv/venv')

    log('Installing Python dependencies...')
    _run('/opt/djevops/bin/install-python-deps.sh')

    result = run(
        '/srv/venv/bin/python -c "import celery"',
        shell=True,
        capture_output=True
    )
    USES_CELERY = result.returncode == 0

    log('Checking Django settings...')
    _run(
        'su -c "/opt/djevops/bin/manage.sh shell --pythonpath '
        '/opt/djevops/bin -c \'from check_django_settings import main; '
        'main()\' -v 0" - django'
    )

    if USES_CELERY:
        log('Celery detected. Installing Redis...')
        install('redis-server')

    log('Migrating database...')
    _run('/opt/djevops/bin/migrate-db.sh')

    log('Collecting static files...')
    _run('/opt/djevops/bin/collect-static-files.sh')

    log('Initializing run/ directory...')
    _run('/opt/djevops/bin/init-run-dir.sh')

    log('Installing Supervisor...')
    install('supervisor')

    log('Configuring Supervisor...')
    symlink_force(
        '/opt/djevops/conf/supervisor/gunicorn.conf',
        '/etc/supervisor/conf.d/gunicorn.conf'
    )

    if USES_CELERY:
        symlink_force(
            '/opt/djevops/conf/supervisor/beat.conf ',
            '/etc/supervisor/conf.d/beat.conf'
        )
        symlink_force(
            '/opt/djevops/conf/supervisor/worker.conf ',
            '/etc/supervisor/conf.d/worker.conf'
        )

    log('Starting services...')
    _run('supervisorctl reread')
    _run('supervisorctl update')

    log('Installing Nginx...')
    install('nginx')

    log('Creating Nginx includes directory...')
    makedirs('/etc/nginx/includes', exist_ok=True)

    log('Creating Nginx config...')
    _run(
        'envsubst < /opt/djevops/conf/nginx/server-name > '
        '/etc/nginx/includes/server-name'
    )
    symlink_force(
        '/opt/djevops/conf/nginx/django', '/etc/nginx/includes/django'
    )
    _run('touch /etc/nginx/includes/ssl')

    log('Applying Nginx config...')
    symlink_force(
        '/opt/djevops/conf/nginx/nginx', '/etc/nginx/sites-available/django'
    )
    symlink_force(
        '/etc/nginx/sites-available/django', '/etc/nginx/sites-enabled/django'
    )
    try:
        remove('/etc/nginx/sites-enabled/default')
    except FileNotFoundError:
        pass

    log('Starting Nginx...')
    _run('service nginx restart')

    log('Generating SSL certificates...')
    install('certbot python3-certbot-nginx')
    try:
        run(
            [
                'certbot', 'register', '--quiet', '--email', ADMIN_EMAIL,
                '--agree-tos'
            ],
            stdout=PIPE,
            stderr=STDOUT,
            text=True,
            check=True
        )
    except CalledProcessError as e:
        if e.returncode != 1 or not 'There is an existing account' in e.stdout:
            raise
    _run([
        'certbot', 'certonly', '--nginx', '--quiet', '--cert-name', 'main',
        '-d', HOST_NAME
    ])
    symlink_force('/opt/djevops/conf/nginx/ssl', '/etc/nginx/includes/ssl')
    _run('service nginx restart')

    log(f'The server is now serving requests at {HOST_NAME}!')

    log('Setting up logrotate...')
    symlink_force('/opt/djevops/conf/logrotate', '/etc/logrotate.d/django')

    log('Setting up crontab...')
    symlink_force('/opt/djevops/bin/cronic', '/usr/bin/cronic')
    _run(
        f'sed "s/\\$ADMIN_EMAIL/{ADMIN_EMAIL}/g" '
        f'/opt/djevops/conf/crontab > crontab'
    )
    _run('crontab crontab')
    remove('crontab')

    log('Setting up automatic updates...')
    install('unattended-upgrades')
    with open('/etc/apt/apt.conf.d/20auto-upgrades', 'w') as f:
        f.write('APT::Periodic::Update-Package-Lists "1";\n')
        f.write('APT::Periodic::Unattended-Upgrade "1";\n')

    log('Done.')


def install(packages):
    _run(f'apt-get install -yqq {packages}')


def ensure_group_exists(group_name):
    _run(
        ['groupadd', '--system', group_name],
        ignore_errors=(ERROR_ALREADY_EXISTS,)
    )


def ensure_user_exists(user_name, group_name):
    _run([
        'useradd', '--system', '--gid', group_name, '--shell', '/bin/bash',
        user_name
    ], ignore_errors=(ERROR_ALREADY_EXISTS,))


def _chown(path, user_name, group_name=None):
    uid = getpwnam(user_name).pw_uid
    gid = -1 if group_name is None else getgrnam(group_name).gr_gid
    chown(path, uid, gid)


def symlink_force(source, link_name):
    try:
        symlink(source, link_name)
    except FileExistsError:
        remove(link_name)
        symlink(source, link_name)


def debconf_set_selections(value):
    run(['debconf-set-selections'], input=value + '\n', text=True, check=True)


def log(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f'\n\033[0;32m{timestamp}\033[0m \033[0;93m{message}\033[0m')


def error(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f'\n\033[0;32m{timestamp}\033[0m \033[0;91m{message}\033[0m')
    sys.exit(1)


def _run(cmd, ignore_errors=()):
    shell = isinstance(cmd, str)
    try:
        return run(
            cmd, shell=shell, stdout=PIPE, stderr=STDOUT, text=True, check=True
        )
    except CalledProcessError as e:
        if e.returncode not in ignore_errors:
            raise


def get_env(var_name, default=None, required=False):
    value = os.environ.get(var_name, default)
    if required and not value:
        error(
            f'Please set {var_name} in your .bashrc. '
            f'For example: export {var_name}=value'
        )
    return value


if __name__ == '__main__':
    try:
        main()
    except CalledProcessError as e:
        error(f'Command failed: {e.cmd}\nError: {e.stdout}')
