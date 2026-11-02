#!/usr/bin/env python3
"""Finite half-close controls: preserve input accepted before a FIN."""
import argparse
import copy
import json
import os
from pathlib import Path
import socket
from _lib import Conn, encode
from persistfix2 import boot, wait


def probe(a, admin, count):
    key = f'wave14:fin:{count}'
    assert admin.must('DEL', key) == 0
    client = Conn('127.0.0.1', a.port)
    identity = client.must('CLIENT', 'ID')
    try:
        client.sock.sendall(encode('INCR', key) * count)
        client.sock.shutdown(socket.SHUT_WR)
        # Keep the read half open, so an RST cannot explain discarded input.
        wait(lambda: not any(line.startswith(f'id={identity} '.encode())
                             for line in admin.must('CLIENT', 'LIST').splitlines()),
             'half-closed client retired', 10)
        value = admin.must('GET', key)
    finally:
        client.close()
    return dict(count=count, applied=int(value or b'0'))


def main():
    p = argparse.ArgumentParser()
    for name in ('binary', 'oracle', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    a = p.parse_args(); os.environ['LC_ALL'] = 'C'
    a.output.mkdir(parents=True, exist_ok=True)
    legs = [(True, 'oracle', 'normal', 1)] + [
        (False, mode, engine, db) for mode in ('1s', '2s')
        for engine in ('uring', 'epoll') for db in (1, 16)]
    rows = []; failures = []
    for oracle, mode, engine, db in legs:
        leg = copy.copy(a); leg.oracle = oracle; leg.mode = mode; leg.engine = engine
        leg.output = a.output/f'{mode}-{engine}-db{db}'
        if oracle: leg.binary = a.oracle
        try:
            with boot(leg, 'server', ['--databases', str(db)]) as (_, admin, _):
                for count in (1, 32, 65, 256, 4096):
                    try:
                        row = dict(leg=leg.output.name, **probe(leg, admin, count))
                        rows.append(row); print(row, flush=True)
                        if row['count'] != row['applied']: failures.append(row)
                    except Exception as error:
                        row = dict(leg=leg.output.name, count=count, error=repr(error))
                        rows.append(row); failures.append(row); print(row, flush=True)
        except Exception as error:
            failures.append(dict(leg=leg.output.name, error=repr(error)))
        (a.output/'results.json').write_text(json.dumps(dict(rows=rows, failures=failures), indent=2)+'\n')
    assert not failures, failures


if __name__ == '__main__': main()
