from datetime import datetime
from djevops.remote.component_registry import ComponentRegistry
from djevops.remote.components import AptPackage, SshKey, Crontab, Hostname, \
    IptablesRules, KnownHostsEntry, LetsEncryptCertificate, \
    LetsEncryptRegistration, Litestream, NginxSite, Postfix, \
    SelfSignedCertificate, ServiceUser, TemplatedFile, VirtualEnvironment
from djevops.config import get_services_users_envs, interpolate_secrets, \
    SQLITE_DB_FILE
from djevops.litestream import get_litestream_config
from djevops.remote import postgres
from djevops.remote.actions import install_python_deps, migrate_db, \
    collect_static_files, get_django_setting
from djevops.remote.scaffold import get_deploy_config, get_secrets
from djevops.remote.util import chown, ensure_group_exists, run as _run, \
    symlink_force
from djevops.util import is_domain
from os import chmod, makedirs
from os.path import exists
from shlex import quote
from shutil import rmtree, copyfile
from subprocess import run, CalledProcessError, DEVNULL
from time import sleep

import sys
import yaml

TERMINAL_COLOR_SUCCESS = 93
TERMINAL_COLOR_ERROR = 91

def main():
    config = get_deploy_config()
    secrets = get_secrets()

    registry = ComponentRegistry(log)
    require = registry.require

    server_ip = config['server']

    git_server = config['git'].get('server', 'github.com')
    git_repo_name = config['git']['repo']
    git_repo_branch = config['git'].get('branch', 'main')
    git_repo_key = config['git'].get('key')

    if git_repo_key:
        git_repo_url = f'git@{git_server}:{git_repo_name}.git'
    else:
        git_repo_url = f'https://{git_server}/{git_repo_name}.git'

    def install_if_not_installed(*packages):
        for package in packages:
            require(AptPackage(package))

    install_if_not_installed('git')

    if git_repo_key:
        git_key = secrets[git_repo_key]
        require(SshKey(git_key))

    require(KnownHostsEntry(git_server))

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

    symlink_force('/opt/djevops/conf/.bash_profile', '/root/.bash_profile')

    install_if_not_installed('supervisor')

    require(VirtualEnvironment('/srv/venv'))

    log('Installing Python dependencies...')
    install_python_deps()

    install_if_not_installed('nginx')

    makedirs('/etc/nginx/includes', exist_ok=True)

    django_group = 'django'
    ensure_group_exists(django_group)
    makedirs('/var/lib/djevops', exist_ok=True)
    chown('/var/lib/djevops', group_name=django_group)
    chmod('/var/lib/djevops', 0o770)

    log('Configuring services...')
    primary_domain = ''
    admin_email = ''
    service_domains = {}
    services_users_envs = get_services_users_envs(config, secrets)
    changed_bashrcs = set()
    services = config['services']
    for service_name, (user, env) in services_users_envs.items():
        if require(ServiceUser(user, env, django_group)):
            changed_bashrcs.add(user)
        service = services[service_name]
        replacements = {'$SERVICE': service_name, '$USER': user}
        if service['type'] == 'django':
            if not primary_domain:
                for host in get_django_setting('ALLOWED_HOSTS', env):
                    if is_domain(host):
                        primary_domain = host
                        require(Hostname(primary_domain))
                        break
            if not admin_email:
                admins = get_django_setting('ADMINS', env)
                if admins:
                    admin_email = admins[0]
                    if not isinstance(admin_email, str):
                        admin_email = admin_email[1]
            supervisor_conf_file = 'gunicorn.conf'
            domains = [
                host for host in get_django_setting('ALLOWED_HOSTS', env)
                if is_domain(host)
            ]
            require(NginxSite(
                service_name,
                '/opt/djevops/conf/nginx/django',
                {
                    '$SERVER_NAME': ' '.join(domains) or server_ip,
                    '$SERVICE': service_name,
                }
            ))
            # Placeholder until Certbot runs. Create it only if absent so we
            # don't clobber the ssl config Certbot's TemplatedFile writes below.
            ssl_include = f'/etc/nginx/includes/{service_name}-ssl'
            if not exists(ssl_include):
                open(ssl_include, 'w').close()
            require(TemplatedFile(
                f'/etc/logrotate.d/{service_name}-nginx',
                '/opt/djevops/conf/logrotate/nginx',
                {'$SERVICE': service_name}
            ))
            if domains:
                service_domains[service_name] = domains[:]
        elif service['type'] in ('celery', 'command'):
            supervisor_conf_file = 'command.conf'
            if service['type'] == 'celery':
                command = f'/opt/djevops/bin/celery.sh {service_name}'
            else:
                command = service['command']
            replacements['$COMMAND'] = quote(command)
        else:
            error(f"Unknown service type: {service['type']}")
        require(TemplatedFile(
            f'/etc/supervisor/conf.d/{service_name}.conf',
            f'/opt/djevops/conf/supervisor/{supervisor_conf_file}',
            replacements
        ))
        require(TemplatedFile(
            f'/etc/logrotate.d/{service_name}',
            '/opt/djevops/conf/logrotate/service',
            replacements
        ))

    # Make a self-signed certificate just so we can serve SSL for requests with
    # incorrect host names.
    require(SelfSignedCertificate('/etc/nginx/certs/default', 'default.invalid'))

    copyfile(
        '/opt/djevops/conf/nginx/default', '/etc/nginx/sites-available/default'
    )

    if service_domains:
        install_if_not_installed('certbot', 'python3-certbot-nginx')
        require(LetsEncryptRegistration(admin_email))
        for service_name, domains in service_domains.items():
            require(LetsEncryptCertificate(service_name, domains))

    if config.get('mail'):
        log('Installing iptables-persistent...')
        debconf_set_selections(
            'iptables-persistent iptables-persistent/autosave_v4 boolean true'
        )
        debconf_set_selections(
            'iptables-persistent iptables-persistent/autosave_v6 boolean true'
        )
        install_if_not_installed('iptables-persistent')

        require(IptablesRules(
            accept=['-i lo -p tcp --dport 25'],
            reject=['-p tcp --dport 25'],
        ))

        log('Installing Postfix...')
        if primary_domain:
            debconf_set_selections(
                f'postfix postfix/mailname string {primary_domain}'
            )
        debconf_set_selections(
            "postfix postfix/main_mailer_type string 'Internet Site'"
        )
        install_if_not_installed(
            'postfix', 'mailutils', 'libsasl2-2', 'ca-certificates',
            'libsasl2-modules'
        )

        hostname = primary_domain or _run('hostname')
        require(Postfix(
            hostname,
            config['mail']['host'],
            secrets[config['mail']['user']],
            secrets[config['mail']['password']],
        ))

    if 'redis' in config:
        install_if_not_installed('redis-server')

    cron_jobs = ['@reboot /opt/djevops/bin/init-run-dir.sh']

    db = config.get('db')
    if db:
        db_type = db.get('type', 'sqlite')
        db_backup = interpolate_secrets(db['backup'], secrets) \
            if db.get('backup') else None
        if db_type == 'postgres':
            install_if_not_installed('postgresql')
            db_config = get_django_setting('DATABASES')['default']
            db_existed = postgres.provision(db_config)
            if db_backup and not db_existed:
                log('Restoring database backup...')
                postgres.restore(db_config, db_backup)
            log('Migrating database...')
            migrate_db()
            if db_backup:
                cron_jobs.append(
                    '* * * * * /opt/djevops/.venv/bin/python '
                    '-m djevops.remote.postgres backup'
                )
        else:
            if db_backup:
                require(Litestream())
                litestream_config = get_litestream_config(db_backup)
                with open('/etc/litestream.yml', 'w') as f:
                    yaml.safe_dump(litestream_config, f)
                if not exists(SQLITE_DB_FILE):
                    log('Restoring database backup...')
                    _run(['litestream', 'restore', SQLITE_DB_FILE])
            log('Migrating database...')
            migrate_db()
            chown(SQLITE_DB_FILE, group_name=django_group)
            chmod(SQLITE_DB_FILE, 0o660)
            if db_backup:
                # Do this after migrating the database and chowning the file in
                # order to avoid race conditions.
                _run('systemctl enable litestream')
                _run('systemctl start litestream')

    log('Creating directories for static files...')
    makedirs('/srv/static', exist_ok=True)

    log('Collecting static files...')
    collect_static_files()

    log('Initializing run/ directory...')
    _run('/opt/djevops/bin/init-run-dir.sh')

    log('Starting services...')
    updated_services_str = _run('supervisorctl update')
    updated_services = set()
    for line in updated_services_str.splitlines():
        parts = line.split(': ', 1)
        assert len(parts) == 2, line
        updated_services.add(parts[0])
    # Restart those services that were not already handled by `update`:
    for service_name, (user, env) in services_users_envs.items():
        if service_name in updated_services:
            continue
        service = services[service_name]
        if service['type'] == 'django' and user not in changed_bashrcs:
            try:
                _run(['supervisorctl', 'signal', 'HUP', service_name])
            except CalledProcessError as e:
                if e.returncode != 7:
                    raise
                # The service wasn't running.
                _run_silently(['supervisorctl', 'start', service_name])
        else:
            _run_silently(['supervisorctl', 'restart', service_name])
    # This loop should not run forever because we supply `startsecs` in the
    # supervisor config file.
    while True:
        supervisor_status_str = _run('supervisorctl status')
        if 'STARTING' in supervisor_status_str:
            sleep(1)
        else:
            break
    supervisor_status = {}
    for line in supervisor_status_str.splitlines():
        parts = line.split()
        supervisor_status[parts[0]] = parts[1]
    any_service_failed = False
    for service_name in services:
        if supervisor_status[service_name] != 'RUNNING':
            any_service_failed = True
            print('\n' + line)
            log_file = f'/var/log/{service_name}.log'
            with open(log_file) as f:
                print(f.read().rstrip())
    if any_service_failed:
        error('Some services failed to start. See logs above.')

    _run('nginx -s reload')

    server_url = f'https://{primary_domain}' if primary_domain \
        else f'http://{server_ip}'
    log(f'The server is now serving requests at {server_url}!')

    require(Crontab(cron_jobs, mailto=admin_email))

    install_if_not_installed('unattended-upgrades')
    with open('/etc/apt/apt.conf.d/20auto-upgrades', 'w') as f:
        f.write('APT::Periodic::Update-Package-Lists "1";\n')
        f.write('APT::Periodic::Unattended-Upgrade "1";\n')

    if registry.uninstall_unused():
        _run('supervisorctl update')
        _run('nginx -s reload')

    log('Done.')

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

def _run_silently(cmd):
    return run(cmd, stdout=DEVNULL, stderr=DEVNULL)

if __name__ == '__main__':
    try:
        main()
    except CalledProcessError as e:
        output = e.stderr or e.stdout
        error(f'Command failed: {e.cmd}\nOutput: {output}')
