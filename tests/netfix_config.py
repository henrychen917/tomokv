"""NT4.8: compare complete network CONFIG SET error replies with the Redis oracle."""
from contextlib import closing
import json
import _netfix as n


def cases():
    for name in ('tcp-backlog', 'unixsocket', 'unixsocketperm'):
        for spelling in (name, name.upper()):
            yield (spelling, 'bad')
    for name in ('maxclients', 'timeout', 'tcp-keepalive', 'proto-max-bulk-len',
                 'client-query-buffer-limit', 'protected-mode'):
        for value in ('bad', '-1', '0', '01', '+1', ' 1', '1 ', '1kb',
                      '9223372036854775808', '18446744073709551615'):
            # Only invalid values: setting timeout/maxclients/protected mode successfully
            # would affect the test connection. Zero is legal for timeout and keepalive.
            if value == '0' and name in ('timeout', 'tcp-keepalive'):
                continue
            yield (name, value)
        yield (name.upper(), 'bad')
    yield ('proto-max-bulk-len', '5gb')
    for value in ('normal', 'bad 0 0 0', 'normal x 0 0', 'normal -1 0 0',
                  'normal 0 0 -1', 'normal 0 0 bad', 'normal 0 0 1kb',
                  'normal 0 0', 'master 0 0 0', 'unknown 0 0 0',
                  'normal 0 0 1x', 'normal 184467440737095516160wat 0 0',
                  'normal 0 0 0 pubsub nope 0 0'):
        yield ('client-output-buffer-limit', value)
    for name, value in (('timeout', '0'), ('tcp-keepalive', '0'), ('maxclients', '20032'),
                        ('proto-max-bulk-len', '512mb'), ('client-query-buffer-limit', '1gb'),
                        ('protected-mode', 'no'), ('client-output-buffer-limit', 'normal 0 0 0')):
        yield (name, value, name.upper(), value)


def test(a, port, certs, proc, oracle):
    replies = []
    with closing(n.connect(port, certs)) as admin:
        for args in cases():
            result = admin.cmd('CONFIG', 'SET', *args)
            # Preserve exactly the error payload, not its repr wrapper.
            replies.append([list(args), str(result) if isinstance(result, n._lib.RespError)
                            else result.decode()])
    label = 'tls' if certs else 'tcp'
    path = a.output / ('oracle-' + label + '.json')
    if oracle:
        path.write_text(json.dumps(replies, indent=2))
    else:
        expected = json.loads(path.read_text())
        different = [(old, new) for old, new in zip(expected, replies) if old != new]
        assert not different, json.dumps(different, indent=2)
    return replies


if __name__ == '__main__':
    n.matrix(n.arguments(), test)
