from djevops.backup import as_cron, parse_sync_interval
from djevops.remote.component_registry import ComponentRegistry
from djevops.remote.components import AptPackage, SshKey, Crontab, Hostname, \
    IptablesRules, KnownHostsEntry, LetsEncryptCertificate, \
    LetsEncryptRegistration, Litestream, NginxSite, Postfix, \
    SelfSignedCertificate, ServiceUser, TemplatedFile, VirtualEnvironment
from djevops.config import get_backup_config, get_services_users_envs, \
    SQLITE_DB_FILE
from djevops.litestream import get_litestream_config
from djevops.remote import postgres
from djevops.remote.actions import install_python_deps, migrate_db, \
    collect_static_files, get_django_setting
from djevops.remote.nginx import get_header_name_from_meta_key, \
    get_nginx_size_from_bytes
from djevops.remote.scaffold import DJEVOPS_PYTHON, get_deploy_config, \
    get_secrets
from djevops.remote.util import chown, ensure_group_exists, run as _run, \
    symlink_force
from djevops.util import is_domain, log, error
from os import chmod, makedirs
from os.path import exists
from shlex import quote
from shutil import rmtree, copyfile
from subprocess import run, CalledProcessError, DEVNULL, Popen
from time import sleep

import yaml

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
    programs = []
    services = config['services']
    for service_name, (user, env) in services_users_envs.items():
        def require_program(
            name, supervisor_conf, command=None, hup_eligible=False
        ):
            replacements = {'$SERVICE': name, '$USER': user}
            if command is not None:
                replacements['$COMMAND'] = quote(command)
            require(TemplatedFile(
                f'/etc/supervisor/conf.d/{name}.conf',
                f'/opt/djevops/conf/supervisor/{supervisor_conf}',
                replacements
            ))
            require(TemplatedFile(
                f'/etc/logrotate.d/{name}',
                '/opt/djevops/conf/logrotate/service',
                replacements
            ))
            programs.append((name, user, hup_eligible))

        if require(ServiceUser(user, env, django_group)):
            changed_bashrcs.add(user)
        service = services[service_name]
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
            domains = [
                host for host in get_django_setting('ALLOWED_HOSTS', env)
                if is_domain(host)
            ]
            replacements = {
                '$CLIENT_MAX_BODY_SIZE': get_nginx_size_from_bytes(
                    get_django_setting('DATA_UPLOAD_MAX_MEMORY_SIZE', env)
                ),
                '$SERVER_NAME': ' '.join(domains) or server_ip,
                '$SERVICE': service_name,
                '$USER': user,
                '$PROXY_SSL_HEADER': '',
            }
            ssl_header_tpl = get_django_setting('SECURE_PROXY_SSL_HEADER', env)
            if ssl_header_tpl:
                header_name = get_header_name_from_meta_key(ssl_header_tpl[0])
                replacements['$PROXY_SSL_HEADER'] = \
                    f'proxy_set_header {header_name} $scheme;'
            require(NginxSite(
                service_name,
                '/opt/djevops/conf/nginx/django',
                replacements
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
            require_program(service_name, 'gunicorn.conf', hup_eligible=True)
        elif service['type'] == 'celery':
            # Run the worker and Beat as separate supervised programs instead of
            # one embedded process (`celery worker -B`), so that a Beat crash
            # can't wedge the worker and the two never contend over the schedule
            # file.
            for program, subcommand in (
                (service_name, 'worker'), (f'{service_name}-beat', 'beat')
            ):
                command = \
                    f'/opt/djevops/bin/celery.sh {service_name} {subcommand}'
                require_program(program, 'command.conf', command)
        elif service['type'] == 'command':
            require_program(service_name, 'command.conf', service['command'])
        else:
            error(f"Unknown service type: {service['type']}")

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
        backup_config = get_backup_config(config, secrets)
        if db_type == 'postgres':
            install_if_not_installed('postgresql')
            db_config = get_django_setting('DATABASES')['default']
            db_existed = postgres.provision(db_config)
            if backup_config and not db_existed:
                log('Restoring database backup...')
                postgres.restore(db_config, backup_config)
            log('Migrating database...')
            migrate_db()
            if backup_config:
                sync_interval_str = backup_config.get('sync-interval', '24h')
                sync_interval_secs = parse_sync_interval(sync_interval_str)
                cron_jobs.append(
                    f'{as_cron(sync_interval_secs)} cronic {DJEVOPS_PYTHON} -m '
                    f'djevops.remote.postgres backup'
                )
        else:
            if backup_config:
                require(Litestream())
                litestream_config = get_litestream_config(backup_config)
                with open('/etc/litestream.yml', 'w') as f:
                    yaml.safe_dump(litestream_config, f)
                if not exists(SQLITE_DB_FILE):
                    log('Restoring database backup...')
                    _run(['litestream', 'restore', SQLITE_DB_FILE])
            log('Migrating database...')
            migrate_db()
            chown(SQLITE_DB_FILE, group_name=django_group)
            chmod(SQLITE_DB_FILE, 0o660)
            if backup_config:
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
    # Restart those programs that were not already handled by `update`. The
    # Supervisorctl class lets us submit the commands concurrently for improved
    # speed.
    supervisorctl = Supervisorctl()
    for program_name, user, hup_eligible in programs:
        if program_name in updated_services:
            continue
        if hup_eligible and user not in changed_bashrcs:
            try:
                _run(['supervisorctl', 'signal', 'HUP', program_name])
            except CalledProcessError as e:
                if e.returncode != 7:
                    raise
                # The service wasn't running.
                supervisorctl.submit('start', program_name)
        else:
            supervisorctl.submit('restart', program_name)
    supervisorctl.wait()
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
    for program_name, user, hup_eligible in programs:
        if supervisor_status.get(program_name) != 'RUNNING':
            any_service_failed = True
            print('\n' + line)
            log_file = f'/var/log/{program_name}.log'
            with open(log_file) as f:
                print(f.read().rstrip())
    if any_service_failed:
        error('Some services failed to start. See logs above.')

    _run('nginx -s reload')

    symlink_force('/opt/djevops/bin/cronic', '/usr/bin/cronic')
    require(Crontab(cron_jobs, mailto=admin_email))

    install_if_not_installed('unattended-upgrades')
    with open('/etc/apt/apt.conf.d/20auto-upgrades', 'w') as f:
        f.write('APT::Periodic::Update-Package-Lists "1";\n')
        f.write('APT::Periodic::Unattended-Upgrade "1";\n')

    if registry.uninstall_unused():
        _run('supervisorctl update')
        _run('nginx -s reload')

    server_url = f'https://{primary_domain}' if primary_domain \
        else f'http://{server_ip}'
    log(f'The server is now serving requests at {server_url}.')

def debconf_set_selections(value):
    run(['debconf-set-selections'], input=value + '\n', text=True, check=True)

class Supervisorctl:
    def __init__(self):
        self.pending = []
    def submit(self, *args):
        self.pending.append(
            Popen(['supervisorctl', *args], stdout=DEVNULL, stderr=DEVNULL)
        )
    def wait(self):
        for process in self.pending:
            process.wait()

if __name__ == '__main__':
    try:
        main()
    except CalledProcessError as e:
        output = e.stderr or e.stdout
        error(f'Command failed: {e.cmd}\nOutput: {output}')
