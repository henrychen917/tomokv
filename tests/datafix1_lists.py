"""CD4.5: shrinking quicklists, half-limit boundary, and every pop/mover path."""
from datafix1_common import main


def battery(p):
    # With a count limit, shrinking at exactly half demotes, half+1 does not.
    for fill in (4, 5, 8):
        p.cmd('CONFIG', 'SET', 'list-max-listpack-size', fill)
        for command in ('LPOP', 'RPOP', 'LTRIM', 'LREM', 'LSET', 'LMPOP', 'BLMPOP',
                        'BLPOP', 'BRPOP', 'LMOVE', 'RPOPLPUSH', 'BLMOVE', 'BRPOPLPUSH'):
            key = f'l:{fill}:{command}'
            p.cmd('RPUSH', key, *(['x'] * (fill + 1)))
            p.cmd('OBJECT', 'ENCODING', key)
            p.cmd('LTRIM', key, 0, fill//2)
            p.cmd('OBJECT', 'ENCODING', key)
            if command in ('LPOP', 'RPOP'): p.cmd(command, key)
            elif command == 'LTRIM': p.cmd(command, key, 0, fill//2-1)
            elif command == 'LREM': p.cmd(command, key, 1, 'x')
            elif command == 'LSET':
                # Raising the live threshold leaves a one-node quicklist eligible
                # for conversion when LSET performs its shrinking check.
                p.cmd('CONFIG', 'SET', 'list-max-listpack-size', fill*2)
                p.cmd(command, key, 0, 'y')
                p.cmd('CONFIG', 'SET', 'list-max-listpack-size', fill)
            elif command == 'LMPOP': p.cmd(command, 1, key, 'LEFT')
            elif command == 'BLMPOP': p.cmd(command, 0, 1, key, 'RIGHT')
            elif command in ('BLPOP', 'BRPOP'): p.cmd(command, key, 0)
            elif command == 'LMOVE': p.cmd(command, key, 'dst', 'RIGHT', 'LEFT')
            elif command == 'RPOPLPUSH': p.cmd(command, key, 'dst')
            elif command == 'BLMOVE': p.cmd(command, key, 'dst', 'LEFT', 'RIGHT', 0)
            else: p.cmd(command, key, 'dst', 0)
            p.cmd('OBJECT', 'ENCODING', key)
            p.cmd('LRANGE', key, 0, -1)
    # Exact packed-byte boundaries: header 7 + string header 2 + backlen 2.
    for length in (4085, 4086):
        p.cmd('CONFIG', 'SET', 'list-max-listpack-size', -2)
        key = f'bytes:{length}'
        p.cmd('RPUSH', key, 'x'*length, 'z'*5000)
        p.cmd('OBJECT', 'ENCODING', key)
        p.cmd('RPOP', key)
        p.cmd('OBJECT', 'ENCODING', key)
    # Audit reproduction, with memory shrinking as the nodes disappear.
    p.cmd('CONFIG', 'SET', 'list-max-listpack-size', -2)
    for command in ('LTRIM', 'RPOP', 'LPOP'):
        key = 'large:'+command
        p.cmd('RPUSH', key, *['x'*100+str(i) for i in range(100)])
        before = [c.cmd('MEMORY', 'USAGE', key) for _, c in p.each()]
        if command == 'LTRIM': p.cmd(command, key, 0, 4)
        else: p.cmd(command, key, 95)
        p.cmd('OBJECT', 'ENCODING', key)
        for (name, c), old in zip(p.each(), before):
            p.check(c.cmd('MEMORY', 'USAGE', key) < old, (name, key, 'memory did not shrink'))


if __name__ == '__main__':
    main('CD4.5', battery, multi=True)
