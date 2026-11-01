#!/usr/bin/env python3
"""Restore a shared battery's requested atomic setting and verify the live value."""
import contextlib
import sys

from _lib import Conn


def restore(host, port, atomic):
    assert atomic in ('0', '1'), atomic
    with contextlib.closing(Conn(host, port)) as c:
        assert c.must('CONFIG', 'SET', 'atomic', atomic) == b'OK'
        actual = c.must('CONFIG', 'GET', 'atomic')
        assert actual == [b'atomic', atomic.encode()], ('TM4.1 live atomic mismatch', actual)
        print(f'TM4.1 live atomic={atomic}', flush=True)


if __name__ == '__main__':
    restore(sys.argv[1], int(sys.argv[2]), sys.argv[3])
