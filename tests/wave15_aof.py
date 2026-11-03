#!/usr/bin/env python3
"""Finite AOF liveness/restart witnesses; selected gate jobs, never rate work."""
import argparse
from contextlib import closing
import itertools
import json
import os
from pathlib import Path
import subprocess
import socket
import time
import traceback

from _lib import Conn, RespError
import snapfix as s


def plain(value):
    if isinstance(value, bytes):
        return value.decode(errors='backslashreplace')
    if isinstance(value, list):
        return [plain(x) for x in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    return value


def settled(c):
    p = s.persistence(c)
    return p.get('aof_rewrite_in_progress') == '0' and p.get('aof_rewrite_scheduled', '0') == '0'


def choose(c, oracle, scenario):
    if oracle:
        return ['k', 'a', 'b', 'd', 'watch'], {}
    words = ['LEFT', 'MIN', 'COUNT', '2', '0', '100', 'km', 'STORE', 'm']
    names = [f'wave15:{i}' for i in range(1024)]
    locations = dict(zip(words + names, c.must('DEBUG', 'SHARDS', *words, *names)))
    io = s.io_thread(c)
    forbidden = {int(locations[word][0]) for word in words}
    if scenario == 'lmpop-same':
        selected = [k for k in names if locations[k][0] == locations['LEFT'][0]]
    elif scenario == 'lmpop-io':
        selected = [k for k in names if locations[k][0] != locations['LEFT'][0]
                    and locations[k][1] == io]
    else:
        selected = [k for k in names if locations[k][0] not in forbidden]
    assert selected, ('placement not armed', scenario, io, locations)
    shard = locations[selected[0]][0]
    selected = [k for k in selected if locations[k][0] == shard]
    assert len(selected) >= 4, ('same-shard source/destination inventory missing', selected)
    watch = next(k for k in names if locations[k][0] == locations['LEFT'][0])
    keys = selected[:4] + [watch]
    return keys, dict(io=io, keys={k: locations[k] for k in keys},
                      words={w: locations[w] for w in words})


def transaction(b, scenario, oracle):
    c = b.c
    keys, geometry = choose(c, oracle, scenario)
    k, a, other, dest, watch = keys
    expected_state = None
    if scenario.startswith('lmpop') or scenario in ('lpop', 'blmpop', 'watch', 'nosync'):
        assert c.must('RPUSH', k, 'a', 'b') == 2
        if scenario == 'lpop':
            command, expected = ['LPOP', k], [b'a']
        elif scenario == 'blmpop':
            command, expected = ['BLMPOP', 0, 1, k, 'LEFT'], [[k.encode(), [b'a']]]
        else:
            command = ['LMPOP', 1, k, 'LEFT']
            values = [b'a']
            if scenario == 'lmpop-count':
                command += ['COUNT', 2]
                values += [b'b']
            expected = [[k.encode(), values]]
        expected_state = (['LRANGE', k, 0, -1], [] if scenario == 'lmpop-count' else [b'b'])
    elif scenario == 'zmpop':
        assert c.must('ZADD', k, 1, 'a', 2, 'b') == 2
        command, expected = ['ZMPOP', 1, k, 'MIN'], [[k.encode(), [[b'a', b'1']]]]
        expected_state = (['ZRANGE', k, 0, -1, 'WITHSCORES'], [b'b', b'2'])
    elif scenario in ('zunion', 'zinter', 'zdiff'):
        assert c.must('ZADD', a, 1, 'm') == 1
        assert c.must('ZADD', other, 2, 'm') == 1
        command = [scenario.upper() + 'STORE', dest, 2, a, other]
        expected = [0 if scenario == 'zdiff' else 1]
        expected_state = (['ZRANGE', dest, 0, -1, 'WITHSCORES'],
                          [] if scenario == 'zdiff' else [b'm', b'3'])
    else:
        assert c.must('GEOADD', k, 0, 0, 'm') == 1
        bymember = 'member' in scenario
        verb = 'GEORADIUSBYMEMBER' if bymember else 'GEORADIUS'
        if scenario.endswith('-ro'):
            verb += '_RO'
        command = [verb, k] + (['m'] if bymember else [0, 0]) + [100, 'km']
        expected = [[b'm']]
        if scenario.endswith('-store'):
            command += ['STORE', dest]
            expected = [1]
            expected_state = (['ZRANGE', dest, 0, -1], [b'm'])
    if scenario == 'watch':
        assert c.must('WATCH', watch) == b'OK'
    before = int(s.persistence(c).get('aof_groups_committed', 0))
    assert c.must('MULTI') == b'OK'
    assert c.must(*command) == b'QUEUED'
    # Save the placement before EXEC: a wedged reply gate cannot return INFO.
    evidence = dict(geometry=geometry, command=command, expected=plain(expected), before=before)
    (b.directory / 'armed.json').write_text(json.dumps(evidence, indent=2) + '\n')
    actual = c.cmd('EXEC')
    assert actual == expected, (scenario, actual, expected)
    with closing(Conn('127.0.0.1', b.port, timeout=3)) as probe:
        assert probe.must('PING') == b'PONG'
    if not oracle and (scenario.startswith(('lmpop', 'zmpop')) or scenario == 'watch') and scenario != 'nosync':
        s.wait(lambda: int(s.persistence(c).get('aof_groups_committed', 0)) > before,
               'EXEC never committed its AOF participant group', timeout=3)
    if expected_state:
        assert c.cmd(*expected_state[0]) == expected_state[1], expected_state
    evidence['reply'] = plain(actual)
    return evidence, expected_state


def large(b, oracle, scenario):
    c = b.c
    key = 'big'
    geometry = {}
    if not oracle:
        names = [f'big:{i}' for i in range(256)]
        rows = c.must('DEBUG', 'SHARDS', *names)
        from _lib import topology
        roles = topology(c).roles
        ios = sorted(t for t, role in roles.items() if role in ('io', 'fused'))
        writer = ios[-1]
        key, where = next((k, row) for k, row in zip(names, rows)
                          if (row[1] == writer) == (scenario == 'writer-owner'))
        geometry = dict(writer=writer, key=key, placement=where, roles=roles)
    size = 128 * 1024 * 1024 if scenario == 'original128' else 32 * 1024 * 1024
    if scenario == 'small':
        size = 2 * 1024 * 1024
    before = s.persistence(c)
    evidence = dict(geometry=geometry, size=size, before=before)
    (b.directory / 'armed.json').write_text(json.dumps(evidence, indent=2) + '\n')
    assert c.cmd('SETRANGE', key, size - 1, 'x') == size
    with closing(Conn('127.0.0.1', b.port, timeout=3)) as probe:
        assert probe.must('PING') == b'PONG'
    requires_rewrite = not oracle and scenario in ('rewrite32', 'original128', 'writer-owner')
    s.wait(lambda: settled(c) and (not requires_rewrite or
           int(s.persistence(c)['aof_rewrites']) > int(before['aof_rewrites'])),
           'rewrite did not finish', timeout=60)
    after = s.persistence(c)
    if not oracle and scenario in ('rewrite32', 'original128', 'writer-owner'):
        assert int(after['aof_rewrites']) > int(before['aof_rewrites']), (before, after)
        # A finished rewrite, not merely an enabled policy, arms this witness.
        assert after['aof_last_bgrewrite_status'] == 'ok', after
        assert after['aof_last_write_status'] == 'ok', after
    assert c.must('STRLEN', key) == size
    assert c.must('GETRANGE', key, -1, -1) == b'x'
    evidence['after'] = after
    return evidence, (['STRLEN', key], size)


def run(args, directory, mode, engine, atomic, db, scenario, oracle):
    args.databases = db
    args.read_local = 0
    sync = 'no' if scenario == 'nosync' else 'everysec'
    extra = ['--appendonly', 'yes', '--appendfsync', sync]
    if args.case == 'large':
        extra += ['--auto-aof-rewrite-min-size', '64mb' if scenario == 'original128' else '1mb',
                  '--auto-aof-rewrite-percentage', '0' if scenario == 'no-rewrite' else '100']
    else:
        extra += ['--auto-aof-rewrite-percentage', '0']
    record = dict(mode=mode, engine=engine, atomic=atomic, databases=db,
                  scenario=scenario, oracle=oracle)
    b = None
    try:
        b = s.Boot(args, directory, mode, engine, atomic, oracle, extra=extra)
        s.wait(lambda: settled(b.c), 'initial rewrite never finished', timeout=30)
        evidence, expected = (large(b, oracle, scenario) if args.case == 'large' else
                              transaction(b, scenario, oracle))
        record.update(evidence)
        stop_error = None
        try:
            b.stop()
        except AssertionError as exc:
            # Acknowledged appendfsync=no effects must survive even if PRE's
            # phantom GCMT makes its shutdown drain fail. Inspect replay first.
            if scenario != 'nosync':
                raise
            stop_error = repr(exc)
            record['stop_error'] = stop_error
        if expected:
            b = s.Boot(args, directory, mode, engine, atomic, oracle, extra=extra, name='restart')
            assert b.c.cmd(*expected[0]) == expected[1], ('acknowledged effect lost on restart', expected)
            if not oracle:
                assert int(s.persistence(b.c).get('aof_groups_skipped_on_replay', 0)) == 0
            record['restart'] = plain(b.c.cmd(*expected[0]))
            b.stop()
        assert stop_error is None, stop_error
        record['verdict'] = 'PASS'
    except Exception as exc:
        record.update(verdict='FAIL', error=repr(exc), traceback=traceback.format_exc())
        if b and b.proc.poll() is None and args.capture_stacks:
            stack = directory / 'stacks.txt'
            with stack.open('w') as out:
                subprocess.run(['gdb', '-nx', '-batch', '-p', str(b.proc.pid),
                                '-ex', 'set pagination off', '-ex', 'thread apply all bt'],
                               stdout=out, stderr=subprocess.STDOUT, timeout=20)
    finally:
        if b:
            b.kill()
            if b.c is not None:
                b.c.close()
            # io_uring cancellation can release a killed listener after waitpid.
            # Require exclusive rebind before starting the next fresh scenario.
            def released():
                with socket.socket() as probe:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        probe.bind(('127.0.0.1', b.port))
                        probe.listen()
                        return True
                    except OSError:
                        return False
            s.wait(released, 'owned listener survived child teardown', timeout=10)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    print(record['verdict'], mode, engine, atomic, db, scenario, record.get('error', ''), flush=True)
    return record


def main():
    os.environ['LC_ALL'] = 'C'
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--case', choices=('participants', 'large'), required=True)
    p.add_argument('--modes', nargs='+', default=['1s', '2s'])
    p.add_argument('--engines', nargs='+', default=['uring', 'epoll'])
    p.add_argument('--databases', nargs='+', type=int, default=[1, 16])
    p.add_argument('--atomics', nargs='+', type=int, default=[0, 1])
    p.add_argument('--scenarios', nargs='+')
    p.add_argument('--capture-stacks', action='store_true')
    p.add_argument('--stall', type=float, default=5)
    a = p.parse_args()
    assert 20000 <= a.port <= 20098, 'wave15 port allocation'
    a.output.mkdir(parents=True, exist_ok=False)
    scenarios = a.scenarios or (['lmpop', 'zmpop', 'lmpop-count', 'lmpop-same', 'lmpop-io',
                                'lpop', 'blmpop', 'watch', 'nosync', 'zunion', 'zinter', 'zdiff',
                                'geo', 'geo-member', 'geo-ro', 'geo-member-ro',
                                'geo-store', 'geo-member-store'] if a.case == 'participants' else
                               ['rewrite32', 'no-rewrite', 'small', 'writer-owner', 'original128'])
    dbs = list(a.databases)
    rows = []
    for oracle in (True, False):
        matrix = [('1s', 'uring', 0, 16)] if oracle else itertools.product(a.modes, a.engines, a.atomics, dbs)
        for mode, engine, atomic, db in matrix:
            for scenario in scenarios:
                if scenario in ('lmpop-io', 'writer-owner') and (mode != '1s' or oracle):
                    continue
                name = f'{"redis" if oracle else "tomo"}-{mode}-{engine}-a{atomic}-d{db}-{scenario}'
                rows.append(run(a, a.output / name, mode, engine, atomic, db, scenario, oracle))
    (a.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    return int(any(r['verdict'] != 'PASS' for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
