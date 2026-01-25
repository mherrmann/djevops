from datetime import datetime
from djevops.config import get_services_users_envs, SQLITE_DB_FILE
from djevops.remote.actions import install_python_deps, migrate_db, \
    collect_static_files, get_django_setting
from djevops.remote.scaffold import get_deploy_config, get_secrets
from djevops.util import copy_with_replace, get_apt_install_cmd
from grp import getgrnam
from os import chmod, makedirs, remove, chown, symlink
from os.path import exists
from pwd import getpwnam
from random import randint
from shutil import rmtree, copyfile
from subprocess import PIPE, STDOUT, run, CalledProcessError

import sys

ERROR_ALREADY_EXISTS = 9

def main():
    config = get_deploy_config()
    secrets = get_secrets()

    host_name = config['server']
    for service in config['services'].values():
        try:
            host_name = service['domains'][0]
            break
        except (KeyError, IndexError):
            pass

    git_server = config['git'].get('server', 'github.com')
    git_repo_name = config['git']['repo']
    git_repo_branch = config['git'].get('branch', 'main')
    git_repo_key = config['git'].get('key')

    if git_repo_key:
        git_repo_url = f'git@{git_server}:{git_repo_name}.git'
    else:
        git_repo_url = f'https://{git_server}/{git_repo_name}.git'

    log('Setting hostname...')
    _run(['hostnamectl', 'set-hostname', host_name])

    log('Installing git...')
    install('git-core')

    log('Configuring git to avoid warnings when pulling...')
    # TODO: Maybe this should be in the repo only?
    _run('git config --global pull.rebase true')

    if git_repo_key:
        log('Setting up SSH keys for cloning the Git repository...')
        git_key = secrets[git_repo_key]
        makedirs('/root/.ssh', exist_ok=True)
        with open('/root/.ssh/id_rsa', 'w') as f:
            f.write(git_key)
        chmod('/root/.ssh/id_rsa', 0o600)
        _run('ssh-keygen -y -f /root/.ssh/id_rsa > /root/.ssh/id_rsa.pub')
        chmod('/root/.ssh/id_rsa.pub', 0o644)

    log('Adding git repository server to known hosts...')
    _run(f'ssh-keyscan -H {git_server} > /root/.ssh/known_hosts 2>/dev/null')
    chmod('/root/.ssh/known_hosts', 0o600)

    log('Cloning the repository...')
    try:
        rmtree('/srv/app')
    except FileNotFoundError:
        pass
    _run(f'git clone -q -b {git_repo_branch} {git_repo_url} /srv/app')

    log('Setting up .bash_profile for root...')
    symlink_force('/opt/djevops/conf/.bash_profile', '/root/.bash_profile')

    log('Installing Supervisor...')
    install('supervisor')

    log('Installing OS dependencies for our Python environment...')
    install('python3-venv')

    log('Creating virtual environment...')
    _run('python3 -m venv /srv/venv')

    log('Installing Python dependencies...')
    install_python_deps()

    log('Installing Nginx...')
    install('nginx')

    log('Creating Nginx includes directory...')
    makedirs('/etc/nginx/includes', exist_ok=True)

    log('Creating /var/lib/django directory...')
    django_group = 'django'
    ensure_group_exists(django_group)
    makedirs('/var/lib/django', exist_ok=True)
    _chown('/var/lib/django', group_name=django_group)
    chmod('/var/lib/django', 0o770)

    log('Configuring services...')
    created_users = set()
    admin_email = None
    service_domains = {}
    services_users_envs = get_services_users_envs(config, secrets)
    for service_name, (user, env) in services_users_envs.items():
        if user not in created_users:
            ensure_group_exists(user)
            ensure_user_exists(user, user)
            _run(f'usermod -a -G {django_group} {user}')
            home_dir = f'/home/{user}'
            makedirs(home_dir, exist_ok=True)
            _chown(home_dir, user, user)
            chmod(home_dir, 0o700)
            symlink_force(
                '/opt/djevops/conf/.bash_profile', f'{home_dir}/.bash_profile'
            )
            with open(f'{home_dir}/.bashrc', 'w') as f:
                for key, value in env.items():
                    f.write(f'export {key}="{value}"\n')
            _chown(f'{home_dir}/.bashrc', user, user)
            created_users.add(user)
        service = config['services'][service_name]
        if service['type'] == 'django':
            if not admin_email:
                admins = get_django_setting('ADMINS', env)
                if admins:
                    admin_email = admins[0]
                    if not isinstance(admin_email, str):
                        admin_email = admin_email[1]
            supervisor_conf_file = 'gunicorn.conf'
            nginx_available_file = '/etc/nginx/sites-available/' + service_name
            copy_with_replace(
                '/opt/djevops/conf/nginx/django', nginx_available_file,
                {
                    '$SERVER_NAME': ' '.join(service['domains']),
                    '$SERVICE': service_name,
                }
            )
            # Placeholder until Certbot runs:
            open(f'/etc/nginx/includes/{service_name}-ssl', 'w').close()
            symlink_force(
                nginx_available_file, '/etc/nginx/sites-enabled/' + service_name
            )
            copy_with_replace(
                f'/opt/djevops/conf/logrotate/nginx',
                f'/etc/logrotate.d/{service_name}-nginx',
                {'$SERVICE': service_name}
            )
            service_domains[service_name] = service['domains'][:]
        elif service['type'] == 'celery':
            supervisor_conf_file = 'celery.conf'
        else:
            error(f"Unknown service type: {service['type']}")
        replacements = {'$SERVICE': service_name, '$USER': user}
        copy_with_replace(
            f'/opt/djevops/conf/supervisor/{supervisor_conf_file}',
            f'/etc/supervisor/conf.d/{service_name}.conf',
            replacements
        )
        copy_with_replace(
            f'/opt/djevops/conf/logrotate/service',
            f'/etc/logrotate.d/{service_name}',
            replacements
        )

    # Make a self-signed certificate just so we can serve SSL for requests with
    # incorrect host names.
    makedirs('/etc/nginx/certs/default', exist_ok=True)
    _run([
        'openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048',
        '-keyout', '/etc/nginx/certs/default/privkey.pem',
        '-out', '/etc/nginx/certs/default/fullchain.pem',
        '-days', '36500',
        '-subj', '/CN=default.invalid'
    ])
    copyfile(
        '/opt/djevops/conf/nginx/default', '/etc/nginx/sites-available/default'
    )

    if service_domains:
        log('Configuring SSL certificates...')
        install('certbot python3-certbot-nginx')
        register_args = ['certbot', 'register', '--quiet', '--agree-tos']
        if admin_email:
            register_args.extend(['--email', admin_email])
        else:
            register_args.append('--register-unsafely-without-email')
        try:
            run(
                register_args, stdout=PIPE, stderr=STDOUT, text=True, check=True
            )
        except CalledProcessError as e:
            if e.returncode != 1 or \
                not 'There is an existing account' in e.stdout:
                raise
        for service_name, domains in service_domains.items():
            certbot_cmd = [
                'certbot', 'certonly', '--nginx', '--cert-name', service_name,
                '--quiet'
            ]
            for domain in domains:
                certbot_cmd.extend(['-d', domain])
            _run(certbot_cmd)
            copy_with_replace(
                '/opt/djevops/conf/nginx/ssl',
                f'/etc/nginx/includes/{service_name}-ssl',
                {'$SERVICE': service_name}
            )

    if config.get('mail'):
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
        debconf_set_selections(f'postfix postfix/mailname string {host_name}')
        debconf_set_selections(
            "postfix postfix/main_mailer_type string 'Internet Site'"
        )
        install('postfix mailutils libsasl2-2 ca-certificates libsasl2-modules')

        log('Configuring Postfix...')
        with open('/etc/mailname', 'w') as f:
            f.write(host_name + '\n')
        _chown('/etc/mailname', 'postfix')
        smtp_host = config['mail']['host']
        copy_with_replace(
            '/opt/djevops/conf/postfix/main.cf',
            '/etc/postfix/main.cf',
            {
                '$HOST_NAME': host_name,
                '$SMTP_HOST': smtp_host,
            }
        )
        copy_with_replace(
            '/opt/djevops/conf/postfix/sasl_passwd',
            '/etc/postfix/sasl_passwd',
            {
                '$SMTP_HOST': config['mail']['host'],
                '$SMTP_USER': secrets[config['mail']['user']],
                '$SMTP_PASSWORD': secrets[config['mail']['password']],
            }
        )
        _chown('/etc/postfix', 'postfix')
        try:
            remove('/etc/postfix/sasl_passwd.db')
        except FileNotFoundError:
            pass
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

    if 'redis' in config:
        log('Installing Redis...')
        install('redis-server')

    if config.get('db'):
        log('Migrating database...')
        migrate_db()
        _chown(SQLITE_DB_FILE, group_name=django_group)
        chmod(SQLITE_DB_FILE, 0o660)

    log('Creating directories for static files...')
    makedirs('/srv/static', exist_ok=True)

    log('Collecting static files...')
    collect_static_files()

    log('Initializing run/ directory...')
    _run('/opt/djevops/bin/init-run-dir.sh')

    log('Starting services...')
    _run('supervisorctl reread')
    _run('supervisorctl update')
    _run('service nginx restart')

    log(f'The server is now serving requests at {host_name}!')

    log('Setting up crontab...')
    symlink_force('/opt/djevops/bin/cronic', '/usr/bin/cronic')
    with open('crontab', 'w') as f:
        if admin_email:
            f.write(f'MAILTO={admin_email}\n')
        f.write('@reboot /opt/djevops/bin/init-run-dir.sh\n')
        minute = randint(0, 59)
        hour = randint(0, 23)
        f.write(f'{minute} {hour} */7 * * cronic certbot renew\n')
    _run('crontab crontab')
    remove('crontab')

    log('Setting up automatic updates...')
    install('unattended-upgrades')
    with open('/etc/apt/apt.conf.d/20auto-upgrades', 'w') as f:
        f.write('APT::Periodic::Update-Package-Lists "1";\n')
        f.write('APT::Periodic::Unattended-Upgrade "1";\n')

    log('Done.')

def install(packages):
    _run(get_apt_install_cmd(packages))

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

def _chown(path, user_name=None, group_name=None):
    uid = -1 if user_name is None else getpwnam(user_name).pw_uid
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
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f'\n\033[0;32m{timestamp}\033[0m \033[0;93m{message}\033[0m')

def error(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f'\n\033[0;32m{timestamp}\033[0m \033[0;91m{message}\033[0m')
    sys.exit(1)

def _run(cmd, ignore_errors=(), env=None):
    shell = isinstance(cmd, str)
    try:
        return run(
            cmd, shell=shell, stdout=PIPE, stderr=STDOUT, text=True, check=True,
            env=env
        )
    except CalledProcessError as e:
        if e.returncode not in ignore_errors:
            raise

if __name__ == '__main__':
    try:
        main()
    except CalledProcessError as e:
        output = e.stderr or e.stdout
        error(f'Command failed: {e.cmd}\nOutput: {output}')
