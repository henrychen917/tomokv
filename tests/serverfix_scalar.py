#!/usr/bin/env python3
"""CG4.4 shared config scalar grammar, at boot and through CONFIG SET."""
from _serverfix import main, Server, is_error


CASES = [
    ('maxmemory', '', b'0'), ('maxmemory', 'KB', b'0'),
    ('maxmemory', '00020', b'20'), ('maxmemory', '+20', None),
    ('maxclients', '00020', None), ('maxclients', '20', b'20'),
    ('tcp-keepalive', '01', None), ('tcp-keepalive', '0', b'0'),
    ('slowlog-max-len', '01', None), ('acllog-max-len', '+1', None),
    ('slowlog-log-slower-than', '-0', None),
    ('slowlog-log-slower-than', '-1', b'-1'),
    ('protected-mode', '1', None), ('protected-mode', 'YeS', b'yes'),
    ('aof-timestamp-enabled', '1', None), ('aof-timestamp-enabled', 'YeS', b'yes'),
    ('auto-aof-rewrite-percentage', '01', None),
    ('auto-aof-rewrite-min-size', 'mb', b'0'),
    ('hash-max-listpack-entries', '01', None),
    ('hash-max-listpack-value', 'kb', b'0'),
    ('stream-node-max-entries', '01', None),
    ('stream-node-max-bytes', 'mb', b'0'),
    ('latency-monitor-threshold', '01', None),
    ('maxmemory-policy', 'ALLKEYS-LRU', b'allkeys-lru'),
    ('appendfsync', 'EVERYSEC', b'everysec'),
    ('maxmemory', '0\0ignored', b'0'),
    ('timeout', '0\0ignored', None),
    ('slowlog-log-slower-than', '-1\0ignored', None),
    ('hash-max-listpack-entries', '2\0ignored', None),
    ('hash-max-listpack-entries', '1\0x', None),
    ('hash-max-listpack-value', '1\0x', b'1'),
    ('latency-monitor-threshold', '0\0ignored', None),
    ('dynamic-hz', 'no\0ignored', b'no'),
    ('appendfsync', 'no\0ignored', b'no'),
    ('maxmemory-policy', 'noeviction\0ignored', b'noeviction'),
]


def probe(run, mode, label, extra):
    with Server(run, label + '-live', mode, extra=extra) as server, server.client() as c:
        for name, value, expected in CASES:
            old = c.cmd('CONFIG', 'GET', name)
            reply = c.cmd('CONFIG', 'SET', name, value)
            key = f'{name}:{value!r}'
            run.rows[key] = reply
            if not run.oracle:
                run.check(f'{label} exact oracle reply {key}', reply, run.reference[key])
            run.check(f'{label} live {name} {value!r}', reply,
                      (lambda r: is_error(r, 'ERR')) if expected is None else b'OK')
            run.check(f'{label} retained/normalized {name} {value!r}', c.cmd('CONFIG', 'GET', name),
                      old if expected is None else [name.encode(), expected])
            run.check(label + ' restore ' + name, c.cmd('CONFIG', 'SET', name, old[1]), b'OK')
    for i, (name, value, expected) in enumerate(CASES):
        case = f'{label}-file-{i}'
        quoted = value.replace('\\', '\\\\').replace('"', '\\"').replace('\0', '\\x00')
        conf = run.conf(case, name + ' "' + quoted + '"\n')
        with Server(run, case, mode, conf, extra, refusal=True) as server:
            run.check(case + ' ' + name + ' startup', server.booted, expected is not None)
            if server.booted and name != 'protected-mode':  # lifecycle helper supplies no on CLI
                with server.client() as c:
                    run.check(case + ' normalized bytes', c.cmd('CONFIG', 'GET', name),
                              [name.encode(), expected])


if __name__ == '__main__':
    raise SystemExit(main(probe))
