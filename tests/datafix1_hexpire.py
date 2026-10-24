"""CD4.11: expire-value validation precedes optional condition/FIELDS parsing."""
from datafix1_common import main


def battery(p):
    p.cmd('SET', 'wrong', 'string')
    for command in ('HEXPIRE', 'HPEXPIRE', 'HEXPIREAT', 'HPEXPIREAT'):
        for key in ('h', 'missing', 'wrong'):
            for value in (-1, -5, '9223372036854775808', 'x', '01',
                          2**46, 2**63-1, 100):
                for tail in [('FIELDS', 2, 'f'), ('FIELDS', 0, 'f'),
                             ('FIELD', 1, 'f'), ('NX', 'XX', 'FIELDS', 1, 'f'),
                             ('FIELDS', 1, 'f'), ('FIELDS', 'x', 'f')]:
                    if key == 'h': p.cmd('HSET', key, 'f', 'v')
                    p.cmd(command, key, value, *tail)
        unit = 1000 if command in ('HEXPIRE', 'HEXPIREAT') else 1
        for value in ((2**46-1)//unit, (2**46-1)//unit+1):
            p.cmd('HSET', 'bound', 'f', 'v')
            p.cmd(command, 'bound', value, 'FIELDS', 1, 'f')


if __name__ == '__main__':
    main('CD4.11', battery)
