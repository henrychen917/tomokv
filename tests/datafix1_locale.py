"""CD4.6: environment default, live locale-collate, and binary STORE ordering."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from datafix1_common import main, Conn, plain
from known_difference import expect


def battery(p):
    defaults = p.cmd('CONFIG', 'GET', 'locale-collate')
    p.check(all(value == [b'locale-collate', b''] for value in defaults), defaults)
    values = ['b', 'A', 'a', 'B', 'c', 'C', '_x', 'é', 'z']
    p.cmd('RPUSH', 'l', *values)
    p.cmd('SADD', 's', *values)
    for i, value in enumerate(values):
        p.cmd('SET', 'weight:'+value, value)
        p.cmd('ZADD', 'z', i, value)
    # Every server boots in C. Explicit non-C collation must still differ,
    # and resetting the setting must restore the inherited C order.
    inherited = p.cmd('SORT_RO', 'l', 'ALPHA')
    p.cmd('CONFIG', 'SET', 'locale-collate', 'C')
    binary = p.cmd('SORT_RO', 'l', 'ALPHA')
    p.cmd('CONFIG', 'SET', 'locale-collate', 'en_US.UTF-8')
    explicit = p.cmd('SORT_RO', 'l', 'ALPHA')
    p.check(inherited == binary and all(a != b for a, b in zip(explicit, binary)),
            ('inherited C must differ from explicitly armed en_US.UTF-8', inherited, binary, explicit))
    p.cmd('CONFIG', 'SET', 'locale-collate', '')
    p.check(p.cmd('SORT_RO', 'l', 'ALPHA') == inherited, 'empty locale restores environment')
    for locale in ('', 'C', 'en_US.UTF-8', 'C.UTF-8', 'not_a_locale', 'C\x00suffix', ''):
        p.cmd('CONFIG', 'SET', 'locale-collate', locale)
        p.cmd('CONFIG', 'GET', 'locale-collate')
        lua = ('EVAL', "local t={'b','A','a','B','é'}; table.sort(t); return {('a'<'B') and 1 or 0,t}", 0)
        if locale == 'en_US.UTF-8':
            oracle = p.oracle.cmd(*lua)
            target = p.target.cmd(*lua) if p.target else oracle
            p.check(oracle == [1, [b'a', b'A', b'b', b'B', 'é'.encode()]],
                    ('Redis non-C Lua collation armed', oracle))
            compatible = expect(target, oracle, root='CD4.6-LUA-COLLATION (compat audit 6.12)',
                                known=[0, [b'A', b'B', b'a', b'b', 'é'.encode()]])
            p.receipt.write(json.dumps(plain(dict(argv=lua, oracle=oracle, target=target,
                known_difference=None if compatible else 'CD4.6-LUA-COLLATION'))) + '\n')
        else:
            p.cmd(*lua)
        for source in ('l', 's', 'z'):
            for command in ('SORT', 'SORT_RO'):
                p.cmd(command, source, 'ALPHA')
                p.cmd(command, source, 'ALPHA', 'DESC')
                p.cmd(command, source, 'ALPHA', 'BY', 'weight:*', 'LIMIT', 1, 5)
            p.cmd('SORT', source, 'ALPHA', 'STORE', 'dst')
            p.cmd('LRANGE', 'dst', 0, -1)
    p.cmd('CONFIG', 'SET', 'locale-collate', 'C', 'LOCALE-COLLATE', '')
    p.cmd('CONFIG', 'GET', 'locale-collate')
    p.cmd('CONFIG', 'SET', 'LOCALE-COLLATE', 'not_a_locale')
    p.cmd('CONFIG', 'GET', 'locale-collate')
    # Each concurrent SORT must use one complete collation snapshot. A freed or
    # mixed comparison locale cannot be excused as nondeterministic ordering.
    for name, c in p.each():
        c.cmd('RPUSH', 'race', *(values * 100))
        allowed = []
        for locale in ('C', 'en_US.UTF-8'):
            c.cmd('CONFIG', 'SET', 'locale-collate', locale)
            allowed.append(c.cmd('SORT', 'race', 'ALPHA'))
        start = threading.Barrier(3)
        port = c.s.getpeername()[1]

        def reader():
            with Conn(port) as other:
                start.wait()
                return [other.cmd('SORT', 'race', 'ALPHA') for _ in range(30)]

        with ThreadPoolExecutor(max_workers=2) as pool:
            readers = [pool.submit(reader) for _ in range(2)]
            start.wait()
            for i in range(30):
                p.check(c.cmd('CONFIG', 'SET', 'locale-collate',
                              'C' if i % 2 else 'en_US.UTF-8') == b'OK', (name, 'live update'))
            for reader in readers:
                for result in reader.result():
                    p.check(result in allowed, (name, 'mixed collation snapshot'))


if __name__ == '__main__':
    main('CD4.6', battery, multi=True)
