#!/usr/bin/env python3
"""CONFIG listener rollback must not join another process's SO_REUSEPORT group."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import traceback

from cfgfix2 import Server
import _netfix as n
from _lib import Conn, RespError


def listener(address, port, *, ipv6_only=None):
    sock = socket.socket(socket.AF_INET6 if ipv6_only is not None else socket.AF_INET)
    if ipv6_only is not None:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, int(ipv6_only))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind((address, port))
    sock.listen()
    return sock


def check(a, mode, engine, databases):
    label = f'{mode}-{engine}-d{databases}'
    record = dict(label=label, passed=False)
    try:
        with Server(a, label, mode, engine, extra=['--databases', str(databases)]):
            with closing(n.connect(a.port)) as c:
                original = c.must('CONFIG', 'GET', 'maxmemory')
                with listener('127.0.0.1', a.port + 2):
                    reply = c.cmd('CONFIG', 'SET', 'port', a.port + 2, 'maxmemory', '16mb')
                    assert isinstance(reply, RespError), ('foreign port admitted', reply)
                    assert c.must('CONFIG', 'GET', 'port') == [b'port', str(a.port).encode()]
                    assert c.must('CONFIG', 'GET', 'maxmemory') == original
                with listener('127.0.0.2', a.port):
                    for bind in ('127.0.0.2', '0.0.0.0'):
                        reply = c.cmd('CONFIG', 'SET', 'bind', bind)
                        assert isinstance(reply, RespError), ('foreign address admitted', bind, reply)
                        assert c.must('CONFIG', 'GET', 'bind') == [b'bind', b'127.0.0.1']
                with listener('::', a.port + 2, ipv6_only=False):
                    assert isinstance(c.cmd('CONFIG', 'SET', 'port', a.port + 2), RespError)
                with listener('::', a.port + 2, ipv6_only=True):
                    assert c.must('CONFIG', 'SET', 'port', a.port + 2) == b'OK'
                    assert c.must('CONFIG', 'SET', 'port', a.port) == b'OK'
                if mode != 'redis':  # Redis's listeners do not use SO_REUSEPORT.
                    with listener('::', a.port, ipv6_only=False):
                        assert isinstance(c.cmd('CONFIG', 'SET', 'bind', '0.0.0.0'), RespError)
                # A probe must distinguish our own overlapping old listeners.
                for bind in ('127.0.0.2', '0.0.0.0', '127.0.0.1'):
                    assert c.must('CONFIG', 'SET', 'bind', bind) == b'OK'
                    with closing(Conn('127.0.0.2' if bind == '127.0.0.2' else '127.0.0.1', a.port)) as other:
                        assert other.must('PING') == b'PONG'
                assert c.must('CONFIG', 'SET', 'port', a.port + 2) == b'OK'
                with closing(n.connect(a.port + 2)) as other:
                    assert other.must('PING') == b'PONG'
                assert c.must('CONFIG', 'SET', 'port', a.port) == b'OK'
        record['passed'] = True
    except Exception:
        record['error'] = traceback.format_exc()
    print(json.dumps(record), flush=True)
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'oracle', 'cores'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    os.environ['LC_ALL'] = 'C'
    a.output.mkdir(parents=True, exist_ok=False)
    rows = [check(a, 'redis', 'oracle', 16)]
    rows += [check(a, mode, engine, db) for mode in ('1s', '2s')
             for engine in ('uring', 'epoll') for db in (1, 16)]
    (a.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    return int(not all(r['passed'] for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
