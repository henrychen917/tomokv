"""CD4.5: shrinking quicklists, half-limit boundary, and every pop/mover path."""
from datafix1_common import main
from clientfix import Error


def mpop_errors(p):
    # The upstream Tcl assertions accept "ERR numkeys*" / "ERR count*".
    # Compare whole replies to Redis, including every illegal-argument shape
    # in those tests, so an unrelated suffix cannot masquerade as compatibility.
    for protocol in (2, 3):
        for _, conn in p.each():
            hello = conn.cmd('HELLO', protocol)
            assert isinstance(hello, dict if protocol == 3 else list), hello
            fields = hello if isinstance(hello, dict) else dict(zip(hello[::2], hello[1::2]))
            assert fields[b'proto'] == protocol, hello
        cases = 0
        for verb in ('LMPOP', 'BLMPOP', 'ZMPOP', 'BZMPOP'):
            prefix = (verb, 1) if verb.startswith('B') else (verb,)
            edge, other = ('LEFT', 'RIGHT') if 'LMPOP' in verb else ('MIN', 'MAX')
            key, second = 'mpop:errors:first', 'mpop:errors:second'
            tails = [(), (1,), (1, key)]
            tails += [(n, key, edge) for n in (0, 'a', -1)]
            tails += [(1, key, 'bad_where'), (1, key, edge, 'bad_arg'),
                      (1, key, other, edge), (1, key, 'COUNT'),
                      (1, key, edge, 'COUNT', 1, 'COUNT', 2),
                      (2, key, second, 'bad_where')]
            tails += [(1, key, edge, 'COUNT', n) for n in (0, 'a', -1)]
            tails += [(2, key, second, other, 'COUNT', -1)]
            for tail in tails:
                oracle, target = p.cmd(*prefix, *tail)
                p.check(isinstance(oracle, Error) and isinstance(target, Error),
                        ('MPOP error path required', protocol, prefix + tail, oracle, target))
                cases += 1
            p.cmd('SET', key, 'wrong-type')
            oracle, target = p.cmd(*prefix, 1, key, edge)
            p.check(isinstance(oracle, Error) and isinstance(target, Error),
                    ('MPOP wrong-type path required', protocol, verb, oracle, target))
            p.check(p.cmd('GET', key) == (b'wrong-type', b'wrong-type'),
                    ('MPOP error must preserve value', protocol, verb))
            p.cmd('DEL', key, second)
            cases += 1
        assert cases == 68
        print(f'MPOP exact-error replies RESP{protocol}: {cases}', flush=True)
    for _, conn in p.each():
        conn.cmd('HELLO', 2)


def battery(p):
    mpop_errors(p)
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
