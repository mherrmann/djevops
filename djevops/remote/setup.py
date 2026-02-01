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
TERMINAL_COLOR_SUCCESS = 93
TERMINAL_COLOR_ERROR = 91

def main():
    config = get_deploy_config()
    secrets = get_secrets()

    server_ip = config['server']
    primary_domain = ''
    for service in config['services'].values():
        try:
            primary_domain = service['domains'][0]
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

    if primary_domain and _run('hostname') != primary_domain:
        log('Setting hostname...')
        _run(['hostnamectl', 'set-hostname', primary_domain])

    log('Installing git...')
    install('git-core')

    if git_repo_key and not exists('/root/.ssh/id_rsa'):
        log('Setting up SSH keys for cloning the Git repository...')
        git_key = secrets[git_repo_key]
        makedirs('/root/.ssh', exist_ok=True)
        with open('/root/.ssh/id_rsa', 'w') as f:
            f.write(git_key)
        chmod('/root/.ssh/id_rsa', 0o600)
        _run('ssh-keygen -y -f /root/.ssh/id_rsa > /root/.ssh/id_rsa.pub')
        chmod('/root/.ssh/id_rsa.pub', 0o644)

    try:
        with open('/root/.ssh/known_hosts') as f:
            need_to_add_to_known_hosts = git_server not in f.read()
    except FileNotFoundError:
        need_to_add_to_known_hosts = True
    if need_to_add_to_known_hosts:
        log('Adding git repository server to known hosts...')
        _run(
            f'ssh-keyscan -H {git_server} > /root/.ssh/known_hosts 2>/dev/null'
        )
        chmod('/root/.ssh/known_hosts', 0o600)

    try:
        _run('git -C /srv/app fetch origin')
        _run(f'git -C /srv/app reset --hard origin/{git_repo_branch}')
    except CalledProcessError:
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

    if not exists('/srv/venv'):
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
    gunicorns = []
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
            gunicorns.append(service_name)
            nginx_available_file = '/etc/nginx/sites-available/' + service_name
            domains = service.get('domains', [])
            copy_with_replace(
                '/opt/djevops/conf/nginx/django', nginx_available_file,
                {
                    '$SERVER_NAME': ' '.join(domains) or server_ip,
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
            if domains:
                service_domains[service_name] = domains[:]
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
    self_signed_cert_privkey = '/etc/nginx/certs/default/privkey.pem'
    if not exists(self_signed_cert_privkey):
        log('Creating self-signed certificate...')
        makedirs('/etc/nginx/certs/default', exist_ok=True)
        _run([
            'openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048',
            '-keyout', self_signed_cert_privkey,
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
        if primary_domain:
            debconf_set_selections(
                f'postfix postfix/mailname string {primary_domain}'
            )
        debconf_set_selections(
            "postfix postfix/main_mailer_type string 'Internet Site'"
        )
        install('postfix mailutils libsasl2-2 ca-certificates libsasl2-modules')

        log('Configuring Postfix...')
        if primary_domain:
            with open('/etc/mailname', 'w') as f:
                f.write(primary_domain + '\n')
        _chown('/etc/mailname', 'postfix')
        smtp_host = config['mail']['host']
        copy_with_replace(
            '/opt/djevops/conf/postfix/main.cf',
            '/etc/postfix/main.cf',
            {
                '$primary_domain': primary_domain,
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
    for gunicorn in gunicorns:
        _run(f'supervisorctl signal HUP {gunicorn}', ignore_errors=(7,))

    any_service_failed = False
    for status_line in _run('supervisorctl status').splitlines():
        parts = status_line.split()
        if parts[1] != 'RUNNING':
            any_service_failed = True
            print('\n' + status_line)
            log_file = f'/var/log/{parts[0]}.log'
            with open(log_file) as f:
                print(f.read().rstrip())
    if any_service_failed:
        error('Some services failed to start. See logs above.')

    _run('service nginx restart')

    server_url = f'https://{primary_domain}' if primary_domain \
        else f'http://{server_ip}'
    log(f'The server is now serving requests at {server_url}!')

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
    _log(message, TERMINAL_COLOR_SUCCESS)

def error(message):
    _log(message, TERMINAL_COLOR_ERROR)
    sys.exit(1)

def _log(message, color):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f'\n\033[0;32m{timestamp}\033[0m \033[0;{color}m{message}\033[0m')

def _run(cmd, ignore_errors=(), env=None):
    shell = isinstance(cmd, str)
    try:
        return run(
            cmd, shell=shell, stdout=PIPE, stderr=STDOUT, text=True, check=True,
            env=env
        ).stdout.strip()
    except CalledProcessError as e:
        if e.returncode not in ignore_errors:
            raise

if __name__ == '__main__':
    try:
        main()
    except CalledProcessError as e:
        output = e.stderr or e.stdout
        error(f'Command failed: {e.cmd}\nOutput: {output}')
