#!/usr/bin/env python3
"""EX4.4: every advertised child dispatches; ACL DRYRUN has no command effects."""
import argparse
from pathlib import Path

from compat2_support import Client, arguments, save, server


class ProtocolClient(Client):
    def read(self):
        if self.f.peek(1)[:1] == b'%':
            line = self.f.readline()
            assert line.endswith(b'\r\n'), line
            return {self.read(): self.read() for _ in range(int(line[1:-2]))}
        return super().read()


def run(a):
    a.output.mkdir(parents=True, exist_ok=False)
    rows, children, failures = [], [], []
    with server(a.binary, a.output / 'target', a.port, a.cores, a.mode, a.engine), \
         server(a.oracle, a.output / 'oracle', a.port + 1, a.cores, oracle=True):
        with ProtocolClient(a.port) as target, ProtocolClient(a.port + 1) as oracle:
            for row in target.cmd('COMMAND'):
                for child in row[9]:
                    name, arity = child[0].decode(), child[1]
                    argv = name.split('|') + ['invalid'] * max(0, abs(arity) - 2)
                    replies = [c.cmd(*argv) for c in (target, oracle)]
                    record = dict(argv=argv, target=replies[0], oracle=replies[1])
                    children.append(record)
                    unknown = [isinstance(r, bytes) and r.startswith(b'-ERR ') and
                               b'unknown subcommand' in r.lower() for r in replies]
                    if unknown[0] and not unknown[1]:
                        failures.append(record)
            for c in (target, oracle):
                assert c.cmd('ACL', 'SETUSER', 'reader', 'reset', 'on', 'nopass',
                             '~allowed:*', '&allowed:*', '+get', '+set', '+subscribe',
                             '+psubscribe', '+publish') == b'OK'
                assert c.cmd('SET', 'allowed:key', 'before') == b'OK'
            probes = [
                ('ACL', 'DRYRUN'), ('ACL', 'DRYRUN', 'default'),
                ('ACL', 'DRYRUN', 'absent', 'GET', 'key'),
                ('ACL', 'DRYRUN', 'default', 'NOSUCHCOMMAND'),
                ('ACL', 'DRYRUN', 'default', 'CONFIG', 'NOSUCHSUB'),
                ('ACL', 'DRYRUN', 'default', 'GET'),
                ('ACL', 'DRYRUN', 'default', 'CONFIG', 'GET'),
                ('ACL', 'DRYRUN', 'default', 'GET', 'key'),
                ('ACL', 'DRYRUN', 'reader', 'GET', 'allowed:key'),
                ('ACL', 'DRYRUN', 'reader', 'GET', 'denied:key'),
                ('ACL', 'DRYRUN', 'reader', 'DEL', 'allowed:key'),
                ('ACL', 'DRYRUN', 'reader', 'SET', 'allowed:key', 'after'),
                ('ACL', 'DRYRUN', 'reader', 'SUBSCRIBE', 'allowed:a', 'denied:b'),
                ('ACL', 'DRYRUN', 'reader', 'PSUBSCRIBE', 'allowed:*'),
                ('ACL', 'DRYRUN', 'reader', 'PSUBSCRIBE', 'allowed:a'),
                ('ACL', 'DRYRUN', 'reader', 'PUBLISH', 'denied:a', 'payload'),
                ('GET', 'allowed:key'), ('LATENCY', 'HISTOGRAM', 'NOSUCHCOMMAND'),
                ('LATENCY', 'HISTOGRAM', 'NOSUCHCOMMAND', 'ANOTHER'),
            ]
            for argv in probes:
                row = dict(argv=argv, target=target.cmd(*argv), oracle=oracle.cmd(*argv))
                rows.append(row)
                if row['target'] != row['oracle']:
                    failures.append(row)
            assert target.cmd('GET', 'allowed:key') == oracle.cmd('GET', 'allowed:key') == b'before'
            # TomoKV currently has no command-histogram recorder. Compare its
            # empty state with Redis's explicit equivalent, in both protocols.
            setup = []
            for argv in [('CONFIG', 'SET', 'latency-tracking', 'no'), ('CONFIG', 'RESETSTAT')]:
                reply = oracle.cmd(*argv)
                setup.append(dict(argv=argv, oracle=reply))
                assert reply == b'OK', (argv, reply)
            save(a.output / 'histogram-oracle-setup.json', setup)
            for protocol in (2, 3):
                for c in (target, oracle):
                    hello = c.cmd('HELLO', protocol)
                    assert (hello[b'proto'] if protocol == 3 else dict(zip(hello[::2], hello[1::2]))[b'proto']) == protocol
                for argv in [('LATENCY', 'HISTOGRAM'), ('LATENCY', 'HISTOGRAM', 'GET'),
                             ('LATENCY', 'HISTOGRAM', 'ping', 'config|get', 'NOSUCHCOMMAND')]:
                    row = dict(protocol=protocol, argv=argv, target=target.cmd(*argv), oracle=oracle.cmd(*argv))
                    rows.append(row)
                    assert row['oracle'] == ([] if protocol == 2 else {}), row
                    if row['target'] != row['oracle']:
                        failures.append(row)
    save(a.output / 'children.json', children)
    save(a.output / 'replies.json', rows)
    assert len(children) >= 90, len(children)
    for row in failures:
        print(row)
    assert not failures, f'{len(failures)} advertised-child/DRYRUN failures'
    print(f'EX4.4 PASS: {len(children)} children; {len(rows)} exact oracle assertions')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    arguments(p)
    p.add_argument('--oracle', type=Path, required=True)
    run(p.parse_args())
