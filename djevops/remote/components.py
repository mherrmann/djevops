from djevops.remote.util import chown, ensure_group_exists, \
    ensure_user_exists, run as _run, symlink_force
from djevops.util import get_apt_install_cmd
from os import chmod, makedirs, remove
from os.path import expanduser, exists, join
from pwd import getpwnam
from shutil import which
from subprocess import PIPE, STDOUT, run, CalledProcessError
from urllib.request import urlretrieve

class Component:

    def is_installed(self):
        raise NotImplementedError

    def install(self):
        raise NotImplementedError


class AptPackage(Component):

    def __init__(self, name):
        self.name = name

    def is_installed(self):
        cp = run(
            ['dpkg', '-s', self.name],
            stdout=PIPE, stderr=STDOUT, text=True
        )
        if cp.returncode == 0:
            return True
        elif cp.returncode == 1 and 'is not installed' in cp.stdout:
            return False
        raise CalledProcessError(cp.returncode, cp.args, cp.stdout)

    def install(self):
        _run(get_apt_install_cmd(self.name))

    def __str__(self):
        return self.name


class SshKey(Component):

    def __init__(self, contents):
        self.contents = contents

    def is_installed(self):
        try:
            with open(self._path) as f:
                return f.read() == self.contents
        except FileNotFoundError:
            return False

    def install(self):
        with open(self._path, 'w') as f:
            f.write(self.contents)
        chmod(self._path, 0o600)
        _run(f"ssh-keygen -y -f {self._path} > {self._path}.pub")
        chmod(f'{self._path}.pub', 0o644)

    @property
    def _path(self):
        return expanduser('~/.ssh/id_rsa')

    def __str__(self):
        return f'SSH key {self._path}'


class KnownHostsEntry(Component):

    def __init__(self, host):
        self.host = host

    def is_installed(self):
        try:
            with open(self._path) as f:
                return self.host in f.read()
        except FileNotFoundError:
            return False

    def install(self):
        _run(f"ssh-keyscan -H {self.host} >> {self._path} 2>/dev/null")
        chmod(self._path, 0o600)

    @property
    def _path(self):
        return expanduser('~/.ssh/known_hosts')

    def __str__(self):
        return f'Known hosts entry for {self.host}'


class VirtualEnvironment(Component):

    def __init__(self, path):
        self.path = path

    def is_installed(self):
        return exists(self.path)

    def install(self):
        _run(f'uv venv {self.path}')

    def __str__(self):
        return f'Virtual environment {self.path}'


class ServiceUser(Component):

    def __init__(self, user, env, group):
        self.user = user
        self.env = env
        self.group = group

    def is_installed(self):
        try:
            getpwnam(self.user)
        except KeyError:
            return False
        try:
            with open(self._bashrc_path) as f:
                return f.read() == self._bashrc_contents
        except FileNotFoundError:
            return False

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

    def is_installed(self):
        return exists(self._privkey_path)

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
    def _privkey_path(self):
        return join(self.directory, 'privkey.pem')

    @property
    def _fullchain_path(self):
        return join(self.directory, 'fullchain.pem')

    def __str__(self):
        return f'Self-signed certificate {self._privkey_path}'


class Litestream(Component):

    VERSION = '0.5.6'

    def is_installed(self):
        return which('litestream') is not None

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

    def is_installed(self):
        return _run('hostname') == self.name

    def install(self):
        _run(['hostnamectl', 'set-hostname', self.name])

    def __str__(self):
        return f'Hostname {self.name}'
