#!/usr/bin/env python3
"""EX4.10: container outer bounds must preserve the child's lookup/error order."""
import argparse
from pathlib import Path

from compat2_support import Client, arguments, save, server


def run(a):
    a.output.mkdir(parents=True, exist_ok=False)
    rows = []
    with server(a.binary, a.output / 'target', a.port, a.cores, a.mode, a.engine), \
         server(a.oracle, a.output / 'oracle', a.port + 1, a.cores, oracle=True):
        with Client(a.port) as target, Client(a.port + 1) as oracle:
            for c in (target, oracle):
                assert c.cmd('XADD', 'stream', '1-0', 'f', 'v') == b'1-0'
                assert c.cmd('SET', 'string', 'v') == b'OK'
            for key in ('stream', 'string', 'missing'):
                for tail in (('FULL', 'COUNT', '1', 'extra'),
                             ('FULL', 'COUNT', '1', 'extra', 'more'),
                             ('full', 'count', '1', 'x', 'y', 'z')):
                    argv = ('XINFO', 'STREAM', key, *tail)
                    rows.append(dict(argv=argv, target=target.cmd(*argv), oracle=oracle.cmd(*argv)))
            # Fixed-arity children still reject before lookup; MEMORY's handler
            # grammar is checked before lookup, unlike XINFO STREAM's.
            controls = [('XINFO',), ('XINFO', 'HELP', 'x'),
                        ('XINFO', 'GROUPS', 'missing', 'x'),
                        ('XINFO', 'CONSUMERS', 'missing', 'g', 'x'),
                        ('XINFO', 'BOGUS', *(['x'] * 8))]
            controls += [('MEMORY', 'USAGE', key, 'SAMPLES', '1', 'x')
                         for key in ('stream', 'string', 'missing')]
            for argv in controls:
                rows.append(dict(argv=argv, target=target.cmd(*argv), oracle=oracle.cmd(*argv)))
    save(a.output / 'replies.json', rows)
    failures = [r for r in rows if r['target'] != r['oracle']]
    for row in failures:
        print(row)
    assert not failures, f'{len(failures)}/{len(rows)} outer-arity replies differ'
    print(f'EX4.10 PASS: {len(rows)} exact oracle replies')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    arguments(p)
    p.add_argument('--oracle', type=Path, required=True)
    run(p.parse_args())
