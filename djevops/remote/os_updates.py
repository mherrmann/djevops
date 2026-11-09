from djevops.remote.components import AptPackage, TemplatedFile
from djevops.remote.util import run as _run
from djevops.util import get_apt_uninstall_cmd
from os import makedirs

def setup(require):
    # Debian installs apt-listchanges by default. It emails root the NEWS
    # entries of every package that unattended-upgrades installs.
    _run(get_apt_uninstall_cmd('apt-listchanges'))
    require(AptPackage('unattended-upgrades'))
    # "always" makes apt act every time the timers below fire. Otherwise, it
    # acts at most once per day.
    require(TemplatedFile(
        '/etc/apt/apt.conf.d/20auto-upgrades',
        '/opt/djevops/conf/apt/20auto-upgrades', {}
    ))
    # Reboot when an update requires it, for example a new kernel:
    require(TemplatedFile(
        '/etc/apt/apt.conf.d/52unattended-upgrades-reboot',
        '/opt/djevops/conf/apt/52unattended-upgrades-reboot', {}
    ))
    # Fetch package lists every hour and install upgrades half an hour later:
    result = False
    for timer in ('apt-daily', 'apt-daily-upgrade'):
        makedirs(f'/etc/systemd/system/{timer}.timer.d', exist_ok=True)
        result |= require(TemplatedFile(
            f'/etc/systemd/system/{timer}.timer.d/override.conf',
            f'/opt/djevops/conf/systemd/{timer}.timer', {}
        ))
    return result

def restart_timers():
    _run('systemctl daemon-reload')
    _run('systemctl restart apt-daily.timer apt-daily-upgrade.timer')
