#!/usr/bin/env python3
"""Timestamp unchanged differ.py reads/sends; dump its actual generated commands.

Usage: trace_differ.py OUTPUT_PREFIX HOST PORT ORACLE_HOST ORACLE_PORT edgetime 7
The harness's generators, batching, comparisons and exit status are unchanged.
Read completion is a client timestamp, not a server execution timestamp. Buffered
reads and the harness's target-before-oracle drain order must be accounted for.
"""
import ast
import json
from pathlib import Path
import sys
import time

prefix = Path(sys.argv[1])
sys.argv = ['tests/differ.py', *sys.argv[2:]]
assert sys.argv[5:] == ['edgetime', '7'], sys.argv
sys.path.insert(0, 'tests')
source = Path('tests/differ.py')
tree = ast.parse(source.read_text(), filename=str(source))
cut = next(i for i, node in enumerate(tree.body)
           if isinstance(node, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == 'ops' for t in node.targets))
scope = dict(__name__='__main__', __file__=str(source))
events = []
depth = 0


def stamp():
    return time.monotonic_ns(), time.time_ns()


class Socket:
    def __init__(self, sock, side):
        self.sock, self.side = sock, side

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def sendall(self, payload):
        before = stamp()
        result = self.sock.sendall(payload)
        events.append(dict(kind='send', side=self.side, batch=scope.get('i'),
                           bytes=len(payload), before=before, after=stamp()))
        return result


exec(compile(ast.Module(body=tree.body[:cut], type_ignores=[]), str(source), 'exec'), scope)
original_read = scope['read_reply']
original_conn = scope['conn']
files = {}


def conn(host, port):
    sock, file = original_conn(host, port)
    side = 'target' if (host, port) == (scope['TH'], scope['TP']) else 'oracle'
    files[id(file)] = side
    return Socket(sock, side), file


def read_reply(file):
    global depth
    outer = depth == 0
    before = stamp() if outer else None
    depth += 1
    try:
        result = original_read(file)
    finally:
        depth -= 1
    if outer:
        op = scope['i'] + scope['j'] if 'j' in scope else None
        events.append(dict(kind='reply', side=files.get(id(file)), op=op,
                           before=before, after=stamp(), reply=result.hex()))
    return result


scope['conn'] = conn
scope['read_reply'] = read_reply
start = stamp()
try:
    exec(compile(ast.Module(body=tree.body[cut:], type_ignores=[]), str(source), 'exec'), scope)
finally:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix('.json').write_text(json.dumps(dict(
        start=start, end=stamp(), operations=scope.get('ops'), events=events,
        harness_sha256=__import__('hashlib').sha256(source.read_bytes()).hexdigest())) + '\n')
