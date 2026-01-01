from subprocess import run

import sys

def main():
    assert sys.argv[1] == 'setup'
    host = 'root@' + read_host_name_from_bashrc()
    ssh = lambda cmd: run(['ssh', host] + cmd, check=True)
    ssh(['apt-get', 'update', '-qq'])
    ssh(['apt-get', 'install', 'rsync', '-yqq'])
    run(['rsync', '-r', '.', f'{host}:/opt/djevops/'], check=True)
    run(['scp', '.bashrc', f'{host}:/root/.bashrc'], check=True)
    ssh(['python3', '/opt/djevops/djevops/remote/setup.py'])


def read_host_name_from_bashrc():
    prefix = 'export HOST_NAME='
    with open('.bashrc') as f:
        for line in f:
            if line.startswith(prefix):
                return line[len(prefix):].strip()
    raise ValueError(f'{prefix} not found in .bashrc')

if __name__ == '__main__':
    main()
