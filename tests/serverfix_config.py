#!/usr/bin/env python3
"""SV4.6: inventory-driven CONFIG type, duplicate and transaction validation."""
import re
from pathlib import Path
from _serverfix import main, Server, is_error


def inventory():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'src/cmd/t_server.cc').read_text().split('void init_config(')[1].split('ConfigValue* find_config')[0]
    table = dict(re.findall(r'(?:add_config\(|g_config\.push_back\(\{)"([^"]+)", ConfigKind::(\w+)', source))
    enc = (root / 'src/core/config.h').read_text().split('settings[Count] = {')[1].split('};')[0]
    for name in re.findall(r'"([^"]+)"', enc):
        table[name] = 'Encoding'
    return table


# Deliberate existing lifetime/representation differences, exercised and recorded.
IMMUTABLE = set('hll-sparse-max-bytes port bind unixsocket unixsocketperm dir dbfilename appendonly '
                'net-io thread-mode read-local reorder wb-policy wb-small-pipe wb-complete-visits '
                'key-lb key-lb-damping client-lb flip-auto appendfilename appenddirname tls-port '
                'tls-cert-file tls-key-file tls-ca-cert-file tls-ca-cert-dir tls-auth-clients '
                'tls-protocols tls-ciphers tls-ciphersuites tls-prefer-server-ciphers '
                'tracking-table-max-keys databases aclfile enable-debug-command tcp-backlog'.split())

# These controls are boot-only in TomoKV but mutable in Redis. All other
# oracle-backed immutable/protected replies must match exactly, too.
LIFETIME_DIFFERENCES = set('appendonly bind hll-sparse-max-bytes port tls-auth-clients '
                           'tls-ca-cert-dir tls-ca-cert-file tls-cert-file tls-ciphers '
                           'tls-ciphersuites tls-key-file tls-port tls-prefer-server-ciphers '
                           'tls-protocols tracking-table-max-keys'.split())


def probe(run, mode, label, extra):
    table = inventory()
    with Server(run, label, mode, extra=extra) as server, server.client() as c:
        if not run.oracle:
            values = c.cmd('CONFIG', 'GET', '*')
            run.check(label + ' every parameter has a type row', sorted(v.decode() for v in values[::2]), sorted(table))
        for name, kind in sorted(table.items()):
            old = c.cmd('CONFIG', 'GET', name)
            if not old:
                run.check(label + ' oracle-only absence ' + name, run.oracle, True)
                continue
            value = old[1]
            bad = 'not-a-value'
            # A distinct valid update makes partial application observable. A
            # current-value-only transaction would pass even if applied early.
            witness = 'acllog-max-len' if name == 'slowlog-max-len' else 'slowlog-max-len'
            witness_old = c.cmd('CONFIG', 'GET', witness)
            witness_new = str(int(witness_old[1]) + 1)
            # Strings accept arbitrary bytes; use the second parameter to force a
            # failure without installing a password, path or notification policy.
            cases = [('valid', ('CONFIG', 'SET', name, value)),
                     ('invalid', ('CONFIG', 'SET', name, bad) if kind != 'String' else
                      ('CONFIG', 'SET', name, value, 'timeout', bad)),
                     ('invalid-uppercase', ('CONFIG', 'SET', name.upper(), bad) if kind != 'String' else
                      ('CONFIG', 'SET', name.upper(), value, 'TIMEOUT', bad)),
                     ('duplicate', ('CONFIG', 'SET', name, value, name.upper(), value)),
                     ('atomic-tail', ('CONFIG', 'SET', witness, witness_new, name, value, 'timeout', bad)),
                     ('atomic-head', ('CONFIG', 'SET', 'timeout', bad, witness, witness_new, name, value))]
            for case, command in cases:
                key = name + ':' + case
                result = c.cmd(*command)
                run.rows[key] = result
                if run.oracle:
                    run.check(label + ' oracle transaction retained ' + key,
                              c.cmd('CONFIG', 'GET', witness), witness_old)
                    continue
                expected = run.reference.get(key)
                if name in IMMUTABLE and (expected is None or name in LIFETIME_DIFFERENCES):
                    run.check(label + ' immutable ' + key, result, lambda r: is_error(r, 'ERR'))
                elif expected is not None:
                    run.check(label + ' oracle ' + key, result, expected)
                else:  # Tomo-only spellings retain their own type, but reject duplicates too.
                    run.check(label + ' native ' + key, result,
                              b'OK' if case == 'valid' else lambda r: is_error(r, 'ERR'))
                run.check(label + ' atomic retained ' + key, c.cmd('CONFIG', 'GET', name), old)
                run.check(label + ' transaction witness retained ' + key,
                          c.cmd('CONFIG', 'GET', witness), witness_old)
        # Each generic scalar family must reject noncanonical forms atomically.
        for name, bad in [('timeout', '01'), ('protected-mode', '0'),
                          ('aof-timestamp-enabled', '1'), ('tcp-keepalive', '01')]:
            before = c.cmd('CONFIG', 'GET', name, 'slowlog-max-len')
            reply = c.cmd('CONFIG', 'SET', 'slowlog-max-len', '17', name, bad)
            key = name + ':multi-invalid'
            run.rows[key] = reply
            if not run.oracle:
                run.check(label + ' ' + key, reply, run.reference[key])
                run.check(label + ' all values retained ' + name,
                          c.cmd('CONFIG', 'GET', name, 'slowlog-max-len'), before)


        # Exact oracle witnesses for notify.py's legacy invalid-flag assertions.
        notify_before = c.cmd('CONFIG', 'GET', 'notify-keyspace-events')
        run.check(label + ' notify error setup', c.cmd('CONFIG', 'SET', 'notify-keyspace-events', 'gKE'), b'OK')
        for bad in ('Qz', 'o', 'c', 'a', 'S', 'T', 'I', 'V', 'r'):
            key = 'notify-invalid-flag:' + bad
            reply = c.cmd('CONFIG', 'SET', 'notify-keyspace-events', bad)
            run.rows[key] = reply
            expected = {'error': "ERR CONFIG SET failed (possibly related to argument 'notify-keyspace-events') - Invalid event class character. Use 'Ag$lshzxeKEtmdn'."}
            run.check(label + ' exact ' + key, reply, expected if run.oracle else run.reference[key])
            run.check(label + ' retained ' + key, c.cmd('CONFIG', 'GET', 'notify-keyspace-events'),
                      [b'notify-keyspace-events', b'gKE'])
        run.check(label + ' notify error restore',
                  c.cmd('CONFIG', 'SET', 'notify-keyspace-events', notify_before[1]), b'OK')


if __name__ == '__main__':
    raise SystemExit(main(probe))
