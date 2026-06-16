from djevops.util import run_silently
from os import makedirs
from os.path import join
from tempfile import TemporaryDirectory

def query_postgres_dump(dump_path, sql):
    with TemporaryDirectory() as tmp_dir:
        data_dir = join(tmp_dir, 'data')
        socket_dir = join(tmp_dir, 'sock')
        makedirs(socket_dir)
        run_silently([
            'initdb', '-D', data_dir, '-A', 'trust', '-U', 'postgres'
        ])
        # `-l` is essential: it redirects the server's output to a log file.
        # Without it, the started server inherits our stdout pipe and keeps it
        # open, so `run_silently` would block forever waiting for EOF.
        run_silently([
            'pg_ctl', '-D', data_dir, '-l', '/dev/null', '-w', '-o',
            f'-k {socket_dir} -c listen_addresses=', 'start'
        ])
        try:
            run_silently([
                'psql', '-h', socket_dir, '-U', 'postgres', '-q', '-f',
                dump_path
            ])
            output = run_silently([
                'psql', '-h', socket_dir, '-U', 'postgres', '-tAc', sql
            ])
        finally:
            run_silently(['pg_ctl', '-D', data_dir, '-w', 'stop'])
    return int(output) if output else None
