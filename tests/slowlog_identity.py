#!/usr/bin/env python3
"""SV4.3: immutable six-column SLOWLOG entries across rename and disconnect."""
import sys
import time
from _lib import Conn


def main():
    host, port = sys.argv[1], int(sys.argv[2])
    admin, client = Conn(host, port), Conn(host, port)
    try:
        admin.must('CONFIG', 'SET', 'slowlog-log-slower-than', 0)
        admin.must('CONFIG', 'SET', 'slowlog-max-len', 128)
        client.must('CLIENT', 'SETNAME', 'bugs5-before')
        peer = '%s:%d' % client.sock.getsockname()
        client.must('SET', 'bugs5:slowlog:marker', 'value')

        def entry():
            for _ in range(100):
                entries = admin.must('SLOWLOG', 'GET', -1)
                matches = [e for e in entries if e[3] == [b'SET', b'bugs5:slowlog:marker', b'value']]
                if matches:
                    assert len(matches) == 1, matches
                    return matches[0]
                time.sleep(.01)
            raise AssertionError('marker never logged')

        before = entry()
        assert len(before) == 6 and all(isinstance(x, int) for x in before[:3]), before
        assert before[4:] == [peer.encode(), b'bugs5-before'], before
        client.must('CLIENT', 'SETNAME', 'bugs5-after')
        renamed = entry()
        client_id = client.must('CLIENT', 'ID')
        client.close()
        for _ in range(200):
            if ('id=%d ' % client_id).encode() not in admin.must('CLIENT', 'LIST'):
                break
            time.sleep(.01)
        else:
            raise AssertionError('disconnect never observed')
        disconnected = entry()
        print('before', before, 'renamed', renamed, 'disconnected', disconnected, flush=True)
        assert renamed == before and disconnected == before, 'historical identity changed'
        print('slowlog historical identity PASS')
    finally:
        client.close()
        admin.must('CONFIG', 'SET', 'slowlog-log-slower-than', 10000)
        admin.close()


if __name__ == '__main__':
    main()
