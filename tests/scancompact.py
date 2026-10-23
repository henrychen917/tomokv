#!/usr/bin/env python3
"""CD4.2: compact scans finish atomically, including COUNT/MATCH/NOVALUES.

The mutation arms independently assert the full-iteration guarantee; they do
not assume a cursor representation. Run unchanged against Redis 7.4 too.
"""
import sys
from _lib import Conn


def main():
    c = Conn(sys.argv[1], int(sys.argv[2]))
    failures = []
    try:
        for mutation in ('delete', 'promote'):
            key = 'bugs5:hash:' + mutation
            c.must('DEL', key)
            fields = [f'f{i}'.encode() for i in range(20)]
            c.must('HSET', key, *sum(([f, b'v'] for f in fields), []))
            assert c.must('OBJECT', 'ENCODING', key) == b'listpack'
            cursor, pairs = c.must('HSCAN', key, 0, 'COUNT', 3)
            seen = set(pairs[::2])
            if mutation == 'delete':
                removed = pairs[0]
                c.must('HDEL', key, removed)
                survivors = set(fields) - {removed}
            else:
                c.must('HSET', key, 'promoter', 'x' * 100)
                assert c.must('OBJECT', 'ENCODING', key) == b'hashtable'
                survivors = set(fields)
            for _ in range(1000):
                if cursor == b'0':
                    break
                cursor, pairs = c.must('HSCAN', key, cursor, 'COUNT', 3)
                seen.update(pairs[::2])
            else:
                raise AssertionError('scan did not terminate')
            missing = sorted(survivors - seen)
            print(mutation, 'missing', missing, flush=True)
            if missing:
                failures.append((mutation, missing))

        # Redis consumes the entire compact representation even with a nonzero
        # cursor. COUNT is a work hint, not a hard page-size bound.
        for kind, add, scan, expected, encoding in (
            ('hash', ('HSET', 'a', '1', 'b', '2'), 'HSCAN', [b'a', b'1', b'b', b'2'], b'listpack'),
            ('set', ('SADD', 'a', 'b'), 'SSCAN', [b'a', b'b'], b'listpack'),
            ('intset', ('SADD', '1', '2'), 'SSCAN', [b'1', b'2'], b'intset'),
            ('zset', ('ZADD', '1', 'a', '2', 'b'), 'ZSCAN', [b'a', b'1', b'b', b'2'], b'listpack'),
        ):
            key = 'bugs5:compact:' + kind
            c.must('DEL', key)
            c.must(add[0], key, *add[1:])
            assert c.must('OBJECT', 'ENCODING', key) == encoding
            for start in (0, 1, 999):
                cur, values = c.must(scan, key, start, 'COUNT', 1)
                if cur != b'0' or sorted(values) != sorted(expected):
                    failures.append((kind, start, cur, values))
            got = c.must(scan, key, 0, 'MATCH', 'absent*', 'COUNT', 1)
            if got != [b'0', []]:
                failures.append((kind, 'MATCH', got))
            if kind == 'hash':
                got = c.must(scan, key, 0, 'MATCH', 'a', 'COUNT', 1, 'NOVALUES')
                if got != [b'0', [b'a']]:
                    failures.append(('NOVALUES', got))
        assert not failures, failures
        print('compact scan guarantee PASS')
    finally:
        c.close()


if __name__ == '__main__':
    main()
