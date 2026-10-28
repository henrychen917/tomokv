#!/usr/bin/env python3
"""Bounded PRE/oracle reproductions and unchanged upstream Tcl assertions."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from _lib import Conn, info
from compat3_blockfix2 import removed, waiter
from compat3_lib import wire
import redis_tcl

TEST = 'XGROUP DESTROY should unblock XREADGROUP with -NOGROUP'


def probe(c):
    clients = []
    result = {}
    try:
        try:
            result['removal'] = wire(removed(c, clients))
        except Exception as error:
            result['removal_error'] = repr(error)
        for client in clients: client.close()
        clients.clear()
        c.cmd('FLUSHALL')
        c.cmd('CONFIG', 'RESETSTAT')
        c.cmd('XGROUP', 'CREATE', 'stats', 'g', '$', 'MKSTREAM')
        w = waiter(c, clients, 'XREADGROUP', 'GROUP', 'g', 'c', 'BLOCK', 0,
                   'STREAMS', 'stats', '>')
        c.cmd('XGROUP', 'DESTROY', 'stats', 'g')
        result['reply'] = wire(w.read())
        result['errorstat'] = info(c, 'errorstats').get('errorstat_NOGROUP')
        result['cmdstat'] = info(c, 'commandstats').get('cmdstat_xreadgroup')
        result['total_errors'] = info(c, 'stats').get('total_error_replies')
        return result
    finally:
        for client in clients: client.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--expect', choices=('pre', 'post'), required=True)
    a = p.parse_args()
    a.binary = a.binary.resolve(); a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=True)
    tree = a.output / 'checkout'
    redis_tcl.prepare(Path('/home/user/Projects/redis'), tree, controller_port=20191)
    rows = []
    for mode, engine in [('redis', None)] + [(m, e) for m in ('1s', '2s') for e in ('epoll', 'uring')]:
        binary = Path('/home/user/Projects/redis74/src/redis-server') if mode == 'redis' else a.binary
        folder = a.output / f'{mode}-{engine}'
        folder.mkdir(exist_ok=True)
        argv = ['taskset', '-c', '0-7', str(binary), '--port', '20190',
                '--bind', '127.0.0.1', '--save', '', '--appendonly', 'no', '--dir', str(folder)]
        if engine:
            argv += ['--thread-mode', mode, '--net-io', engine, '--shards', '16', '--databases', '16']
            if mode == '2s': argv += ['--ratio', '6:2']
        with (folder / 'server.log').open('w') as log:
            server = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            c = None
            try:
                for _ in range(200):
                    if server.poll() is not None: raise RuntimeError('server exited')
                    try:
                        c = Conn('127.0.0.1', 20190, timeout=3, buffering=0)
                        if c.cmd('PING') == b'PONG': break
                    except OSError: time.sleep(.025)
                else: raise RuntimeError('boot deadline')
                result = probe(c)
            finally:
                if c: c.close()
                redis_tcl.stop(server)
        run = argparse.Namespace(output=folder / 'tcl', binary=binary, cores='0-7',
            port=20190, baseport=20192, mode=mode, ratio='6:2', idle_timeout=15, file_timeout=45)
        tcl = redis_tcl.run_file(run, tree, 'unit/type/stream-cgroups', only=[TEST],
                               server_args=['--net-io', engine] if engine else [])
        result.update(mode=mode, engine=engine, sha256=redis_tcl.sha(binary), argv=argv,
                      tcl_passed=tcl['passed'], tcl_failed=tcl['failed'], tcl_error=tcl['error'])
        rows.append(result)
        (a.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(mode, engine, json.dumps(result), flush=True)
        expected_pass = mode == 'redis' or a.expect == 'post'
        assert ('removal_error' not in result) == expected_pass
        assert (result['errorstat'] == 'count=1') == expected_pass
        assert (result['total_errors'] == '1') == expected_pass
        assert (tcl['passed'] == 1 and tcl['failed'] == 0 and tcl['complete']) == expected_pass


if __name__ == '__main__': main()
