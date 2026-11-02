#!/usr/bin/env python3
"""Round-5 CD5.4/5/6 and TM5.1 witnesses; no rates or server management.

The mover, WATCH and tracking sequences are derived from round5-read's
ls-maxmem{,2}.py, ls-watch2.py and zs-crash-repro.py. Geometry always names
the final keys. Each failure is retained instead of masking later cases.
"""
import argparse
import contextlib
import importlib.util
import json
from pathlib import Path
import sys

from _lib import Conn, RespError


def emit(**values):
    print(json.dumps(values, default=repr, sort_keys=True), flush=True)


def pair(c, prefix, placement):
    first = prefix + ':0'
    origin = c.must('DEBUG', 'SHARDS', first)[0]
    for start in range(1, 4096, 64):
        names = [f'{prefix}:{i}' for i in range(start, start + 64)]
        for key, where in zip(names, c.must('DEBUG', 'SHARDS', *names)):
            same_shard, same_owner = where[0] == origin[0], where[1] == origin[1]
            if ((placement == 'same-shard' and same_shard) or
                (placement == 'same-owner' and same_owner and not same_shard) or
                (placement == 'cross-owner' and not same_owner)):
                emit(keys=[first, key], placement=placement, locations=[origin, where])
                return first, key
    raise AssertionError('required placement unavailable: ' + placement)


def oom(c, a):
    failures, count = [], 0
    for policy in ('noeviction', 'volatile-lru'):
        for verb in ('SMOVE', 'LMOVE', 'RPOPLPUSH', 'BLMOVE', 'BRPOPLPUSH', 'RENAME', 'RENAMENX'):
            for placement in ('same-shard', 'same-owner', 'cross-owner'):
                c.must('CONFIG', 'SET', 'maxmemory', 0)
                c.must('FLUSHALL')
                src, dst = pair(c, f'txnfix4:{verb}:{placement}', placement)
                if verb == 'SMOVE':
                    c.must('SADD', src, 'm1', 'm2')
                    read = lambda key: sorted(c.must('SMEMBERS', key))
                    args = (verb, src, dst, 'm1')
                    expected = ([b'm2'], [b'm1'])
                elif verb in ('RENAME', 'RENAMENX'):
                    c.must('SET', src, 'payload')
                    read = lambda key: c.cmd('GET', key)
                    args = (verb, src, dst)
                    expected = (None, b'payload')
                else:
                    c.must('RPUSH', src, 'e1', 'e2', 'e3')
                    read = lambda key: c.must('LRANGE', key, 0, -1)
                    args = [verb, src, dst]
                    if verb in ('LMOVE', 'BLMOVE'): args += ['LEFT', 'RIGHT']
                    if verb.startswith('B'): args += ['0.01']
                    expected = None
                before = (read(src), read(dst))
                c.must('CONFIG', 'SET', 'maxmemory-policy', policy)
                # A one-byte cap proves over-budget admission, independent of
                # allocator size classes and the per-shard budget division.
                c.must('CONFIG', 'SET', 'maxmemory', 1)
                reply = c.cmd(*args)
                after = (read(src), read(dst))
                passed = (after == expected and not isinstance(reply, RespError)) if expected else (
                    isinstance(reply, RespError) and str(reply).startswith('OOM ') and after == before)
                count += 1
                emit(case='CD5.4', verb=verb, placement=placement, policy=policy,
                     reply=reply, before=before, after=after, passed=passed)
                if not passed: failures.append((verb, placement, policy))
    c.must('CONFIG', 'SET', 'maxmemory', 0)
    assert not failures, failures
    return count


def watch(c, a):
    failures, count = [], 0
    with contextlib.closing(Conn(a.host, a.port)) as w:
        for verb in ('LMPOP', 'ZMPOP', 'BZMPOP', 'BLMPOP'):
            for placement in ('same-shard', 'same-owner', 'cross-owner'):
                for members in (1, 3):
                    c.must('FLUSHALL')
                    missing, key = pair(c, f'txnfix4:{verb}:{members}', placement)
                    zset = 'Z' in verb
                    seed = ('ZADD', key, *sum(([i, str(i)] for i in range(members)), [])) if zset else (
                        'RPUSH', key, *map(str, range(members)))
                    c.must(*seed)
                    w.must('WATCH', key)
                    args = [verb] + ([0.01] if verb.startswith('B') else [])
                    args += [2, missing, key, 'MIN' if zset else 'LEFT']
                    popped = c.cmd(*args)
                    w.must('MULTI'); w.must('PING')
                    result = w.cmd('EXEC')
                    passed = isinstance(popped, list) and result is None
                    emit(case='CD5.5', verb=verb, placement=placement, members=members,
                         pop=popped, exec=result, passed=passed)
                    if not passed: failures.append((verb, placement, members))
                    # A miss must preserve WATCH; detecting every write by name
                    # would turn this real/no-op control red.
                    c.must('DEL', key)
                    w.must('WATCH', key)
                    c.cmd(*args)
                    w.must('MULTI'); w.must('PING')
                    assert w.cmd('EXEC') == [b'PONG'], 'empty pop dirtied WATCH'
                    count += 2
    assert not failures, failures
    return count


def crash(c, a):
    count = 0
    # Six original failing shapes, 200 fresh key/connection iterations each.
    # Cross-owner placement prevents a local lowering from hiding the defect.
    for family, resp, exec_first, flush in (
            ('zset', 3, True, True), ('zset', 3, True, False),
            ('zset', 3, False, False), ('zset', 2, True, False),
            ('list', 2, True, False), ('list', 3, False, False)):
        for iteration in range(a.iterations):
            c.must('FLUSHALL')
            missing, key = pair(c, f'txnfix4:crash:{family}:{iteration}', 'cross-owner')
            seed = ('ZADD', key, 1, 'a', 2, 'b', 3, 'c') if family == 'zset' else ('RPUSH', key, 'a', 'b', 'c')
            read = ('ZRANGE' if family == 'zset' else 'LRANGE', key, 0, -1)
            with contextlib.closing(Conn(a.host, a.port)) as w, contextlib.closing(Conn(a.host, a.port)) as t:
                c.must(*seed); w.must('WATCH', key)
                pop = c.must('ZMPOP' if family == 'zset' else 'LMPOP', 2, missing, key,
                             'MIN' if family == 'zset' else 'LEFT')
                assert isinstance(pop, list), pop
                if exec_first:
                    w.must('MULTI'); w.must('PING'); w.cmd('EXEC')
                if flush: c.must('FLUSHALL'); c.must(*seed)
                if resp == 3: t.must('HELLO', 3)
                t.must('CLIENT', 'TRACKING', 'ON')
                observed = t.cmd(*read)
                assert observed == ([b'a', b'b', b'c'] if flush else [b'b', b'c']), observed
                assert c.must('PING') == b'PONG'
            count += 1
        emit(case='CD5.6', family=family, resp=resp, exec_first=exec_first,
             flush=flush, iterations=a.iterations, passed=True)
    return count


def placement(c, a):
    path = Path(__file__).with_name('execfix.py')
    spec = importlib.util.spec_from_file_location('txnfix4_execfix', path)
    module = importlib.util.module_from_spec(spec)
    saved = sys.argv
    try:
        sys.argv = [str(path), a.host, str(a.port)]
        spec.loader.exec_module(module)
    finally:
        sys.argv = saved
    class SingleOwner:
        def command(self, *args):
            if args[:2] == ('DEBUG', 'SHARD'): return int(args[2].rsplit(':', 1)[1]) % 16
            if args[:2] == ('DEBUG', 'SHARDS'):
                return [[int(key.rsplit(':', 1)[1]) % 16, 6] for key in args[2:]]
            raise AssertionError(args)
    rejected = False
    try: module.two_owner_keys(SingleOwner(), 'planted-single-owner')
    except AssertionError: rejected = True
    assert rejected, 'TM5.1: helper accepted distinct shards on one planted owner'
    class Live:
        command = c.cmd
    for count in (2, 3):
        keys = module.two_owner_keys(Live(), 'final-suffix:family:119', count)
        rows = c.must('DEBUG', 'SHARDS', *keys)
        assert len({row[1] for row in rows}) >= 2, (keys, rows)
        emit(case='TM5.1', keys=keys, rows=rows, planted_single_owner_rejected=rejected)
    return 3


def main():
    p = argparse.ArgumentParser()
    p.add_argument('host'); p.add_argument('port', type=int)
    p.add_argument('--case', choices=('oom', 'watch', 'crash', 'placement'), required=True)
    p.add_argument('--iterations', type=int, default=200)
    a = p.parse_args()
    with contextlib.closing(Conn(a.host, a.port)) as c:
        total = globals()[a.case](c, a)
    emit(summary=a.case, checks=total, passed=True)


if __name__ == '__main__': main()
