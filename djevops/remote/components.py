from djevops.remote.util import chown, ensure_group_exists, \
    ensure_user_exists, run as _run, symlink_force
from djevops.util import copy_with_replace, get_apt_install_cmd
from os import chmod, makedirs, remove
from os.path import exists, expanduser, join
from urllib.request import urlretrieve

class Component:

    @property
    def key(self):
        return None

    @property
    def state(self):
        return None

    def install(self):
        raise NotImplementedError


class AptPackage(Component):

    def __init__(self, name):
        self.name = name

    def install(self):
        _run(get_apt_install_cmd(self.name))

    @property
    def key(self):
        return self.name

    def __str__(self):
        return self.name


class SshKey(Component):

    def __init__(self, contents):
        self.contents = contents

    def install(self):
        with open(self._path, 'w') as f:
            f.write(self.contents)
        chmod(self._path, 0o600)
        _run(f"ssh-keygen -y -f {self._path} > {self._path}.pub")
        chmod(f'{self._path}.pub', 0o644)

    @property
    def state(self):
        return self.contents

    @property
    def _path(self):
        return expanduser('~/.ssh/id_rsa')

    def __str__(self):
        return f'SSH key {self._path}'


class KnownHostsEntry(Component):

    def __init__(self, host):
        self.host = host

    def install(self):
        _run(f"ssh-keyscan -H {self.host} >> {self._path} 2>/dev/null")
        chmod(self._path, 0o600)

    @property
    def key(self):
        return self.host

    @property
    def _path(self):
        return expanduser('~/.ssh/known_hosts')

    def __str__(self):
        return f'Known hosts entry for {self.host}'


class VirtualEnvironment(Component):

    def __init__(self, path):
        self.path = path

    def install(self):
        _run(f'uv venv {self.path}')

    @property
    def key(self):
        return self.path

    def __str__(self):
        return f'Virtual environment {self.path}'


class ServiceUser(Component):

    def __init__(self, user, env, group):
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
            '/opt/djevops/conf/.bash_profile', f'{self._home_dir}/.bash_profile'
        )
        with open(self._bashrc_path, 'w') as f:
            f.write(self._bashrc_contents)
        chown(self._bashrc_path, self.user, self.user)

    @property
    def key(self):
        return self.user

    @property
    def state(self):
        return {'env': self.env, 'group': self.group}

    @property
    def _home_dir(self):
        return f'/home/{self.user}'

    @property
    def _bashrc_path(self):
        return f'{self._home_dir}/.bashrc'

    @property
    def _bashrc_contents(self):
        return '\n'.join(
            f'export {key}="{value}"' for key, value in self.env.items()
        )

    def __str__(self):
        return f'Service user {self.user}'


class SelfSignedCertificate(Component):

    def __init__(self, directory, common_name):
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

    @property
    def key(self):
        return self.directory

    @property
    def state(self):
        return self.common_name

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
        self.name = name

    def install(self):
        _run(['hostnamectl', 'set-hostname', self.name])

    @property
    def state(self):
        return self.name

    def __str__(self):
        return f'Hostname {self.name}'


class LetsEncryptRegistration(Component):

    ACCOUNTS_DIR = '/etc/letsencrypt/accounts'

    def __init__(self, email=''):
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

    @property
    def state(self):
        return self.email

    def __str__(self):
        return "Let's Encrypt registration"


class IptablesRules(Component):

    def __init__(self, accept=(), reject=()):
        self.accept = list(accept)
        self.reject = list(reject)

    def install(self):
        for rule in self.accept:
            _run(f'iptables -A INPUT {rule} -j ACCEPT')
        for rule in self.reject:
            _run(f'iptables -A INPUT {rule} -j REJECT')
        _run('iptables-save > /etc/iptables/rules.v4')

    @property
    def state(self):
        return {'accept': self.accept, 'reject': self.reject}

    def __str__(self):
        return 'iptables rules'


class Postfix(Component):

    def __init__(self, hostname, smtp_host, smtp_user, smtp_password):
        self.hostname = hostname
        self.smtp_host = smtp_host
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password

    def install(self):
        with open('/etc/mailname', 'w') as f:
            f.write(self.hostname + '\n')
        chown('/etc/mailname', 'postfix')
        copy_with_replace(
            '/opt/djevops/conf/postfix/main.cf',
            '/etc/postfix/main.cf',
            {
                '$HOST_NAME': self.hostname,
                '$SMTP_HOST': self.smtp_host,
            }
        )
        copy_with_replace(
            '/opt/djevops/conf/postfix/sasl_passwd',
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
        _run(
            'envsubst < /opt/djevops/conf/postfix/generic > '
            '/etc/postfix/generic'
        )
        if exists('/etc/postfix/generic.db'):
            remove('/etc/postfix/generic.db')
        _run('postmap /etc/postfix/generic')
        chown('/etc/postfix/generic', 'postfix')
        _run('/etc/init.d/postfix reload')

    @property
    def state(self):
        return {
            'hostname': self.hostname,
            'smtp_host': self.smtp_host,
            'smtp_user': self.smtp_user,
            'smtp_password': self.smtp_password,
        }

    def __str__(self):
        return 'Postfix'
