#!/usr/bin/env python3
"""C3 live control: TLS1.2 kTLS closes, TLS1.3 stays on OpenSSL, gauges follow sockets."""
import argparse
from pathlib import Path

from compat2_support import Client, arguments, save, server, stats, wait_for
import tls


def run(a):
    a.output.mkdir(parents=True, exist_ok=False)
    certs = a.certs.resolve()
    extra = ['--tls-port', str(a.port + 1), '--tls-cert-file', str(certs / 'server.crt'),
             '--tls-key-file', str(certs / 'server.key'), '--tls-ca-cert-file',
             str(certs / 'ca.crt'), '--tls-auth-clients', 'no']
    rows = []
    with server(a.binary, a.output / 'server', a.port, a.cores, a.mode, a.engine, extra), \
            Client(a.port) as admin:
        for protocol in ('tls12', 'tls13'):
            probe = tls.Conn('127.0.0.1', a.port + 1, tls.context(str(certs), **{protocol: True}))
            assert probe.command('PING') == b'PONG'
            live = stats(admin)
            assert live['tls_current_connections'] == 1
            assert live['tls_ktls_active'] == (protocol == 'tls12'), live
            if protocol == 'tls13':
                assert live['tls_ktls_fallback'] >= 1 and live['tls_ktls_rx_declined_13'] >= 1
            probe.close(graceful=True)
            # The exact no-reap window is tested by ktls_lifetime_unit. This
            # live control requires real graceful shutdown and eventual teardown.
            closed = wait_for(lambda: (s if (s := stats(admin))['tls_current_connections'] == 0
                                       else None), 'graceful TLS close did not release its connection')
            assert closed['tls_ktls_active'] == 0
            rows.append(dict(protocol=protocol, live=live, closed=closed))
        save(a.output / 'results.json', rows)
    print('PASS TLS1.2 kTLS / TLS1.3 fallback socket lifecycle')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    arguments(p)
    p.add_argument('--certs', type=Path, required=True)
    run(p.parse_args())
