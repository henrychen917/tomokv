#!/usr/bin/env python3
"""Bounded PRE reproduction: unchanged upstream Tcl assertion and raw wire bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import redis_tcl
from _lib import encode


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.binary = args.binary.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    redis = Path('/home/user/Projects/redis')
    tree = args.output / 'checkout'
    redis_tcl.prepare(redis, tree, controller_port=20301)
    rows = []
    for mode, engine in [('redis', None), ('1s', 'epoll'), ('1s', 'uring'),
                         ('2s', 'epoll'), ('2s', 'uring')]:
        label = mode + ('-' + engine if engine else '')
        out = args.output / label
        out.mkdir(exist_ok=True)
        binary = redis / 'src/redis-server' if mode == 'redis' else args.binary
        cfg = SimpleNamespace(binary=binary, mode=mode, cores='0-7', port=20300,
                              baseport=20302, ratio='6:2', output=out,
                              idle_timeout=5, file_timeout=15)
        extra = ['--net-io', engine] if engine else []
        tcl = redis_tcl.run_file(cfg, tree, 'unit/functions',
            only=['FUNCTION - test function list with CRLF injection attempt'],
            server_args=extra)
        command = ['taskset', '-c', '0-7', str(binary), '--port', '20300',
                   '--bind', '127.0.0.1', '--save', '', '--appendonly', 'no',
                   '--dir', str(out)]
        if mode != 'redis':
            command += ['--thread-mode', mode, '--shards', '16', *extra]
            if mode == '2s': command += ['--ratio', '6:2']
        with (out / 'wire-server.log').open('w') as log:
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                for _ in range(100):
                    if proc.poll() is not None:
                        raise RuntimeError('server exited during boot')
                    try:
                        sock = socket.create_connection(('127.0.0.1', 20300), timeout=2)
                        break
                    except OSError:
                        time.sleep(.05)
                else:
                    raise RuntimeError('server boot timeout')
                with sock:
                    sock.sendall(encode('FUNCTION', 'LIST', b'X\r\n+INJECTED') + encode('PING'))
                    raw = b''
                    while not raw.endswith(b'+PONG\r\n'):
                        part = sock.recv(65536)
                        if not part: raise EOFError('missing PING reply')
                        raw += part
                rows.append(dict(mode=mode, engine=engine,
                    sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                    raw=raw.decode('latin1'), hex=raw.hex(), tcl=tcl))
                print(label, repr(raw), 'Tcl:', tcl['passed'], tcl['failed'], tcl['error'], flush=True)
            finally:
                redis_tcl.stop(proc)
        (args.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
