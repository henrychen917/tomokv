"""NT4.6: exact INFO placement, silent closes, RESETSTAT, TCP/TLS, both engines/modes."""
from contextlib import closing
import time
import ssl
import _netfix as n

FIELD = b'client_query_buffer_limit_disconnections'


def counter(admin):
    body = admin.must('INFO', 'stats')
    lines = body.splitlines()
    keys = [line.split(b':', 1)[0] for line in lines]
    assert keys.count(FIELD) == 1, 'missing/duplicate ' + FIELD.decode()
    index = keys.index(FIELD)
    assert keys[index + 1] == b'client_output_buffer_limit_disconnections', keys[index:index+2]
    assert b'# Stats' in lines
    return int(lines[index].split(b':')[1])


def test(a, port, certs, proc, oracle):
    with closing(n.connect(port, certs)) as admin:
        assert admin.must('CONFIG', 'RESETSTAT') == b'OK'
        observed = [counter(admin)]
        assert observed == [0]
        admin.must('CONFIG', 'SET', 'client-query-buffer-limit', '1mb')
        for queued in (False, True, False):
            with closing(n.connect(port, certs)) as client:
                if queued:
                    assert client.must('MULTI') == b'OK'
                    assert client.must('ECHO', b'x' * (768 << 10)) == b'QUEUED'
                payload = (b'*2\r\n$4\r\nECHO\r\n$2097152\r\n' + b'x' * ((1 << 20) + 1))
                try:
                    client.raw(payload)
                except (BrokenPipeError, ConnectionResetError, ssl.SSLEOFError):
                    pass
                try:
                    assert client.file.read(1) == b'', 'limit must close without a reply'
                except (ConnectionResetError, ssl.SSLEOFError):
                    pass
            deadline = time.monotonic() + 3
            while counter(admin) != observed[-1] + 1 and time.monotonic() < deadline:
                time.sleep(.01)
            observed.append(counter(admin))
            assert observed[-1] == observed[-2] + 1, observed
        admin.must('CONFIG', 'RESETSTAT')
        observed.append(counter(admin))
        assert observed == [0, 1, 2, 3, 0], observed
        assert FIELD not in admin.must('INFO', 'clients')
        return observed


if __name__ == '__main__':
    n.matrix(n.arguments(), test)
