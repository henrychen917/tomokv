#!/usr/bin/env python3
"""AT4 directed compatibility checks. Every declared leg runs, including on PRE."""
import argparse
import contextlib
import json
from pathlib import Path
import subprocess
import traceback

from _lib import Conn, wait_ready
from _gate_process import quiesce_connections, stop_process


@contextlib.contextmanager
def boot(binary, cores, port, directory, flags, oracle=False):
    directory.mkdir(parents=True, exist_ok=False)
    listeners = subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{port}'], text=True)
    assert not listeners.strip(), (port, listeners)
    argv = ['taskset', '-c', cores, str(Path(binary).resolve()), '--bind', '127.0.0.1',
            '--port', str(port), '--dir', str(directory.resolve()), '--save', '',
            '--appendonly', 'no', '--enable-debug-command', 'yes', *flags]
    (directory / 'argv.json').write_text(json.dumps(argv) + '\n')
    with (directory / 'server.log').open('w') as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    conn = None
    try:
        conn = wait_ready('127.0.0.1', port, process=process,
                          log_path=None if oracle else directory / 'server.log', timeout=20)
        assert int(dict(line.split(b':', 1) for line in conn.must('INFO', 'server').splitlines()
                        if b':' in line)[b'process_id']) == process.pid
        yield conn
    finally:
        try:
            if conn:
                try:
                    quiesce_connections(conn, process)
                finally:
                    conn.close()
        finally:
            forced = stop_process(process)
            (directory / 'exit.json').write_text(json.dumps(dict(rc=process.returncode, forced=forced)) + '\n')
            assert not forced and process.returncode == 0, (process.returncode, directory)


def watch_trace(admin, port, databases):
    trace = []
    with contextlib.closing(Conn('127.0.0.1', port)) as client:
        ident = client.must('CLIENT', 'ID')
        def sample(label):
            own = dict(x.split(b'=', 1) for x in client.must('CLIENT', 'INFO').strip().split())
            rows = [dict(x.split(b'=', 1) for x in row.split())
                    for row in admin.must('CLIENT', 'LIST').splitlines()]
            listed = next(row for row in rows if int(row[b'id']) == ident)
            trace.append((label, int(own[b'watch']), int(listed[b'watch'])))
        sample('initial')
        assert client.must('WATCH', 'watch:a', 'watch:b', 'watch:a') == b'OK'
        sample('two')
        assert client.must('WATCH', 'watch:a') == b'OK'
        sample('duplicate')
        if databases > 1:
            assert client.must('SELECT', 1) == b'OK'
            assert client.must('WATCH', 'watch:a') == b'OK'
            sample('same name in another database')
            assert admin.must('SWAPDB', 0, 1) == b'OK'
            sample('after swap')
        assert client.must('UNWATCH') == b'OK'
        sample('unwatch')
        assert client.must('WATCH', 'watch:a', 'watch:b') == b'OK'
        assert client.must('MULTI') == b'OK'
        assert client.must('PING') == b'QUEUED'
        assert client.must('EXEC') == [b'PONG']
        sample('exec')
        assert client.must('WATCH', 'watch:a') == b'OK'
        assert client.must('MULTI') == b'OK'
        assert client.must('DISCARD') == b'OK'
        sample('discard')
    return trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--oracle', required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=['watch'], required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    failures = []
    with boot(args.oracle, args.cores, args.port + 1, args.output / 'oracle',
              ['--databases', '16'], oracle=True) as oracle:
        expected = {db: watch_trace(oracle, args.port + 1, db) for db in (1, 16)}
        assert [row[1] for row in expected[16]] == [0, 2, 2, 3, 3, 0, 0, 0], expected
        print(json.dumps(dict(oracle=expected)), flush=True)
        for mode in ('1s', '2s'):
            for engine in ('uring', 'epoll'):
                for atomic in (0, 1):
                    for db in (1, 16):
                        label = f'{mode}-{engine}-atomic{atomic}-db{db}'
                        try:
                            flags = ['--shards', '16', '--thread-mode', mode,
                                     '--net-io', engine, '--atomic', str(atomic), '--databases', str(db),
                                     '--read-local', '1' if mode == '1s' else '0',
                                     '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
                            if mode == '2s':
                                flags += ['--ratio', args.ratio]
                            with boot(args.binary, args.cores, args.port, args.output / label, flags) as admin:
                                observed = watch_trace(admin, args.port, db)
                                print(json.dumps(dict(leg=label, observed=observed, expected=expected[db])), flush=True)
                                assert observed == expected[db], (label, observed, expected[db])
                        except Exception:
                            failures.append(label)
                            traceback.print_exc()
    print(json.dumps(dict(case=args.case, failures=failures)), flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
