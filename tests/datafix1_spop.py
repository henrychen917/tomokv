"""CD4.4: partial pops retain compact sets, values, metadata and memory bounds."""
import json
from datafix1_common import main, plain


def battery(p):
    for kind, members, encoding in [
        ('int16', list(range(100)), b'intset'),
        ('int32', list(range(100000, 100100)), b'intset'),
        ('int64', list(range(2**40, 2**40+100)), b'intset'),
        ('text', [f'm{i:03d}' for i in range(100)], b'listpack'),
        ('table', [f'm{i:03d}' for i in range(200)], b'hashtable')]:
        for count in (None, 0, 1, 2, 49, 50, 99, 100, 101, 166, 167, 199):
            key = f'spop:{kind}:{count}'
            p.cmd('SADD', key, *members)
            p.cmd('PEXPIRE', key, 60000)
            p.cmd('OBJECT', 'ENCODING', key)
            for name, c in p.each():
                before = c.cmd('MEMORY', 'USAGE', key)
                args = ['SPOP', key] + ([] if count is None else [count])
                result = c.cmd(*args)
                popped = [result] if count is None else result
                wanted = min(1 if count is None else count, len(members))
                remain = c.cmd('SMEMBERS', key)
                enc = c.cmd('OBJECT', 'ENCODING', key)
                after = c.cmd('MEMORY', 'USAGE', key)
                p.check(isinstance(popped, list) and len(popped) == wanted and
                        len(set(popped)) == wanted, (name, args, result))
                expected = {str(v).encode() for v in members}
                p.check(set(popped).isdisjoint(remain) and set(popped) | set(remain) == expected,
                        (name, key, 'conservation'))
                expected = encoding
                if remain and count is not None and len(remain) * 5 <= count:
                    expected = b'listpack' if encoding == b'hashtable' else encoding
                p.check(enc == (expected if remain else None), (name, key, 'encoding', enc))
                if remain:
                    p.check(c.cmd('PTTL', key) > 0, (name, key, 'TTL lost'))
                    p.check(after <= before, (name, key, 'partial pop grew memory', before, after))
                p.receipt.write(json.dumps(plain(dict(server=name, argv=args, popped=popped,
                    remaining=remain, encoding=enc, memory_before=before, memory_after=after)))+'\n')
    # Small counted pops retain an expanded representation; the large-count branch
    # rebuilds survivors and applies the current compact limits instead.
    p.cmd('CONFIG', 'SET', 'set-max-intset-entries', 2)
    p.cmd('SADD', 'incremental', 1, 2)
    p.cmd('SADD', 'incremental', 3)
    p.cmd('CONFIG', 'SET', 'set-max-intset-entries', 512)
    p.cmd('SPOP', 'incremental', 2, normalize=lambda x: len(x))
    p.cmd('OBJECT', 'ENCODING', 'incremental')
    for kind, members, config, value, expected in [
        ('table-text', [f'm{i:03d}' for i in range(60)], 'set-max-listpack-entries', 128, b'listpack'),
        ('table-int', list(range(60)), 'set-max-listpack-entries', 128, b'listpack'),
        ('int-limit', list(range(60)), 'set-max-intset-entries', 5, b'hashtable'),
        ('text-limit', [f'm{i:03d}' for i in range(60)], 'set-max-listpack-entries', 5, b'hashtable'),
        ('text-width', [f'm{i:03d}' for i in range(60)], 'set-max-listpack-value', 1, b'hashtable')]:
        p.cmd('CONFIG', 'SET', 'set-max-intset-entries', 512,
              'set-max-listpack-entries', 128, 'set-max-listpack-value', 64)
        if kind.startswith('table'):
            p.cmd('CONFIG', 'SET', 'set-max-intset-entries', 0, 'set-max-listpack-entries', 0)
        key = 'rebuild:' + kind
        p.cmd('SADD', key, *members)
        p.cmd('CONFIG', 'SET', config, value)
        for name, c in p.each():
            popped = c.cmd('SPOP', key, 50)
            remain = c.cmd('SMEMBERS', key)
            enc = c.cmd('OBJECT', 'ENCODING', key)
            p.check(len(popped) == 50 and len(set(popped)) == 50 and
                    set(popped).isdisjoint(remain) and
                    set(popped + remain) == {str(x).encode() for x in members},
                    (name, kind, 'survivor conservation'))
            p.check(enc == expected, (name, kind, 'rebuilt encoding', enc, expected))
            p.receipt.write(json.dumps(plain(dict(server=name, argv=['SPOP', key, 50],
                popped=popped, remaining=remain, encoding=enc, expected=expected)))+'\n')
    # Removing the sole wide integer does not narrow an intset. Rebuilding after
    # a large pop does: compare memory with a fresh set of exactly its survivors.
    p.cmd('CONFIG', 'SET', 'set-max-intset-entries', 1024,
          'set-max-listpack-entries', 128, 'set-max-listpack-value', 64)
    p.cmd('SADD', 'width-old', *range(600), 2**40)
    p.cmd('SREM', 'width-old', 2**40)
    for name, c in p.each():
        popped = c.cmd('SPOP', 'width-old', 500)
        remain = c.cmd('SMEMBERS', 'width-old')
        c.cmd('SADD', 'width-new', *remain)
        after = c.cmd('MEMORY', 'USAGE', 'width-old')
        fresh = c.cmd('MEMORY', 'USAGE', 'width-new')
        p.check(len(popped) == 500 and len(remain) == 100, (name, 'width counts'))
        p.check(after == fresh, (name, 'rebuilt integer width', after, fresh))
        p.receipt.write(json.dumps(plain(dict(server=name, argv=['SPOP', 'width-old', 500],
            popped=popped, remaining=remain, memory_after=after, memory_fresh=fresh)))+'\n')


if __name__ == '__main__':
    main('CD4.4', battery)
