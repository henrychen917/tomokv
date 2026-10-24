"""CD4.3: option permutations, lookup precedence, duplicate and invalid options."""
from itertools import permutations
from datafix1_common import main


def battery(p):
    p.cmd('GEOADD', 'g', 0, 0, 'a', 0.01, 0.01, 'b')
    p.cmd('SET', 'wrong', 'v')
    for command in ('GEOSEARCH', 'GEOSEARCHSTORE'):
        prefix = [command, 'g'] if command == 'GEOSEARCH' else [command, 'dst', 'g']
        for center in (['FROMMEMBER', 'a'], ['FROMLONLAT', 0, 0]):
            for shape in (['BYRADIUS', 10, 'km'], ['BYBOX', 20, 20, 'km']):
                for parts in permutations([center, shape, ['ASC'], ['COUNT', 1]]):
                    p.cmd(*prefix, *(v for part in parts for v in part))
        for tail in [
            ['ANY', 'COUNT', 10], ['COUNT', 10, 'ASC', 'ANY'], ['STORE', 'dst'],
            ['STOREDIST'], ['COUNT', '01'], ['COUNT', '+1'], ['COUNT', 'x'],
            ['COUNT', '9223372036854775808'], ['COUNT', 0], ['COUNT', -1],
            ['FROMMEMBER', 'b'], ['FROMLONLAT', 0, 0], ['BYBOX', 1, 1, 'km'],
            ['BYRADIUS', 2, 'km'], ['WITHDIST', 'STOREDIST'], ['ANY', 'bad'],
        ]:
            p.cmd(*prefix, 'FROMMEMBER', 'a', 'BYRADIUS', 10, 'km', *tail)
        for key in ('g', 'missing', 'wrong'):
            pre = [command, key] if command == 'GEOSEARCH' else [command, 'dst', key]
            for opts in [
                ['WITHDIST', 'WITHHASH', 'WITHCOORD', 'ASC', 'DESC'],
                ['FROMLONLAT', 0, 0, 'ASC', 'DESC'],
                ['BYRADIUS', 1, 'km', 'ASC', 'DESC'],
                ['FROMMEMBER', 'absent', 'BYRADIUS', 'bad', 'unit'],
                ['BYRADIUS', 'bad', 'unit', 'FROMMEMBER', 'absent'],
                ['FROMLONLAT', 181, 91, 'BYRADIUS', 'bad', 'unit'],
                ['FROMMEMBER', 'a', 'BYBOX', -1, 'bad', 'unit'],
                ['FROMMEMBER', 'a', 'BYBOX', -1, 1, 'unit'],
                ['FROMMEMBER', 'a', 'BYRADIUS', -1, 'unit'],
            ]:
                p.cmd(*pre, *opts)
    for command in ('GEORADIUS', 'GEORADIUS_RO', 'GEORADIUSBYMEMBER', 'GEORADIUSBYMEMBER_RO'):
        member = 'BYMEMBER' in command
        for key in ('g', 'missing', 'wrong'):
            for radius, unit in [(1, 'km'), ('bad', 'unit'), (-1, 'unit')]:
                center = ['absent'] if member else [181, 91]
                p.cmd(command, key, *center, radius, unit)
            center = ['a'] if member else [0, 0]
            for opts in [['ANY', 'COUNT', 10, 'ASC'], ['ANY'], ['COUNT', '01'],
                         ['STORE', 'dst', 'WITHDIST'], ['STORE', 'd1', 'STOREDIST', 'd2']]:
                p.cmd(command, key, *center, 10, 'km', *opts)
    p.cmd('ZRANGE', 'dst', 0, -1, 'WITHSCORES')


if __name__ == '__main__':
    main('CD4.3', battery, multi=True)
