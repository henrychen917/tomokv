"""CD4.10: first-byte offset limits and the maximum eight-byte growth spill."""
from datafix1_common import main


def battery(p):
    limit = 1024 * 1024
    p.cmd('CONFIG', 'SET', 'proto-max-bulk-len', limit)
    for kind, bits in [('u1', 1), ('u8', 8), ('u16', 16), ('u63', 63), ('i64', 64)]:
        for offset in (limit*8-64, limit*8-8, limit*8-1, limit*8):
            key = f'bits:{kind}:{offset}'
            p.cmd('BITFIELD_RO', key, 'GET', kind, offset)
            p.cmd('BITFIELD', key, 'SET', kind, offset, 1, 'GET', kind, offset)
            p.cmd('STRLEN', key)
            p.cmd('BITFIELD', key, 'INCRBY', kind, offset, 1)
            p.cmd('BITFIELD_RO', key, 'GET', kind, offset)
            p.cmd('GETRANGE', key, limit-8, limit+8)
    for offset in ('#131071', '#131072', '#288230376151711744',
                   '#-288230376151711744', '#9223372036854775807',
                   '-1', '01', '+1', '9223372036854775808'):
        p.cmd('BITFIELD', 'indexed', 'SET', 'i64', offset, 123)
        p.cmd('BITFIELD_RO', 'indexed', 'GET', 'i64', offset)
    p.cmd('SET', 'keep', 'original')
    p.cmd('BITFIELD', 'keep', 'SET', 'u8', 0, 5, 'SET', 'i64', limit*8, 1)
    p.cmd('GET', 'keep')
    p.cmd('SETBIT', 'single', limit*8, 1)
    p.cmd('GETBIT', 'single', limit*8)
    # At TomoKV's supported protocol ceiling the last field still fits uint32_t.
    # Reads exercise the arithmetic without allocating a multi-gigabyte string.
    cap = 2**32 - 1 - 65536
    p.cmd('CONFIG', 'SET', 'proto-max-bulk-len', cap)
    p.cmd('BITFIELD_RO', 'missing', 'GET', 'i64', cap*8-1)
    p.cmd('BITFIELD_RO', 'missing', 'GET', 'i64', cap*8)


if __name__ == '__main__':
    main('CD4.10', battery)
