"""CD4.3: option permutations, lookup precedence, duplicate and invalid options."""
from itertools import permutations
import random
from datafix1_common import main


def count_without_order(p):
    # CD4.1/CD4.19: compare to Redis itself, not this candidate's own ASC.
    rng = random.Random(4242)
    points = []
    for index in range(300):
        points += [round(rng.uniform(-.5, .5), 6),
                   round(rng.uniform(-.5, .5), 6), f'p{index}']
    key, dst = 'geo:count:source', 'geo:count:destination'
    p.check(p.cmd('GEOADD', key, *points) == (300, 300), 'GEO COUNT seed')
    for index in range(20):
        lon, lat = round(rng.uniform(-.4, .4), 4), round(rng.uniform(-.4, .4), 4)
        options = ('FROMLONLAT', lon, lat, 'BYRADIUS', 100, 'km', 'COUNT', 5)
        oracle, target = p.cmd('GEOSEARCH', key, *options)
        p.check(isinstance(oracle, list) and len(oracle) == 5,
                ('GEO COUNT oracle returned five neighbors', index, oracle))
        for command in ('GEORADIUS', 'GEORADIUS_RO'):
            p.cmd(command, key, lon, lat, 100, 'km', 'COUNT', 5)
        p.check(p.cmd('GEOSEARCHSTORE', dst, key, *options) == (5, 5),
                ('GEOSEARCHSTORE count', index))
        p.cmd('ZRANGE', dst, 0, -1)
        p.check(p.cmd('GEORADIUS', key, lon, lat, 100, 'km',
                      'COUNT', 5, 'STORE', dst) == (5, 5), ('GEORADIUS STORE count', index))
        p.cmd('ZRANGE', dst, 0, -1)
        member = f'p{index}'
        p.cmd('GEOSEARCH', key, 'FROMMEMBER', member, 'BYRADIUS', 100, 'km', 'COUNT', 5)
        for command in ('GEORADIUSBYMEMBER', 'GEORADIUSBYMEMBER_RO'):
            p.cmd(command, key, member, 100, 'km', 'COUNT', 5)
    p.cmd('DEL', key, dst)
    print('GEO COUNT without ASC/DESC/ANY: 20 centers compared directly to Redis', flush=True)


def battery(p):
    count_without_order(p)
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
