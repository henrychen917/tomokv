#!/usr/bin/env python3
"""C1: every registered Redis command, arity boundary, and authentication state.

Right-arity authenticated probes use a command-denied user, so even SHUTDOWN,
blocking commands and nondeterministic administrative replies are safe to compare
byte for byte. Wrong-arity probes use the fully authorized default user. Finite
local maxima also probe handler grammar (e.g. ten-argument PING). Variadic
commands with minimum one have no representable too-short RESP command; this is
recorded explicitly, with their valid boundary still tested in both auth states.
"""
import argparse
import re
from pathlib import Path

from compat2_support import Client, arguments, save, server
from cmdmeta_coverage import registered_commands

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'compat2-secret'


def run(a):
    a.output.mkdir(parents=True, exist_ok=False)
    rows, failures, unavailable = [], [], []
    with server(a.binary, a.output / 'target', a.port, a.cores, a.mode, a.engine), \
         server(a.oracle, a.output / 'oracle', a.port + 1, a.oracle_cores, oracle=True):
        ports = (a.port, a.port + 1)
        for port in ports:
            with Client(port) as c:
                assert c.cmd('ACL', 'SETUSER', 'compat2', 'on', '>' + PASSWORD,
                             '~*', '&*', '-@all', '+auth', '+hello', '+quit', '+reset') == b'OK'
                assert c.cmd('CONFIG', 'SET', 'requirepass', PASSWORD) == b'OK'
        with Client(a.port + 1) as c:
            assert c.cmd('AUTH', PASSWORD) == b'OK'
            metadata = {r[0].decode(): r for r in c.cmd('COMMAND')}
        bounds = {}
        for path in (ROOT / 'src/cmd').glob('*.cc'):
            for name, lo, hi in re.findall(r'\{"([A-Z0-9_-]+)",\s*(-?\d+),\s*(-?\d+),', path.read_text()):
                bounds[name.lower()] = (int(lo), int(hi))

        def compare(name, kind, argv, auth, denied=False):
            replies = []
            for port in ports:
                with Client(port) as c:
                    if auth:
                        credentials = ('compat2', PASSWORD) if denied else (PASSWORD,)
                        assert c.cmd('AUTH', *credentials) == b'OK'
                    replies.append(c.cmd(*argv))
            row = dict(command=name, kind=kind, argv=argv, authenticated=auth,
                       restricted_user=denied, target=replies[0], oracle=replies[1])
            rows.append(row)
            if replies[0] != replies[1]:
                failures.append(row)

        inventory = sorted(n.lower() for n in registered_commands())
        for name in inventory:
            if name not in metadata:
                # FLIP is TomoKV's explicit extension, not a Redis command.
                assert name == 'flip', ('missing oracle command', name)
                unavailable.append(dict(command=name, reason='local extension; no Redis oracle'))
                continue
            parent = metadata[name]
            entries = [parent, *parent[9]]
            for entry in entries:
                child = entry[0].decode()
                prefix = child.split('|')
                arity = entry[1]
                minimum = abs(arity)
                right = prefix + ['compat2-invalid'] * (minimum - len(prefix))
                if child == 'hello':
                    right = ['hello', 'compat2-invalid']  # stable protocol error, no client ID
                # AUTH/HELLO/QUIT/RESET are intentionally available before AUTH.
                for authenticated in (False, True):
                    compare(child, 'right', right, authenticated, denied=authenticated)
                wrong_counts = {minimum - 1} if minimum > len(prefix) else set()
                if arity > 0:
                    wrong_counts.add(arity + 1)
                if child == name:
                    lo, hi = bounds[name]
                    if lo > 1:
                        wrong_counts.add(lo - 1)
                    if hi >= 0:
                        wrong_counts.add(hi + 1)
                if child == 'ping':
                    wrong_counts.add(10)
                if not wrong_counts:
                    unavailable.append(dict(command=child, reason='variadic; no invalid advertised arity'))
                for count in sorted(wrong_counts):
                    assert len(prefix) <= count <= 10, (child, count)
                    wrong = prefix + ['compat2-invalid'] * (count - len(prefix))
                    for authenticated in (False, True):
                        # Local maxima of a variadic Redis command are handler grammar,
                        # beyond the advertised-arity matrix. Probe their AUTH ordering;
                        # PING is also checked with normal authenticated execution.
                        if authenticated and arity < 0 and count >= minimum and child != 'ping':
                            continue
                        compare(child, 'wrong', wrong, authenticated)
        for auth in (False, True):
            compare('unknown', 'unknown', ['COMPAT2-UNKNOWN', 'x'], auth)
        save(a.output / 'results.json', dict(inventory=inventory, rows=rows,
                                            unavailable=unavailable, failures=failures))
    print(f'autharity: commands={len(inventory)} comparisons={len(rows)} failures={len(failures)}')
    assert not failures, failures[:5]


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    arguments(p)
    p.add_argument('--oracle', type=Path, required=True)
    p.add_argument('--oracle-cores', required=True)
    run(p.parse_args())
