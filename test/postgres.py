from djevops.util import run_silently
from os import environ, makedirs, pathsep
from os.path import join
from tempfile import TemporaryDirectory

def query_postgres_dump(dump_path, sql):
    with TemporaryDirectory() as tmp_dir:
        data_dir = join(tmp_dir, 'data')
        socket_dir = join(tmp_dir, 'sock')
        makedirs(socket_dir)
        env = _get_postgres_env()
        run_silently([
            'initdb', '-D', data_dir, '-A', 'trust', '-U', 'postgres'
        ], env=env)
        # `-l` is essential: it redirects the server's output to a log file.
        # Without it, the started server inherits our stdout pipe and keeps it
        # open, so `run_silently` would block forever waiting for EOF.
        run_silently([
            'pg_ctl', '-D', data_dir, '-l', '/dev/null', '-w', '-o',
            f'-k {socket_dir} -c listen_addresses=', 'start'
        ], env=env)
        try:
            run_silently([
                'psql', '-h', socket_dir, '-U', 'postgres', '-q', '-f',
                dump_path
            ])
            output = run_silently([
                'psql', '-h', socket_dir, '-U', 'postgres', '-tAc', sql
            ])
        finally:
            run_silently(['pg_ctl', '-D', data_dir, '-w', 'stop'], env=env)
    return int(output) if output else None

def _get_postgres_env():
    # On Debian, server binaries like `initdb` and `pg_ctl` are not on PATH;
    # they live in `pg_config --bindir` (e.g. /usr/lib/postgresql/15/bin).
    bindir = run_silently(['pg_config', '--bindir'])
    return {**environ, 'PATH': bindir + pathsep + environ['PATH']}
