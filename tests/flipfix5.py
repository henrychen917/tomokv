#!/usr/bin/env python3
"""flipfix5 witness driver: FLIP while an all-shard or cross-owner storm runs.

`--case live-flip` runs flushfix2's unchanged witness (tests/flushfix2_siblings.py, copied
byte-identical from a396a42e5). `--case op-flip --op OP` replaces its FLUSHALL storm with another
all-shard or cross-owner operation. Every attempt boots a fresh 2s server on --cores/--port, runs
for --seconds, and is classified from the server's own exit status:

  pass   no worker error and a clean server exit (rc 0, not forced)
  abort  the server died on SIGABRT (rc -6) or on the diagnostic abort wrapper (rc 134)
  fail   anything else (a wrong reply, a stall, a non-abort death)

Only correctness evidence is recorded: counts, exit codes and log tails. No rates are claimed.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import threading
import time
import traceback

import flushfix2 as f
import flushfix2_siblings  # noqa: F401  (registers live-flip and its siblings in f.CASES)
import snapfix as s
from _lib import Conn, RespError, encode

OPS = ('FLUSHALL', 'FLUSHALL-ASYNC', 'FLUSHDB', 'SWAPDB', 'DBSIZE', 'KEYS', 'SCAN',
       'RANDOMKEY', 'BGSAVE', 'EXEC', 'EVAL', 'NONE')
ABORT_RCS = (-6, 134)
PORTS = range(20200, 20300)


def flipper(b, args, counts, refusals):
    def run(stop):
        with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
            while not stop.is_set():
                target = 4 if counts['flips'] % 2 == 0 else 6
                reply = c.cmd('FLIP', target, 8 - target)
                if isinstance(reply, RespError):
                    message = reply.message.decode(errors='replace')
                    assert message.startswith(('ERR FLIP', 'ERR a FLIP')), message
                    key = message.split(':')[0][:72]
                    refusals[key] = refusals.get(key, 0) + 1
                    counts['flip_refusals'] += 1
                    continue
                assert reply == b'OK', reply
                counts['flips'] += 1
    return run


def seed(c, args):
    """A modest resident set in two namespaces so walkers have real work on every owner."""
    dbs = (0, 7) if args.databases > 1 else (0,)
    for db in dbs:
        c.must('SELECT', db)
        for begin in range(0, args.population, 500):
            end = min(args.population, begin + 500)
            c.raw(b''.join(encode('SET', f'flipfix5:resident:{db}:{i}', 'v') for i in range(begin, end)))
            assert all(c.read() == b'OK' for _ in range(begin, end))
    c.must('SELECT', 0)


def operation(b, args, pair, counts):
    op = args.op
    other = 7 if args.databases > 1 else 0

    def run(stop):
        with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as c:
            while not stop.is_set():
                if op in ('FLUSHALL', 'FLUSHALL-ASYNC', 'FLUSHDB'):
                    verb = 'FLUSHDB' if op == 'FLUSHDB' else 'FLUSHALL'
                    mode = 'ASYNC' if op.endswith('ASYNC') else 'SYNC'
                    c.raw(encode('MSET', pair[0], 1, pair[1], 1) + encode(verb, mode))
                    assert [c.read(), c.read()] == [b'OK', b'OK']
                elif op == 'SWAPDB':
                    assert c.must('SWAPDB', 0, other) == b'OK'
                elif op == 'DBSIZE':
                    assert isinstance(c.must('DBSIZE'), int)
                elif op == 'KEYS':
                    assert isinstance(c.must('KEYS', 'flipfix5:resident:*'), list)
                elif op == 'SCAN':
                    cursor = b'0'
                    while True:
                        cursor, batch = c.must('SCAN', cursor, 'COUNT', 200)
                        assert isinstance(batch, list)
                        if cursor == b'0' or stop.is_set():
                            break
                elif op == 'RANDOMKEY':
                    reply = c.must('RANDOMKEY')
                    assert reply is None or isinstance(reply, bytes)
                elif op == 'BGSAVE':
                    reply = c.cmd('BGSAVE')
                    assert reply == b'Background saving started' or (
                        isinstance(reply, RespError) and b'in progress' in reply.message), reply
                    s.wait(lambda: s.persistence(c)['rdb_bgsave_in_progress'] == '0',
                           'BGSAVE stalled', args.stall)
                elif op == 'EXEC':
                    c.raw(encode('MULTI') + encode('INCR', pair[0]) + encode('INCR', pair[1]) +
                          encode('EXEC'))
                    assert [c.read() for _ in range(3)] == [b'OK', b'QUEUED', b'QUEUED']
                    value = c.read()
                    assert isinstance(value, list) and len(value) == 2 and value[0] == value[1], value
                elif op == 'EVAL':
                    reply = c.cmd('EVAL', s.WRITE, 2, *pair)
                    if isinstance(reply, RespError) and str(reply).startswith(s.REFUSALS):
                        counts['refused'] += 1
                        continue
                    assert isinstance(reply, list) and len(reply) == 2 and reply[0] == reply[1], reply
                elif op == 'NONE':
                    stop.wait(.05)
                    continue
                counts['ops'] += 1
    run.__name__ = f'op_{op.lower()}'
    return run


def op_flip(args, directory, mode, engine, atomic, oracle):
    assert not oracle and mode == '2s'
    counts = dict(ops=0, flips=0, flip_refusals=0, refused=0)
    refusals = {}
    with s.Boot(args, directory, mode, engine, atomic, oracle) as b:
        seed(b.c, args)
        pair, owners = s.keys_for(b.c, 'flipfix5:pair', False, 2)
        b.c.must('MSET', pair[0], 0, pair[1], 0)
        errors = s.run_storm(args.seconds, [operation(b, args, pair, counts),
                                            flipper(b, args, counts, refusals)], args.stall)
        result = dict(**counts, refusal_kinds=refusals, owners=owners)
        assert not errors and counts['flips'] and (counts['ops'] or args.op == 'NONE'), (result, errors)
        return result


CASES = dict(f.CASES, **{'op-flip': op_flip})


def server_exit(directory):
    path = directory / 'server.exit.json'
    return json.loads(path.read_text()) if path.exists() else None


def log_tail(directory, lines=12):
    path = directory / 'server.log'
    if not path.exists():
        return []
    return path.read_text(errors='replace').splitlines()[-lines:]


def counts_from_error(error):
    found = re.search(r"\{'flushes': \d+[^}]*\}|\{'ops': \d+[^}]*\}", error or '')
    if not found:
        return None
    return {k: int(v) for k, v in re.findall(r"'(\w+)': (\d+)", found.group(0))}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--case', choices=['live-flip', 'op-flip'], required=True)
    p.add_argument('--op', choices=OPS, default='FLUSHALL')
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', default='/home/user/Projects/redis/src/redis-server')
    p.add_argument('--cores', default='24-31')
    p.add_argument('--port', type=int, default=20200)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--engines', nargs='+', default=['uring', 'epoll'])
    p.add_argument('--atomics', nargs='+', type=int, default=[0, 1])
    p.add_argument('--databases', nargs='+', type=int, choices=[1, 16], default=[1, 16])
    p.add_argument('--flush-mode', choices=['SYNC', 'ASYNC'], default='SYNC')
    p.add_argument('--seconds', type=float, default=8)
    p.add_argument('--stall', type=float, default=10)
    p.add_argument('--attempts', type=int, default=1, help='fresh boots per leg')
    p.add_argument('--population', type=int, default=2000)
    p.add_argument('--stop-on-abort', type=int, choices=[0, 1], default=0)
    args = p.parse_args()
    assert args.port in PORTS, 'flipfix5 owns ports 20200-20299'
    assert 1 <= args.attempts <= 200
    os.environ['LC_ALL'] = 'C'
    # flushfix2's witness reads these knobs from its own parser.
    args.command, args.require_counters, args.no_oracle, args.fresh_attempts = 'FLUSHALL', 0, True, 1
    s.Boot = f.VerifiedBoot
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for databases in args.databases:
        for engine in args.engines:
            for atomic in args.atomics:
                leg = f'2s-{engine}-{atomic}-db{databases}'
                outcomes = []
                for attempt in range(args.attempts):
                    directory = args.output / leg / f'attempt-{attempt}'
                    began = time.monotonic()
                    leg_args = argparse.Namespace(**vars(args))
                    leg_args.databases = databases
                    record = dict(attempt=attempt)
                    try:
                        record['value'] = CASES[args.case](leg_args, directory, '2s', engine, atomic, False)
                        record['error'] = None
                    except Exception:
                        record['error'] = traceback.format_exc()
                    record['seconds'] = round(time.monotonic() - began, 3)
                    record['exit'] = server_exit(directory)
                    rc = (record['exit'] or {}).get('rc')
                    if record['error'] is None and record['exit'] == dict(rc=0, forced=False):
                        record['outcome'] = 'pass'
                    elif rc in ABORT_RCS:
                        record['outcome'] = 'abort'
                    else:
                        record['outcome'] = 'fail'
                    if record['outcome'] != 'pass':
                        record['counts'] = counts_from_error(record['error'])
                        record['log_tail'] = log_tail(directory)
                    outcomes.append(record)
                    print(json.dumps(dict(leg=leg, **{k: v for k, v in record.items()
                                                      if k not in ('error', 'log_tail')})), flush=True)
                    if record['outcome'] == 'abort' and args.stop_on_abort:
                        break
                tally = {k: sum(o['outcome'] == k for o in outcomes) for k in ('pass', 'abort', 'fail')}
                rows.append(dict(case=args.case, op=args.op if args.case == 'op-flip' else 'FLUSHALL',
                                 flush_mode=args.flush_mode, leg=leg, databases=databases,
                                 engine=engine, atomic=atomic, attempts=len(outcomes),
                                 seconds_per_attempt=args.seconds, tally=tally, outcomes=outcomes))
                (args.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    summary = [dict(leg=r['leg'], op=r['op'], **r['tally']) for r in rows]
    print(json.dumps(summary), flush=True)
    return int(any(r['tally']['abort'] or r['tally']['fail'] for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
