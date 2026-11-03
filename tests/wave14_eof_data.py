#!/usr/bin/env python3
"""Finite half-close controls: preserve input accepted before a FIN."""
import argparse
import copy
import json
import os
from pathlib import Path
import socket
import time
from _lib import Conn, encode
from persistfix2 import boot, wait


def probe(a, admin, count, suffix=b'', control=()):
    key = f'wave14:fin:{count}:{int(bool(suffix))}' + (f':{control}' if control else '')
    assert admin.must('DEL', key) == 0
    client = Conn('127.0.0.1', a.port)
    identity = client.must('CLIENT', 'ID')
    replies = []
    error = None
    try:
        prefix = encode(*control) if control else b''
        client.sock.sendall(prefix + encode('INCR', key) * count + suffix)
        client.sock.shutdown(socket.SHUT_WR)
        # Keep the read half open, so an RST cannot explain discarded input.
        client._read_deadline = time.monotonic() + 10
        try:
            for _ in range(count + bool(control)):
                replies.append(client.read())
            assert client.file.read(1) == b'', 'reply stream did not end'
        except Exception as failure:
            error = repr(failure)
        wait(lambda: not any(line.startswith(f'id={identity} '.encode())
                             for line in admin.must('CLIENT', 'LIST').splitlines()),
             'half-closed client retired', 10)
        value = admin.must('GET', key)
    finally:
        client.close()
    expected = ([b'OK'] if control else []) + list(range(1, count + 1))
    return dict(count=count, applied=int(value or b'0'), replies=len(replies),
                ordered=replies == expected, error=error,
                partial_suffix=bool(suffix), control=list(control))


def stalled_reply(a, admin):
    key = 'wave14:fin:large-reply'
    assert admin.must('SET', key, b'x' * (4 * 1024 * 1024)) == b'OK'
    client = Conn('127.0.0.1', a.port, rcvbuf=1024)
    identity = client.must('CLIENT', 'ID')
    try:
        client.send('GET', key)
        client.sock.shutdown(socket.SHUT_WR)
        wait(lambda: not any(line.startswith(f'id={identity} '.encode())
                             for line in admin.must('CLIENT', 'LIST').splitlines()),
             'non-reading half-closed client retired', 5)
    finally:
        client.close()
        admin.must('DEL', key)
    return dict(kind='stalled-reply', retired=True)


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
                for count, suffix in [(n, b'') for n in (1, 32, 65, 256, 4096, 65536)] + [
                        (65, b'*2\r\n$4\r\nINCR\r\n$20\r\ntruncated')]:
                    try:
                        row = dict(leg=leg.output.name, **probe(leg, admin, count, suffix))
                        rows.append(row); print(row, flush=True)
                        if row['count'] != row['applied'] or not row['ordered'] or row['error']:
                            failures.append(row)
                    except Exception as error:
                        row = dict(leg=leg.output.name, count=count, error=repr(error))
                        rows.append(row); failures.append(row); print(row, flush=True)
                try:
                    row = dict(leg=leg.output.name, **stalled_reply(leg, admin))
                    rows.append(row); print(row, flush=True)
                except Exception as error:
                    row = dict(leg=leg.output.name, kind='stalled-reply', error=repr(error))
                    rows.append(row); failures.append(row); print(row, flush=True)
                for control in [('DEBUG', 'SLEEP', '.02'), ('CLIENT', 'TRACKING', 'ON')]:
                    try:
                        row = dict(leg=leg.output.name, **probe(leg, admin, 65, control=control))
                        rows.append(row); print(row, flush=True)
                        if row['count'] != row['applied'] or not row['ordered'] or row['error']:
                            failures.append(row)
                    except Exception as error:
                        row = dict(leg=leg.output.name, control=list(control), error=repr(error))
                        rows.append(row); failures.append(row); print(row, flush=True)
        except Exception as error:
            failures.append(dict(leg=leg.output.name, error=repr(error)))
        (a.output/'results.json').write_text(json.dumps(dict(rows=rows, failures=failures), indent=2)+'\n')
    assert not failures, failures


if __name__ == '__main__': main()
