#!/usr/bin/env python3
"""Round-5 S1 witnesses: pinned gate boots, exact Redis 7.4 comparisons.

GEO fixtures reuse G-T2/G-T3; HLL placements reuse S-T22/S-T23; channel
transcripts reuse T40/T47; stream watermarks reuse T21/T21b. The LCS witness
lowers the live limit so PRE demonstrates the missing guard without a 3.6GB
allocation. Every declared leg runs even after a comparison fails.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import random

from clientfix import Conn, Error, plain
from datafix1_common import Pair, boot


def stored(p, key):
    # Compare the stored member/score mapping, not a formatter's decimal spelling.
    def scores(reply):
        return dict(zip(reply[::2], map(float, reply[1::2])))
    p.cmd('ZRANGE', key, 0, -1, 'WITHSCORES', normalize=scores)


def geo(p):
    # G-T2 / codex T9-T10, including every legacy verb and STORE variant.
    p.cmd('GEOADD', 'g', -5.2, 78, 'centre', 149.88, 84.78, 'far', -10, 79, 'near')
    for origin in (['FROMLONLAT', -5.2, 78], ['FROMMEMBER', 'centre']):
        p.cmd('GEOSEARCH', 'g', *origin, 'BYRADIUS', 2000, 'km', 'ASC', 'WITHDIST')
        for distance in ([], ['STOREDIST']):
            p.cmd('GEOSEARCHSTORE', 'dst', 'g', *origin, 'BYRADIUS', 2000, 'km', *distance)
            stored(p, 'dst')
    for verb in ('GEORADIUS', 'GEORADIUS_RO', 'GEORADIUSBYMEMBER', 'GEORADIUSBYMEMBER_RO'):
        origin = ['centre'] if 'BYMEMBER' in verb else [-5.2, 78]
        p.cmd(verb, 'g', *origin, 2000, 'km', 'ASC')
        if not verb.endswith('_RO'):
            for option in ('STORE', 'STOREDIST'):
                p.cmd(verb, 'g', *origin, 2000, 'km', option, 'dst')
                stored(p, 'dst')
    p.cmd('DEL', 'g')
    p.cmd('GEOADD', 'g', 121, -82, 'point')
    p.cmd('GEOSEARCH', 'g', 'FROMLONLAT', -21, -69, 'BYBOX', 4000, 4000, 'km')
    p.cmd('GEOSEARCHSTORE', 'dst', 'g', 'FROMLONLAT', -21, -69, 'BYBOX', 4000, 4000, 'km')
    stored(p, 'dst')

    rng = random.Random(20261102)
    points = [(rng.uniform(-179.999, 179.999), rng.uniform(-85, 85), f'p{i}') for i in range(600)]
    p.cmd('GEOADD', 'random', *[v for row in points for v in row])
    options = [[], ['ASC'], ['DESC'], ['COUNT', 7], ['COUNT', 7, 'ANY'],
               ['ASC', 'COUNT', 7, 'ANY'], ['DESC', 'COUNT', 7, 'ANY']]
    for lat in [-85, -80, -66, -55, -30, 0, 30, 55, 66, 78, 84, 85] + [rng.uniform(-85, 85) for _ in range(12)]:
        lon = rng.uniform(-180, 180)
        meters = rng.choice([50000, 500000, 1000000, 2000000, 5000000, 10000000])
        for shape in ('BYRADIUS', 'BYBOX'):
            for unit, factor in [('m', 1), ('km', 1000), ('ft', .3048), ('mi', 1609.34)]:
                size = [meters / factor] if shape == 'BYRADIUS' else [2 * meters / factor, 2 * meters / factor]
                search = ['FROMLONLAT', lon, lat, shape, *size, unit]
                for opts in options:
                    # ANY and unsorted traversal must agree too: do not sort away a wrong subset.
                    p.cmd('GEOSEARCH', 'random', *search, *opts)
                    if unit == 'km':
                        for dist in ([], ['STOREDIST']):
                            p.cmd('GEOSEARCHSTORE', 'random-dst', 'random', *search, *opts, *dist)
                            stored(p, 'random-dst')


def scores(p):
    # G-T3. GEOPOS/FROMMEMBER on invalid scores are the separate CD5.8 S2 item.
    for score in [None, '0', '-1', '-0.5', '-1000000', '-inf', 'inf', '1e300',
                  '9223372036854775808', '4503599627370496', '9007199254740992']:
        p.cmd('DEL', 'g')
        p.cmd('GEOADD', 'g', 13.361389, 38.115556, 'Palermo', 15.087269, 37.502669, 'Catania',
              13.5, 38, 'a', 14, 37.8, 'b', 14.5, 37.6, 'c')
        if score is not None:
            p.cmd('ZADD', 'g', score, 'junk')
        for shape in (['BYRADIUS', 200], ['BYBOX', 400, 400]):
            p.cmd('GEOSEARCH', 'g', 'FROMLONLAT', 14, 37.8, *shape, 'km', 'ASC')
            p.cmd('GEOSEARCHSTORE', 'dst', 'g', 'FROMLONLAT', 14, 37.8, *shape, 'km')
            stored(p, 'dst')
        for verb in ('GEORADIUS', 'GEORADIUS_RO', 'GEORADIUSBYMEMBER', 'GEORADIUSBYMEMBER_RO'):
            origin = ['b'] if 'BYMEMBER' in verb else [14, 37.8]
            p.cmd(verb, 'g', *origin, 200, 'km', 'ASC')
        # The global cover must still exclude every out-of-range score.
        p.cmd('GEOSEARCH', 'g', 'FROMLONLAT', 0, 0, 'BYRADIUS', 'inf', 'm', 'ASC')
    # Fractional valid scores belong to the half-open double range as in Redis.
    p.cmd('DEL', 'g')
    p.cmd('ZADD', 'g', .5, 'fraction', 0, 'zero', -0.5, 'negative')
    p.cmd('GEOSEARCH', 'g', 'FROMLONLAT', -179.99, -85, 'BYRADIUS', 100, 'km', 'ASC')


def placements(p):
    names = [f'cmdfix2:{i}' for i in range(1024)]
    rows = p.target.cmd('DEBUG', 'SHARDS', *names)
    where = dict(zip(names, rows))
    shard, owner = rows[0]
    same = [n for n in names if where[n][0] == shard][:4]
    local = next(n for n in names if where[n][1] == owner and where[n][0] != shard)
    cross = next(n for n in names if where[n][1] != owner)
    p.check(len(same) == 4, 'four same-shard keys found')
    p.receipt.write(json.dumps(dict(placements={n: where[n] for n in same + [local, cross]})) + '\n')
    return same, local, cross


def hll(p):
    same, local, cross = placements(p)
    for b in (same[1], local, cross):
        a, dst, absent = same[0], same[2], same[3]
        for transaction in (False, True):
            p.cmd('DEL', a, b, dst, absent)
            p.cmd('PFADD', a, '1', '2')
            p.cmd('PFADD', b, '2', '3')
            if transaction:
                p.cmd('MULTI')
            for cmd in [('PFCOUNT', a, b), ('PFMERGE', dst, a, b), ('PFCOUNT', dst),
                        ('PFADD', b, '4'), ('PFCOUNT', a, b, absent),
                        ('PFMERGE', a, b), ('PFCOUNT', a), ('PFMERGE', absent),
                        ('PFCOUNT', absent)]:
                p.cmd(*cmd)
            if transaction:
                p.cmd('EXEC')
            for key in (a, b, dst, absent):
                p.cmd('PFCOUNT', key)
                p.cmd('GET', key)
        for value in ('bad hll',):
            p.cmd('SET', b, value)
            p.cmd('MULTI')
            p.cmd('PFCOUNT', a, b)
            p.cmd('PFMERGE', dst, a, b)
            p.cmd('EXEC')
            p.cmd('GET', dst)


def lcs(p):
    # Exact 1MiB table boundary, all reply forms, and live limit changes.
    same, local, cross = placements(p)
    p.cmd('CONFIG', 'SET', 'proto-max-bulk-len', 1048576)
    for b in (same[1], local, cross):
        a = same[0]
        for n in (511, 512, 1024):
            p.cmd('SET', a, 'a' * n)
            p.cmd('SET', b, 'a' * n)
            for options in ([], ['LEN'], ['IDX', 'WITHMATCHLEN']):
                p.cmd('LCS', a, b, *options)
            p.cmd('MULTI')
            p.cmd('LCS', a, b, 'LEN')
            p.cmd('EXEC')
        p.cmd('CONFIG', 'SET', 'proto-max-bulk-len', 8388608)
        p.cmd('LCS', a, b, 'LEN')
        p.cmd('CONFIG', 'SET', 'proto-max-bulk-len', 1048576)
    p.cmd('SET', same[0], '')
    p.cmd('SET', same[1], 'a' * 262144)
    p.cmd('LCS', same[0], same[1], 'LEN')
    p.cmd('CONFIG', 'SET', 'proto-max-bulk-len', 536870912)


def channels(p):
    # T40/T47 plus SUBSCRIBE family and in-EXEC ACL mutation.
    for verb in ('PUBLISH', 'SPUBLISH', 'SUBSCRIBE', 'SSUBSCRIBE', 'PSUBSCRIBE'):
        with Conn(p.oracle.s.getpeername()[1]) as r, Conn(p.target.s.getpeername()[1]) as t:
            q = Pair(r, t, p.receipt)
            args = [verb, 'secret'] + (['payload'] if 'PUBLISH' in verb else [])
            p.cmd('ACL', 'SETUSER', 'channel-user', 'reset', 'on', '>p', '+@all', '~*', '&allowed')
            q.cmd('AUTH', 'channel-user', 'p')
            q.cmd('MULTI')
            q.cmd(*args)
            q.cmd('EXEC')
            # Queue with permission; revoke on a separate administrator connection.
            p.cmd('ACL', 'SETUSER', 'channel-user', '&secret')
            q.cmd('MULTI')
            q.cmd(*args)
            p.cmd('ACL', 'SETUSER', 'channel-user', 'resetchannels')
            q.cmd('EXEC')
            # The ACL shadow for a preceding SETUSER in this same EXEC must check channels too.
            p.cmd('ACL', 'SETUSER', 'channel-user', '&secret')
            q.cmd('MULTI')
            q.cmd('ACL', 'SETUSER', 'channel-user', 'resetchannels')
            q.cmd(*args)
            q.cmd('EXEC')
            # Command permission alone cannot grant access to a channel.
            # Selector syntax is an explicit pre-existing unsupported surface.
            p.cmd('ACL', 'SETUSER', 'channel-user', 'reset', 'on', '>p', '+multi', '+exec',
                  f'+{verb.lower()}', '&allowed')
            q.cmd('MULTI')
            q.cmd(*args)
            q.cmd('EXEC')
            p.checks += q.checks
            p.failures += q.failures
    p.cmd('ACL', 'DELUSER', 'channel-user')


def xsetid(p):
    # T21: deleted ID still in the PEL must never be reused after a rejected rewind.
    p.cmd('XADD', 's', '1-0', 'f', 'old')
    p.cmd('XADD', 's', '2-0', 'f', 'pending')
    p.cmd('XGROUP', 'CREATE', 's', 'g', '0')
    p.cmd('XREADGROUP', 'GROUP', 'g', 'c', 'STREAMS', 's', '>')
    p.cmd('XDEL', 's', '2-0')
    p.cmd('XSETID', 's', '1-5', 'MAXDELETEDID', '1-0')
    p.cmd('XADD', 's', '2-0', 'f', 'replacement')
    p.cmd('XREADGROUP', 'GROUP', 'g', 'c', 'STREAMS', 's', '0')
    p.cmd('XCLAIM', 's', 'g', 'other', 0, '2-0')
    # T21b: zero is ignored; lag remains unknown across a deletion gap.
    for i in range(1, 11):
        p.cmd('XADD', 'lag', f'{i}-0', 'f', 'v')
    p.cmd('XGROUP', 'CREATE', 'lag', 'g', '0')
    p.cmd('XREADGROUP', 'GROUP', 'g', 'c', 'COUNT', 3, 'STREAMS', 'lag', '>')
    p.cmd('XDEL', 'lag', '5-0')
    p.cmd('XSETID', 'lag', '10-0', 'MAXDELETEDID', '0-0')
    p.cmd('XINFO', 'GROUPS', 'lag')
    def metadata(reply):
        d = dict(zip(reply[::2], reply[1::2]))
        return {k: d[k] for k in (b'last-generated-id', b'max-deleted-entry-id', b'entries-added', b'length')}
    p.cmd('XINFO', 'STREAM', 'lag', normalize=metadata)
    p.cmd('SET', 'wrong', 'value')
    for key in ('missing', 'wrong', 'lag'):
        for opts in (['MAXDELETEDID', '11-0'], ['ENTRIESADDED', -1],
                     ['ENTRIESADDED', 1], ['MAXDELETEDID', '11-0', 'bad'],
                     ['MAXDELETEDID', '9-0', 'MAXDELETEDID', '0-0'],
                     ['ENTRIESADDED', 9, 'ENTRIESADDED', 15]):
            p.cmd('XSETID', key, '10-0', *opts)
    p.cmd('XTRIM', 'lag', 'MAXLEN', 0)
    p.cmd('XSETID', 'lag', '10-0', 'ENTRIESADDED', 0, 'MAXDELETEDID', 0)
    p.cmd('XINFO', 'STREAM', 'lag', normalize=metadata)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    parser.add_argument('--oracle', required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--case', choices=['geo', 'scores', 'hll', 'lcs', 'channels', 'xsetid'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = []
    for engine in ('uring', 'epoll'):
        for mode, local in (('1s', 0), ('1s', 1), ('2s', 0), ('2s', 1)):
            for atomic in (0, 1):
                for databases in (1, 16):
                    name = f'{engine}-{mode}-rl{local}-a{atomic}-db{databases}'
                    directory = args.output / name
                    result = dict(leg=name, checks=0, failures=[])
                    try:
                        with boot(args.oracle, args.port + 1, args.cores, directory / 'oracle', oracle=True) as r:
                            flags = ['--shards', '16', '--thread-mode', mode, '--read-local', str(local),
                                     '--databases', str(databases), '--atomic', str(atomic), '--net-io', engine,
                                     '--flip-auto', '0', '--client-lb', '0', '--key-lb', '0']
                            if mode == '2s':
                                flags += ['--ratio', args.ratio]
                            with boot(args.binary, args.port, args.cores, directory / 'target', flags) as t:
                                with (directory / 'replies.jsonl').open('w') as receipt:
                                    pair = Pair(r, t, receipt)
                                    if databases == 16:
                                        pair.cmd('SELECT', 7)
                                    globals()[args.case](pair)
                                    result.update(checks=pair.checks, failures=pair.failures)
                    except Exception as e:
                        result['failures'].append(repr(e))
                    results.append(result)
                    print(json.dumps(dict(case=args.case, leg=name, checks=result['checks'],
                                          failures=len(result['failures']))), flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'summary.json').write_text(json.dumps(results, indent=2, default=plain) + '\n')
    raise SystemExit(any(r['failures'] for r in results))


if __name__ == '__main__':
    main()
