"""CD4.6: environment default, live locale-collate, and binary STORE ordering."""
from concurrent.futures import ThreadPoolExecutor
import threading
from datafix1_common import main, Conn


def battery(p):
    defaults = p.cmd('CONFIG', 'GET', 'locale-collate')
    p.check(all(value == [b'locale-collate', b''] for value in defaults), defaults)
    values = ['b', 'A', 'a', 'B', 'c', 'C', '_x', 'é', 'z']
    p.cmd('RPUSH', 'l', *values)
    p.cmd('SADD', 's', *values)
    for i, value in enumerate(values):
        p.cmd('SET', 'weight:'+value, value)
        p.cmd('ZADD', 'z', i, value)
    # The common boot helper explicitly sets en_US.UTF-8 for both processes.
    # Prove that the empty setting follows that environment even when the gate
    # itself exports C; comparing two accidentally C-pinned boots would be vacuous.
    inherited = p.cmd('SORT_RO', 'l', 'ALPHA')
    p.cmd('CONFIG', 'SET', 'locale-collate', 'C')
    binary = p.cmd('SORT_RO', 'l', 'ALPHA')
    p.cmd('CONFIG', 'SET', 'locale-collate', 'en_US.UTF-8')
    explicit = p.cmd('SORT_RO', 'l', 'ALPHA')
    p.check(inherited == explicit and all(a != b for a, b in zip(inherited, binary)),
            ('environment default must be en_US.UTF-8, distinct from C', inherited, binary, explicit))
    p.cmd('CONFIG', 'SET', 'locale-collate', '')
    p.check(p.cmd('SORT_RO', 'l', 'ALPHA') == inherited, 'empty locale restores environment')
    for locale in ('', 'C', 'en_US.UTF-8', 'C.UTF-8', 'not_a_locale', 'C\x00suffix', ''):
        p.cmd('CONFIG', 'SET', 'locale-collate', locale)
        p.cmd('CONFIG', 'GET', 'locale-collate')
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
