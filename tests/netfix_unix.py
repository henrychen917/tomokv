"""NT4.11: Redis replaces regular files, stale/live sockets and symlinks at unixsocket."""
from contextlib import closing
import json
from pathlib import Path
import socket
import tempfile
import traceback
import _netfix as n


def main():
    a = n.arguments()
    results, failures = {}, []
    for oracle, mode, engine in [(True, 'oracle', 'oracle')] + [
            (False, m, e) for m in ('1s', '2s') for e in ('epoll', 'uring')]:
        for kind in ('regular', 'stale', 'live', 'symlink'):
            label = f'{mode}-{engine}-{kind}'
            original = None
            try:
                with tempfile.TemporaryDirectory(prefix='nf-', dir='build') as directory:
                    path = Path(directory).resolve() / 'server.sock'
                    target = path.with_name('target')
                    if kind == 'regular':
                        path.write_bytes(b'pre-existing file')
                    elif kind == 'symlink':
                        target.write_bytes(b'unchanged target')
                        path.symlink_to(target)
                    else:
                        original = socket.socket(socket.AF_UNIX)
                        original.bind(str(path))
                        if kind == 'live':
                            original.listen(16)
                        else:
                            original.close()
                    with n.server(a, label, oracle=oracle, mode=mode, engine=engine,
                                  extra=['--unixsocket', str(path), '--unixsocketperm', '700']):
                        with closing(n.connect(a.port, unix=path)) as c:
                            assert c.must('PING') == b'PONG'
                            assert c.must('ECHO', label) == label.encode()
                        assert path.stat().st_mode & 0o777 == 0o700
                        if kind == 'symlink':
                            assert target.read_bytes() == b'unchanged target'
                    assert not path.exists(), 'normal exit must remove owned pathname'
                results[label] = 'replaced, served, cleaned'
                print('PASS', label, flush=True)
            except Exception:
                failures.append(label)
                results[label] = traceback.format_exc()
                print('FAIL', label, results[label], flush=True)
            finally:
                if original:
                    original.close()
    (a.output / 'results.json').write_text(json.dumps(results, indent=2))
    assert not failures, failures


if __name__ == '__main__':
    main()
