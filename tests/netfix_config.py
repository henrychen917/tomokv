"""NT4.8: compare complete network CONFIG SET error replies with the Redis oracle."""
from contextlib import closing
import json
import time
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
    yield ('protected-mode', '1')
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
        # A public limit above the uint32 frame representation must not make
        # malformed decimal headers wrap into short valid payloads.
        large = admin.cmd('CONFIG', 'SET', 'proto-max-bulk-len', '9223372036854775807')
        replies.append([['proto-max-bulk-len', '9223372036854775807'], str(large)
                        if isinstance(large, n._lib.RespError) else large.decode()])
        with closing(n.connect(port, certs)) as frame:
            frame.raw(b'*2\r\n$4\r\nECHO\r\n')
            time.sleep(.05)  # the bulk header arrives separately: resumed decoding
            frame.raw(b'$18446744073709551620\r\nabcd\r\n')
            result = frame.read()
            replies.append([['wrapped-bulk-header'], str(result)
                            if isinstance(result, n._lib.RespError) else result.decode()])
        with closing(n.connect(port, certs)) as frame:
            # One write: the complete-frame parser hands the oversized header to its tail.
            frame.raw(b'*2\r\n$4\r\nECHO\r\n$18446744073709551620\r\nabcd\r\n')
            result = frame.read()
            replies.append([['wrapped-bulk-header-complete'], str(result)
                            if isinstance(result, n._lib.RespError) else result.decode()])
        if not oracle:
            # Representation bound, not oracle parity: Redis would allocate a >4 GiB
            # string here. 32-bit string values must refuse it instead of narrowing a
            # length (PRE refused the limit itself; the unbounded growth checks aborted).
            for args, error in (
                    (('SETRANGE', 'netfix-wide', '4294967296', 'x'),
                     'ERR string exceeds maximum allowed size (proto-max-bulk-len)'),
                    (('SETBIT', 'netfix-wide', '34359738368', '1'),
                     'ERR bit offset is not an integer or out of range'),
                    (('BITFIELD', 'netfix-wide', 'SET', 'u8', '34359738368', '1'),
                     'ERR bit offset is not an integer or out of range')):
                result = admin.cmd(*args)
                assert isinstance(result, n._lib.RespError) and str(result) == error, (args, result)
            assert admin.cmd('EXISTS', 'netfix-wide') == 0
            assert admin.cmd('PING') == b'PONG'
    label = 'tls' if certs else 'tcp'
    path = a.output / ('oracle-' + label + '.json')
    if oracle:
        path.write_text(json.dumps(replies, indent=2))
    else:
        expected = json.loads(path.read_text())
        assert len(expected) == len(replies), (len(expected), len(replies))
        different = [(old, new) for old, new in zip(expected, replies) if old != new]
        assert not different, json.dumps(different, indent=2)
    return replies


if __name__ == '__main__':
    n.matrix(n.arguments(), test)
