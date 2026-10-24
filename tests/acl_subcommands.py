#!/usr/bin/env python3
"""CC4.15: subcommand/first-argument ACL rules, effective grants and file replay."""
import argparse
from pathlib import Path

from compat2_support import Client, arguments, save, server


def run(a):
    a.output.mkdir(parents=True, exist_ok=False)
    files = [a.output.resolve() / f'{kind}.acl' for kind in ('target', 'oracle')]
    for path in files:
        path.write_text('user default on nopass ~* &* +@all\n')
    rows, roundtrip_failures = [], []
    with server(a.binary, a.output / 'target', a.port, a.cores, a.mode, a.engine,
                extra=('--aclfile', str(files[0]))), \
         server(a.oracle, a.output / 'oracle', a.port + 1, a.cores,
                extra=('--aclfile', str(files[1])), oracle=True):
        with Client(a.port) as target, Client(a.port + 1) as oracle:
            clients = (target, oracle)

            def compare(argv):
                answers = [c.cmd(*argv) for c in clients]
                rows.append(dict(argv=argv, target=answers[0], oracle=answers[1]))
                return answers

            # Exact historical acl.py assertion, retained beside its oracle reply.
            compare(('ACL', 'SETUSER', 'bad-firstarg', '+select|0'))
            compare(('ACL', 'GETUSER', 'bad-firstarg'))
            compare(('ACL', 'DELUSER', 'bad-firstarg'))
            cases = [('+select|0',), ('+config|get',), ('+config', '-config|set'),
                     ('+@all', '-config|get'), ('+config|get', '+config'),
                     ('+config|get', '-config'), ('+config', '-config', '+config|get'),
                     ('+CONFIG|GET', '+config|get'),
                     ('+@admin', '-config|get'), ('+config|get', '-@admin'),
                     ('+@all', '-@admin', '+config|get'),
                     ('+get|allowed',), ('+get|allowed', '+get|another'),
                     ('+get|allowed', '+get|another', '+get|allowed'),
                     ('+get|allowed', '+get'), ('+get', '+get|allowed', '-get'),
                     ('+get|allowed', '-@read'), ('+@all', '-get', '+get|allowed'),
                     ('+config|missing',), ('-config|missing',),
                     ('+config|get|x',), ('-config|get|x',),
                     ('+config|',), ('+get|',), ('+missing|arg',),
                     ('-get|allowed',), ('+@read|x',),
                     ('+GET|ALLOWED',), ('+get|allowed', '+get|ALLOWED'),
                     ('+get|allowed\0ignored',), ('+config|get\0ignored',),
                     ('+@all', '-config|get\0ignored'),
                     ('+config|get\0|x',), ('+missing\0|get',)]
            commands = target.cmd('COMMAND')
            children = [child for row in commands for child in row[9]]
            reference_names = {row[0] for row in oracle.cmd('COMMAND')}
            # FLIP is TomoKV-specific: it has no Redis command-permission oracle.
            assert {row[0] for row in commands if row[0] not in reference_names} == {b'flip'}
            leaves = [row for row in commands if not row[9] and row[0] in reference_names] + children
            cases += [(('+' + child[0].decode()),) for child in children]
            cases += [('+@all', '-' + child[0].decode()) for child in children]
            # Representative category/parent/child interleavings, including the
            # independently categorized read/write children of a container.
            for category in ('read', 'write', 'admin', 'slow', 'fast', 'dangerous', 'connection'):
                cases += [(f'+@{category}', '-config|get', '+config|get'),
                          ('+config', f'-@{category}'),
                          ('+@all', f'-@{category}')]
            for category in target.cmd('ACL', 'CAT'):
                cases += [(f'+@{category.decode()}',), ('+@all', f'-@{category.decode()}')]
            probes = [('CONFIG', 'GET', 'no-such-config'), ('CONFIG', 'SET', 'timeout', '0'),
                      ('CONFIG', 'HELP'), ('GET', 'allowed'), ('GET', 'another'),
                      ('GET', 'denied'), ('GET', b'allowed\0tail'),
                      ('GET', b'ALLOWED\0tail'), ('SELECT', '0'), ('SELECT', '1'), ('CLIENT', 'ID'), ('XINFO', 'STREAM', 'missing')]
            for rules in cases:
                compare(('ACL', 'SETUSER', 'subject', 'reset', 'on', 'nopass', '~*', '&*', *rules))
                compare(('ACL', 'GETUSER', 'subject'))
                # Inspect effective permissions without running administrative mutations.
                for command in probes:
                    compare(('ACL', 'DRYRUN', 'subject', *command))
                # Explicit grants/revocations exercise their own admission bit;
                # every category rule checks all shared leaf commands and children.
                for child in leaves:
                    full = child[0].decode()
                    if any(rule[1:].lower() == full or rule[1:2] == '@' for rule in rules):
                        prefix = tuple(full.split('|'))
                        command = prefix + ('x',) * (abs(child[1]) - len(prefix))
                        compare(('ACL', 'DRYRUN', 'subject', *command))
                # Persist and reload even rejected rules: Redis retains the old image.
                before = [c.cmd('ACL', 'GETUSER', 'subject') for c in clients]
                compare(('ACL', 'SAVE'))
                compare(('ACL', 'LOAD'))
                after = compare(('ACL', 'GETUSER', 'subject'))
                if before != after:
                    roundtrip_failures.append(dict(rules=rules, before=before, after=after))
                lists = [next((line for line in c.cmd('ACL', 'LIST')
                               if line.startswith(b'user subject ')), None) for c in clients]
                rows.append(dict(argv=('ACL LIST subject', *rules), target=lists[0], oracle=lists[1]))
            # Real connection admission and revocation, not just DRYRUN's parser.
            compare(('ACL', 'SETUSER', 'subject', 'reset', 'on', 'nopass', '~*', '+config|get'))
            with Client(a.port) as user, Client(a.port + 1) as reference:
                command = ('AUTH', 'subject', 'ignored')
                rows.append(dict(argv=command, target=user.cmd(*command), oracle=reference.cmd(*command)))
                for command in probes[:3]:
                    rows.append(dict(argv=command, target=user.cmd(*command), oracle=reference.cmd(*command)))
                compare(('ACL', 'SETUSER', 'subject', '-config|get'))
                command = ('CONFIG', 'GET', 'no-such-config')
                rows.append(dict(argv=command, target=user.cmd(*command), oracle=reference.cmd(*command)))
                compare(('ACL', 'SETUSER', 'subject', 'reset', 'on', 'nopass', '~*', '+get|allowed'))
                compare(('SET', b'allowed\0tail', 'binary-key'))
                for command in [('GET', b'allowed\0tail'), ('GET', b'ALLOWED\0tail'),
                                ('GET', b'allowedX\0tail')]:
                    rows.append(dict(argv=command, target=user.cmd(*command), oracle=reference.cmd(*command)))
    save(a.output / 'replies.json', rows)
    save(a.output / 'roundtrip-failures.json', roundtrip_failures)
    failures = [r for r in rows if r['target'] != r['oracle']]
    for row in failures[:30]:
        print(row)
    assert not roundtrip_failures, ('ACL round trip changed permissions', roundtrip_failures)
    assert not failures, f'{len(failures)}/{len(rows)} ACL oracle comparisons differ'
    print(f'CC4.15 PASS: {len(cases)} rule sequences and {len(rows)} exact replies, SAVE/LOAD per sequence')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    arguments(p)
    p.add_argument('--oracle', type=Path, required=True)
    run(p.parse_args())
