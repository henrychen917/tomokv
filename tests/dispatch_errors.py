#!/usr/bin/env python3
"""EX4.11: every advertised container/child's arity errors against Redis 7.4."""
import argparse
from pathlib import Path

from compat2_support import Client, arguments, save, server


def error_wire(port, argv):
    # A fresh connection and a PING delimiter retain even a malformed error's
    # embedded CR/LF without letting it corrupt the next table entry. No idle
    # timeout or missing frame can count as a matching reply.
    with Client(port) as client:
        client.send(*argv)
        client.send('PING')
        lines = []
        for _ in range(8):
            line = client.f.readline()
            assert line, ('connection closed before PING', argv, lines)
            if line == b'+PONG\r\n':
                return b''.join(lines)
            lines.append(line)
        raise AssertionError(('missing PING delimiter', argv, lines))


def run(a):
    a.output.mkdir(parents=True, exist_ok=False)
    rows, inventory = [], {}
    # Use the third reserved gate port so both listeners can avoid even
    # ephemeral source ports used by concurrent lanes. The gate reserves three.
    with server(a.binary, a.output / 'target', a.port, a.cores, a.mode, a.engine), \
         server(a.oracle, a.output / 'oracle', a.port + 2, a.cores, oracle=True):
        with Client(a.port) as target, Client(a.port + 2) as oracle:
            for c in (target, oracle):
                assert c.cmd('XADD', 'stream', '1-0', 'f', 'v') == b'1-0'
                assert c.cmd('SET', 'string', 'v') == b'OK'
            reference = {r[0]: r for r in oracle.cmd('COMMAND')}
            probes, boundaries = [], []
            for row in sorted(target.cmd('COMMAND')):
                if not row[9]:
                    continue
                parent = row[0].decode().upper()
                assert row[0] in reference, ('unrecognized container', parent)
                inventory[parent] = []
                if abs(row[1]) > 1:
                    probes.append((parent,))
                probes += [(parent, 'NOSUCHSUB'),
                           (parent, 'nosuchsub', *(['x'] * 16))]
                boundaries += [(parent, b'x' * length) for length in (127, 128, 129, 300)]
                boundaries += [(parent, b'bad\0tail'), (parent, b'bad\r\nline')]
                for child in row[9]:
                    name, arity = child[0].decode(), child[1]
                    oracle_child = next(r for r in reference[row[0]][9] if r[0] == child[0])
                    assert arity == oracle_child[1], (name, arity, oracle_child[1])
                    inventory[parent].append((name, arity))
                    sub = name.split('|')[1].upper()
                    minimum = abs(arity)
                    if minimum > 2:
                        probes.append((parent, sub, *(['x'] * (minimum - 3))))
                    if arity > 0:
                        for extra in (1, 8):
                            probes.append((parent, sub, *(['x'] * (minimum + extra - 2))))
            # Variadic metadata delegates these bounds/grammars to the handler.
            probes += [('COMMAND', s) for s in ('GETKEYS', 'GETKEYSANDFLAGS')]
            probes += [('ACL', s, 'x', 'x') for s in ('CAT', 'GENPASS', 'LOG')]
            probes += [('SLOWLOG', 'GET', '1', 'x'), ('ACL', 'HELP')]
            for key in ('stream', 'string', 'missing'):
                probes += [('XINFO', 'STREAM', key, *tail) for tail in
                           [('x',), ('FULL', 'x'), ('FULL', 'x', '1'),
                            ('FULL', 'COUNT', 'x'), ('FULL', 'COUNT', '01'),
                            ('FULL', 'COUNT', '1', 'x')]]
                probes += [('XGROUP', 'CREATE', key, 'g', '0', 'extra'),
                           ('XGROUP', 'SETID', key, 'g', '0', 'extra'),
                           ('XGROUP', 'CREATE', key, 'g', 'bad-id', 'extra'),
                           ('XGROUP', 'CREATE', key, 'g', '0', 'ENTRIESREAD', '01'),
                           ('XGROUP', 'CREATE', key, 'g', '0', 'ENTRIESREAD', '-2')]
            probes += [('XGROUP', s, 'missing', 'g', *tail) for s, tail in
                       [('DESTROY', ()), ('SETID', ('0',)),
                        ('CREATECONSUMER', ('c',)), ('DELCONSUMER', ('c',))]]
            probes += [('OBJECT', 'FREQ', 'missing')]
            for argv in probes:
                rows.append(dict(argv=argv, target=target.cmd(*argv), oracle=oracle.cmd(*argv)))
            for argv in boundaries:
                rows.append(dict(argv=argv, target=error_wire(a.port, argv),
                                 oracle=error_wire(a.port + 2, argv)))
            for c in (target, oracle):
                assert c.cmd('CONFIG', 'SET', 'maxmemory-policy', 'allkeys-lfu') == b'OK'
            for key in ('missing', 'string'):
                argv = ('OBJECT', 'IDLETIME', key)
                rows.append(dict(argv=argv, target=target.cmd(*argv), oracle=oracle.cmd(*argv)))
    save(a.output / 'inventory.json', inventory)
    save(a.output / 'replies.json', rows)
    failures = [r for r in rows if r['target'] != r['oracle']]
    for row in failures:
        print(row)
    assert len(inventory) >= 10 and sum(map(len, inventory.values())) >= 90, inventory
    assert not failures, f'{len(failures)}/{len(rows)} container replies differ'
    print(f'EX4.11 PASS: {len(rows)} exact replies; {len(inventory)} containers')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    arguments(p)
    p.add_argument('--oracle', type=Path, required=True)
    run(p.parse_args())
