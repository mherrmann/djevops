from djevops.remote.util import chown, ensure_group_exists, \
    ensure_user_exists, run as _run, symlink_force
from djevops.util import copy_with_replace, get_apt_install_cmd
from hashlib import sha256
from os import chmod, makedirs, remove
from os.path import exists, expanduser, join
from shlex import quote
from shutil import rmtree
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve

import json

class Component:

    def __init__(self, source_files=()):
        self.source_files = source_files

    @property
    def key(self):
        return None

    def install(self):
        raise NotImplementedError

    def uninstall(self):
        raise NotImplementedError

    def calculate_hash(self):
        hash = sha256()
        hash.update(json.dumps(vars(self), sort_keys=True).encode())
        for path in self.source_files:
            with open(path, 'rb') as f:
                hash.update(f.read())
        return hash.hexdigest()


class AptPackage(Component):

    def __init__(self, name):
        super().__init__()
        self.name = name

    def install(self):
        _run(get_apt_install_cmd(self.name))

    def uninstall(self):
        _run(f'apt-get purge -yqq {self.name}')

    @property
    def key(self):
        return self.name

    def __str__(self):
        return self.name


class SshKey(Component):

    def __init__(self, contents):
        super().__init__()
        self.contents = contents

    def install(self):
        with open(self._path, 'w') as f:
            f.write(self.contents)
        chmod(self._path, 0o600)
        _run(f"ssh-keygen -y -f {self._path} > {self._path}.pub")
        chmod(f'{self._path}.pub', 0o644)

    def uninstall(self):
        for path in (self._path, f'{self._path}.pub'):
            try:
                remove(path)
            except FileNotFoundError:
                pass

    @property
    def _path(self):
        return expanduser('~/.ssh/id_rsa')

    def __str__(self):
        return f'SSH key {self._path}'


class KnownHostsEntry(Component):

    def __init__(self, host):
        super().__init__()
        self.host = host

    def install(self):
        _run(f"ssh-keyscan -H {self.host} >> {self._path} 2>/dev/null")
        chmod(self._path, 0o600)

    def uninstall(self):
        _run(f'ssh-keygen -R {self.host} -f {self._path} 2>/dev/null')

    @property
    def key(self):
        return self.host

    @property
    def _path(self):
        return expanduser('~/.ssh/known_hosts')

    def __str__(self):
        return f'Known hosts entry for {self.host}'


class PreinstallScript(Component):

    def __init__(self, path):
        super().__init__((path,))
        self.path = path

    def install(self):
        with TemporaryDirectory() as temp_dir:
            _run([self.path], cwd=temp_dir)

    def uninstall(self):
        pass

    def __str__(self):
        return 'preinstall script'


class VirtualEnvironment(Component):

    def __init__(self, path):
        super().__init__()
        self.path = path

    def install(self):
        _run(f'uv venv -c {self.path}')

    def uninstall(self):
        rmtree(self.path, ignore_errors=True)

    @property
    def key(self):
        return self.path

    def __str__(self):
        return f'Virtual environment {self.path}'


class ServiceUser(Component):

    BASH_PROFILE_PATH = '/opt/djevops/conf/.bash_profile'

    def __init__(self, user, env, group):
        super().__init__((self.BASH_PROFILE_PATH,))
        self.user = user
        self.env = env
        self.group = group

    def install(self):
        ensure_group_exists(self.user)
        ensure_user_exists(self.user, self.user)
        _run(f'usermod -a -G {self.group} {self.user}')
        makedirs(self._home_dir, exist_ok=True)
        chown(self._home_dir, self.user, self.user)
        chmod(self._home_dir, 0o700)
        symlink_force(
            self.BASH_PROFILE_PATH, f'{self._home_dir}/.bash_profile'
        )
        with open(self._bashrc_path, 'w') as f:
            f.write(self._bashrc_contents)
        chown(self._bashrc_path, self.user, self.user)

    def uninstall(self):
        _run(['userdel', '-r', self.user], ignore_errors=(6, 8, 12))
        _run(['groupdel', self.user], ignore_errors=(6, 8))

    @property
    def key(self):
        return self.user

    @property
    def _home_dir(self):
        return f'/home/{self.user}'

    @property
    def _bashrc_path(self):
        return f'{self._home_dir}/.bashrc'

    @property
    def _bashrc_contents(self):
        return '\n'.join(
            f'export {key}={quote(value)}' for key, value in self.env.items()
        )

    def __str__(self):
        return f'Service user {self.user}'


class SelfSignedCertificate(Component):

    def __init__(self, directory, common_name):
        super().__init__()
        self.directory = directory
        self.common_name = common_name

    def install(self):
        makedirs(self.directory, exist_ok=True)
        _run([
            'openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048',
            '-keyout', self._privkey_path,
            '-out', self._fullchain_path,
            '-days', '36500',
            '-subj', f'/CN={self.common_name}'
        ])

    def uninstall(self):
        rmtree(self.directory, ignore_errors=True)

    @property
    def key(self):
        return self.directory

    @property
    def _privkey_path(self):
        return join(self.directory, 'privkey.pem')

    @property
    def _fullchain_path(self):
        return join(self.directory, 'fullchain.pem')

    def __str__(self):
        return f'Self-signed certificate {self._privkey_path}'


class Litestream(Component):

    VERSION = '0.5.6'

    def install(self):
        deb_path, _ = urlretrieve(self._deb_url)
        _run(['dpkg', '-i', deb_path])
        remove(deb_path)

    def uninstall(self):
        _run('apt-get purge -yqq litestream')

    @property
    def _deb_url(self):
        return (
            f'https://github.com/benbjohnson/litestream/releases/download/'
            f'v{self.VERSION}/litestream-{self.VERSION}-linux-x86_64.deb'
        )

    def __str__(self):
        return f'Litestream {self.VERSION}'


class Hostname(Component):

    def __init__(self, name):
        super().__init__()
        self.name = name

    def install(self):
        _run(['hostnamectl', 'set-hostname', self.name])

    def uninstall(self):
        pass

    def __str__(self):
        return f'Hostname {self.name}'


class LetsEncryptRegistration(Component):

    ACCOUNTS_DIR = '/etc/letsencrypt/accounts'

    def __init__(self, email=''):
        super().__init__()
        self.email = email

    def install(self):
        if exists(self.ACCOUNTS_DIR):
            cmd = \
                ['certbot', 'update_account', '--quiet', '--email', self.email]
        else:
            cmd = ['certbot', 'register', '--quiet', '--agree-tos']
            if self.email:
                cmd.extend(['--email', self.email])
            else:
                cmd.append('--register-unsafely-without-email')
        _run(cmd)

    def uninstall(self):
        rmtree(self.ACCOUNTS_DIR, ignore_errors=True)

    def __str__(self):
        return "Let's Encrypt registration"


class LetsEncryptCertificate(Component):

    SSL_CONFIG_FILE = '/opt/djevops/conf/nginx/ssl'

    def __init__(self, name, domains):
        super().__init__((self.SSL_CONFIG_FILE,))
        self.name = name
        self.domains = domains

    def install(self):
        cmd = [
            'certbot', 'certonly', '--nginx', '--cert-name', self.name,
            '--quiet'
        ]
        for domain in self.domains:
            cmd.extend(['-d', domain])
        _run(cmd)
        copy_with_replace(
            self.SSL_CONFIG_FILE,
            self._ssl_include_path,
            {'$SERVICE': self.name}
        )

    def uninstall(self):
        _run([
            'certbot', 'delete', '--cert-name', self.name, '--non-interactive'
        ])
        try:
            remove(self._ssl_include_path)
        except FileNotFoundError:
            pass

    @property
    def key(self):
        return self.name

    @property
    def _ssl_include_path(self):
        return f'/etc/nginx/includes/{self.name}-ssl'

    def __str__(self):
        return f"Let's Encrypt certificate {self.name}"


class IptablesRules(Component):

    def __init__(self, accept=(), reject=()):
        super().__init__()
        self.accept = list(accept)
        self.reject = list(reject)

    def install(self):
        for rule in self.accept:
            _run(f'iptables -A INPUT {rule} -j ACCEPT')
        for rule in self.reject:
            _run(f'iptables -A INPUT {rule} -j REJECT')
        _run('iptables-save > /etc/iptables/rules.v4')

    def uninstall(self):
        for rule in self.accept:
            _run(f'iptables -D INPUT {rule} -j ACCEPT', ignore_errors=(1,))
        for rule in self.reject:
            _run(f'iptables -D INPUT {rule} -j REJECT', ignore_errors=(1,))
        _run('iptables-save > /etc/iptables/rules.v4')

    def __str__(self):
        return 'iptables rules'


class Postfix(Component):

    MAIN_CF_FILE = '/opt/djevops/conf/postfix/main.cf'
    SASL_PASSWD_FILE = '/opt/djevops/conf/postfix/sasl_passwd'
    GENERIC_FILE = '/opt/djevops/conf/postfix/generic'

    def __init__(
        self, hostname, smtp_host, smtp_user, smtp_password, server_email
    ):
        super().__init__(
            (self.MAIN_CF_FILE, self.SASL_PASSWD_FILE, self.GENERIC_FILE)
        )
        self.hostname = hostname
        self.smtp_host = smtp_host
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.server_email = server_email

    def install(self):
        with open('/etc/mailname', 'w') as f:
            f.write(self.hostname + '\n')
        chown('/etc/mailname', 'postfix')
        copy_with_replace(
            self.MAIN_CF_FILE,
            '/etc/postfix/main.cf',
            {
                '$HOST_NAME': self.hostname,
                '$SMTP_HOST': self.smtp_host,
            }
        )
        copy_with_replace(
            self.SASL_PASSWD_FILE,
            '/etc/postfix/sasl_passwd',
            {
                '$SMTP_HOST': self.smtp_host,
                '$SMTP_USER': self.smtp_user,
                '$SMTP_PASSWORD': self.smtp_password,
            }
        )
        chown('/etc/postfix', 'postfix')
        try:
            remove('/etc/postfix/sasl_passwd.db')
        except FileNotFoundError:
            pass
        _run('postmap /etc/postfix/sasl_passwd')
        chmod('/etc/postfix/sasl_passwd', 0o400)
        chown('/etc/postfix/sasl_passwd', 'postfix')
        if self.server_email:
            copy_with_replace(
                self.GENERIC_FILE,
                '/etc/postfix/generic',
                {
                    '$HOST_NAME': self.hostname,
                    '$SERVER_EMAIL': self.server_email,
                }
            )
        else:
            # main.cf always references the map, so keep an empty one rather
            # than none at all.
            open('/etc/postfix/generic', 'w').close()
        if exists('/etc/postfix/generic.db'):
            remove('/etc/postfix/generic.db')
        _run('postmap /etc/postfix/generic')
        chown('/etc/postfix/generic', 'postfix')
        _run('/etc/init.d/postfix reload')

    def uninstall(self):
        for path in (
            '/etc/mailname',
            '/etc/postfix/sasl_passwd',
            '/etc/postfix/sasl_passwd.db',
            '/etc/postfix/generic',
            '/etc/postfix/generic.db',
        ):
            try:
                remove(path)
            except FileNotFoundError:
                pass

    def __str__(self):
        return 'Postfix'


class Crontab(Component):

    def __init__(self, jobs, mailto=''):
        super().__init__()
        self.jobs = list(jobs)
        self.mailto = mailto

    def install(self):
        lines = []
        if self.mailto:
            lines.append(f'MAILTO={self.mailto}')
        lines.extend(self.jobs)
        with open('crontab', 'w') as f:
            f.write('\n'.join(lines) + '\n')
        _run('crontab crontab')
        remove('crontab')

    def uninstall(self):
        _run(['crontab', '-r'], ignore_errors=(1,))

    def __str__(self):
        return 'crontab'


class NginxSite(Component):

    def __init__(self, name, source, replacements):
        super().__init__((source,))
        self.name = name
        self.source = source
        self.replacements = replacements

    def install(self):
        copy_with_replace(self.source, self._available_path, self.replacements)
        symlink_force(self._available_path, self._enabled_path)

    def uninstall(self):
        for path in (self._enabled_path, self._available_path):
            try:
                remove(path)
            except FileNotFoundError:
                pass

    @property
    def key(self):
        return self.name

    @property
    def _available_path(self):
        return f'/etc/nginx/sites-available/{self.name}'

    @property
    def _enabled_path(self):
        return f'/etc/nginx/sites-enabled/{self.name}'

    def __str__(self):
        return f'nginx site {self.name}'


class TemplatedFile(Component):

    def __init__(self, target, source, replacements):
        super().__init__((source,))
        self.target = target
        self.source = source
        self.replacements = replacements

    def install(self):
        copy_with_replace(self.source, self.target, self.replacements)

    def uninstall(self):
        try:
            remove(self.target)
        except FileNotFoundError:
            pass

    @property
    def key(self):
        return self.target

    def __str__(self):
        return self.target
