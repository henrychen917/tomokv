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
    rows = []
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
                     ('-get|allowed',), ('+@read|x',)]
            children = [child for row in target.cmd('COMMAND') for child in row[9]]
            cases += [(('+' + child[0].decode()),) for child in children]
            cases += [('+@all', '-' + child[0].decode()) for child in children]
            # Representative category/parent/child interleavings, including the
            # independently categorized read/write children of a container.
            for category in ('read', 'write', 'admin', 'slow', 'fast', 'dangerous', 'connection'):
                cases += [(f'+@{category}', '-config|get', '+config|get'),
                          ('+config', f'-@{category}'),
                          ('+@all', f'-@{category}')]
            probes = [('CONFIG', 'GET', 'no-such-config'), ('CONFIG', 'SET', 'timeout', '0'),
                      ('CONFIG', 'HELP'), ('GET', 'allowed'), ('GET', 'another'),
                      ('GET', 'denied'), ('SELECT', '0'), ('SELECT', '1'), ('CLIENT', 'ID'), ('XINFO', 'STREAM', 'missing')]
            for rules in cases:
                compare(('ACL', 'SETUSER', 'subject', 'reset', 'on', 'nopass', '~*', '&*', *rules))
                compare(('ACL', 'GETUSER', 'subject'))
                # Inspect effective permissions without running administrative mutations.
                for command in probes:
                    compare(('ACL', 'DRYRUN', 'subject', *command))
                # Every explicitly named advertised child must exercise its own
                # admission bit, including both the positive and negative rule.
                for child in children:
                    full = child[0].decode()
                    if any(rule[1:].lower() == full for rule in rules):
                        command = tuple(full.split('|')) + ('x',) * (abs(child[1]) - 2)
                        compare(('ACL', 'DRYRUN', 'subject', *command))
                # Persist and reload even rejected rules: Redis retains the old image.
                before = [c.cmd('ACL', 'GETUSER', 'subject') for c in clients]
                compare(('ACL', 'SAVE'))
                compare(('ACL', 'LOAD'))
                after = compare(('ACL', 'GETUSER', 'subject'))
                assert before == after, ('ACL round trip changed permissions', rules)
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
    save(a.output / 'replies.json', rows)
    failures = [r for r in rows if r['target'] != r['oracle']]
    for row in failures[:30]:
        print(row)
    assert not failures, f'{len(failures)}/{len(rows)} ACL oracle comparisons differ'
    print(f'CC4.15 PASS: {len(cases)} rule sequences and {len(rows)} exact replies, SAVE/LOAD per sequence')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    arguments(p)
    p.add_argument('--oracle', type=Path, required=True)
    run(p.parse_args())
