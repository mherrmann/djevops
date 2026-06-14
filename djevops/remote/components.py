from djevops.remote.util import run as _run
from djevops.util import get_apt_install_cmd
from os import chmod
from os.path import expanduser
from subprocess import PIPE, STDOUT, run, CalledProcessError

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
