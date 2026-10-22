"""NT4.7: every locally enabled OpenSSL default suite accepted by Redis must work here."""
from contextlib import closing
import json
import os
import selectors
import ssl
import socket
import subprocess
import time
import _netfix as n


def probe(port, version, cipher, admin):
    # Gauge lifetime is asynchronous. Establish a zero baseline, not a fixed sleep,
    # so each observed offload belongs to this connection alone.
    deadline = time.monotonic() + 3
    while True:
        body = admin.must('INFO', 'stats')
        before = next((int(line.split(b':')[1]) for line in body.splitlines()
                       if line.startswith(b'tls_ktls_active:')), 0)
        if before == 0:
            break
        assert time.monotonic() < deadline, 'previous kTLS connection did not retire'
        time.sleep(.01)
    cmd = ['openssl', 's_client', '-quiet', '-connect', f'127.0.0.1:{port}',
           '-tls1_2' if version == 'TLSv1.2' else '-tls1_3',
           '-cipher' if version == 'TLSv1.2' else '-ciphersuites', cipher]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        p.stdin.write(b'*1\r\n$4\r\nPING\r\n')
        p.stdin.flush()
        with selectors.DefaultSelector() as sel:
            sel.register(p.stdout, selectors.EVENT_READ)
            ready = sel.select(5)
            assert ready, f'{cipher}: TLS request timed out'
            reply = os.read(p.stdout.fileno(), 4096)
        stats = admin.must('INFO', 'stats')
        ktls = next((int(line.split(b':')[1]) for line in stats.splitlines()
                     if line.startswith(b'tls_ktls_active:')), None)
        return reply == b'+PONG\r\n', ktls
    finally:
        p.terminate()
        try:
            p.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()


def test(a, port, certs, proc, oracle):
    suites = []
    for version, flag in (('TLSv1.2', '-tls1_2'), ('TLSv1.3', '-tls1_3')):
        names = subprocess.check_output(['openssl', 'ciphers', '-s', flag, 'DEFAULT'], text=True)
        suites.extend((version, name) for name in names.strip().split(':'))
    results = {}
    with closing(n.connect(a.port)) as admin:
        for version, cipher in suites:
            # A cipher handshake can be accepted by one TLS version only. The oracle with
            # this exact certificate determines which default suites are actually usable.
            results[version + '/' + cipher] = probe(port, version, cipher, admin)
            time.sleep(.03)  # let the old connection leave the live kTLS gauge
    (a.output / f'suites-{proc.pid}.json').write_text(json.dumps(results, indent=2))
    # Redis enables session caching by default. Check an actual resumed handshake.
    ctx = ssl.create_default_context(cafile=str(certs / 'ca.crt'))
    ctx.check_hostname = False
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers('ECDHE-RSA-AES128-GCM-SHA256')
    session = None
    for attempt in range(2):
        with socket.create_connection(('127.0.0.1', port), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname='localhost', session=session) as sock:
                sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                assert sock.recv(64) == b'+PONG\r\n'
                if attempt:
                    assert sock.session_reused, 'Redis default TLS session did not resume'
                session = sock.session
    reference = a.output / 'oracle-suites.json' 
    if oracle:
        reference.write_text(json.dumps(results, indent=2))
        assert sum(row[0] for row in results.values()) >= 8, results
    else:
        expected = json.loads(reference.read_text())
        missing = [name for name, row in expected.items() if row[0] and not results[name][0]]
        assert not missing, missing
        assert results['TLSv1.2/ECDHE-RSA-AES128-GCM-SHA256'] == (True, 1), results
        assert results['TLSv1.2/ECDHE-RSA-AES256-GCM-SHA384'] == (True, 1), results
    return results


if __name__ == '__main__':
    a = n.arguments()
    certs = n.certificates(a)
    results, failed = {}, []
    for oracle, mode, engine in [(True, 'oracle', 'oracle')] + [
            (False, m, e) for m in ('1s', '2s') for e in ('epoll', 'uring')]:
        label = f'{mode}-{engine}'
        try:
            with n.server(a, label, oracle=oracle, mode=mode, engine=engine, certs=certs) as proc:
                results[label] = test(a, a.port + 1, certs, proc, oracle)
            print('PASS', label, results[label], flush=True)
        except Exception as exc:
            failed.append(label)
            results[label] = repr(exc)
            print('FAIL', label, repr(exc), flush=True)
    (a.output / 'results.json').write_text(json.dumps(results, indent=2))
    assert not failed, failed
