"""CD4.12: exact RAND/SCAN errors and validation order, table driven."""
from datafix1_common import main


def battery(p):
    p.cmd('HSET', 'h', 'f', 'v')
    p.cmd('ZADD', 'z', 1, 'a')
    p.cmd('SADD', 's', 'a')
    p.cmd('SET', 'wrong', 'string')
    for command, present, option in [('HRANDFIELD', 'h', 'WITHVALUES'),
                                     ('SRANDMEMBER', 's', 'bogus'),
                                     ('ZRANDMEMBER', 'z', 'WITHSCORES')]:
        for key in (present, 'missing', 'wrong'):
            for count in ('x', '01', '+1', ' 1', '-0', 2**63, -2**63-1,
                          -2**63, 0, 1, -2, 2**62, 2**63-1):
                for tail in [(), (option,), ('bad',), (option, 'extra')]:
                    p.cmd(command, key, count, *tail)
            # Valid huge negative counts only touch missing/wrong-type keys:
            # requesting that many real members would be an unbounded reply.
            if key != present:
                for count in (-2**63+1, -2**62, -2**62+1, 2**62-1):
                    for tail in [(), (option,), ('bad',), (option, 'extra')]:
                        p.cmd(command, key, count, *tail)
            for count in (-2**62,):
                if command != 'SRANDMEMBER':
                    p.cmd(command, key, count, option)
    tails = [('COUNT', 0), ('COUNT', -1), ('COUNT', 'x'), ('COUNT', '01'),
             ('COUNT', 2**63), ('COUNT',), ('MATCH',), ('bad',),
             ('NOVALUES',), ('NOVALUES', 'COUNT', 'x'),
             ('COUNT', 'x', 'NOVALUES'), ('TYPE', 'hash')]
    for command, present in [('HSCAN', 'h'), ('SSCAN', 's'), ('ZSCAN', 'z')]:
        for key in (present, 'missing', 'wrong'):
            for cursor in ('x', ' 0', str(2**64), 0):
                for tail in tails:
                    p.cmd(command, key, cursor, *tail)
    for cursor in ('x', ' 0', str(2**64), 0):
        for tail in tails[:-1]:
            p.cmd('SCAN', cursor, *tail)
    # The remaining original register probes are controls, including negative
    # counts that must not mutate their collections.
    for args in [('ZRANDMEMBER', 'z', 1, 'WITHVALUES'), ('ZSCAN', 'z', 0, 'COUNT', 0),
                 ('SPOP', 's', -1), ('ZPOPMIN', 'z', -1), ('LPOP', 'missing', -1),
                 ('SPOP', 'missing', 'x')]:
        p.cmd(*args)


if __name__ == '__main__':
    main('CD4.12', battery)
