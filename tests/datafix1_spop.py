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
        for count in (None, 0, 1, 2, 49, 50, 99, 100, 101):
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
                p.check(enc == (encoding if remain else None), (name, key, 'encoding', enc))
                if remain:
                    p.check(c.cmd('PTTL', key) > 0, (name, key, 'TTL lost'))
                    p.check(after <= before, (name, key, 'partial pop grew memory', before, after))
                p.receipt.write(json.dumps(plain(dict(server=name, argv=args, popped=popped,
                    remaining=remain, encoding=enc, memory_before=before, memory_after=after)))+'\n')
    # Existing expanded sets never demote, even if the current limits admit compact storage.
    p.cmd('CONFIG', 'SET', 'set-max-intset-entries', 2)
    p.cmd('SADD', 'incremental', 1, 2)
    p.cmd('SADD', 'incremental', 3)
    p.cmd('CONFIG', 'SET', 'set-max-intset-entries', 512)
    p.cmd('SPOP', 'incremental', 2, normalize=lambda x: len(x))
    p.cmd('OBJECT', 'ENCODING', 'incremental')


if __name__ == '__main__':
    main('CD4.4', battery)
