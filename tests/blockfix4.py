#!/usr/bin/env python3
"""Run the round4 black-box repros as non-vacuous gate witnesses, without rates."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CREATORS = ('COPY-list,RESTORE-list,RENAME-list(ctl),SORTSTORE-list(ctl),LMOVE-list(ctl),'
            'COPY-zset,RESTORE-zset,ZUNIONSTORE,ZINTERSTORE,ZDIFFSTORE,ZRANGESTORE,'
            'GEOSEARCHSTORE,RENAME-zset(ctl),COPY-stream,RESTORE-stream,RENAME-stream(ctl)')
REMOVALS = ('SET+RENAME,MSET+RENAME,EXPIRE(EXISTS)+RENAME,FLUSHDB+RENAME,FLUSHALL+RENAME,'
            'FLUSHDB-ASYNC+RENAME,FLUSHALL-ASYNC+RENAME,DEL+RENAME(ctl)')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--engine', choices=['uring', 'epoll'], required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--case', choices=['scripts', 'moves', 'creators', 'removed', 'mpop'], required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, LC_ALL='C', BLOCKFIX4_BINARY=str(Path(a.binary).resolve()),
               BLOCKFIX4_ORACLE=str(Path(a.oracle).resolve()), BLOCKFIX4_CORES=a.cores,
               BLOCKFIX4_ENGINE=a.engine)
    sources = [Path(__file__), *sorted((ROOT / 'blockfix4_repro').rglob('*.py'))]
    (a.output / 'witness.json').write_text(json.dumps(dict(
        case=a.case, engine=a.engine, cores=a.cores, port=a.port,
        databases=int(env.get('BLOCKFIX4_DATABASES', '1')),
        sources={str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sources},
        binary_sha256=hashlib.sha256(Path(a.binary).read_bytes()).hexdigest(),
        oracle_sha256=hashlib.sha256(Path(a.oracle).read_bytes()).hexdigest()), indent=2) + '\n')
    results = []
    creator_oracle = {}

    def run(server, mode, rl, atomic, script, extra, check):
        label = '-'.join(map(str, [server, mode, rl, atomic, len(results)]))
        dest = a.output / label
        dest.mkdir()
        cmd = [sys.executable, str(ROOT / 'blockfix4_repro' / script), '--server', server,
               '--mode', mode, '--rl', str(rl), '--atomic', str(atomic), '--port', str(a.port)] + extra
        child_env = dict(env, BLOCKFIX4_OUTPUT=str(dest.resolve()))
        with (dest / 'stdout.log').open('w') as out:
            proc = subprocess.run(cmd, env=child_env, stdout=out, stderr=subprocess.STDOUT, timeout=240)
        logs = list((dest / 'logs').glob('*.jsonl'))
        records = [json.loads(line) for path in logs for line in path.read_text().splitlines()]
        summaries = [r for r in records if r.get('event') == 'summary']
        errors = []
        if proc.returncode or len(summaries) != 1:
            errors.append(f'child rc={proc.returncode}, summaries={len(summaries)}')
        else:
            errors += check(summaries[0], records, server)
        row = dict(label=label, command=cmd, passed=not errors, errors=errors,
                   summary=summaries[0] if summaries else None)
        results.append(row)
        print(label, 'PASS' if not errors else 'FAIL', '; '.join(errors), flush=True)
        (a.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')

    def script_check(s, records, server):
        errors = []
        served = 0
        for r in records:
            if 'i' not in r:
                continue
            ready = r.get('served_within_grace', False)
            # ATOMIC-COMMIT-HOLD also holds the resumed atomic BLMOVE's
            # commit. It must complete upon release, without a rescue push.
            if s['variant'] == 'hold' and r.get('kind') == 'BLMOVE':
                ready |= r.get('served_after_hold_release', False)
            served += bool(ready)
            if ready:
                expected = 'x' if r['kind'] == 'BLMOVE' else f"[{r['key']}, x]"
                if r.get('waiter_reply') != expected:
                    errors.append(f"{r['kind']}: wrong pushed value: {r.get('waiter_reply')!r}")
        if s['hits'] != 3 or served != 3:
            errors.append(f"wake: hits={s['hits']}/3 served={served}/3")
        if s['mid_llen'] != {'1': 3}:
            errors.append(f"script completion: LLEN={s['mid_llen']}")
        return errors

    def move_check(s, records, server):
        errors = []
        if s['parked'] != s['attempts'] or not s['attempts']:
            errors.append('waiter did not park')
        if server != 'redis' and not s['hits']:
            errors.append('no stolen-element window in 30 fresh attempts')
        if s['defects_nil'] or s['hit_waiter_other'] or s['nonhit_other']:
            errors.append(f"nil={s['defects_nil']} other={s['hit_waiter_other'] + s['nonhit_other']}")
        for r in records:
            if r.get('hit') and r.get('after_second_push') != 'y':
                errors.append('stolen-element waiter did not consume the second push')
                break
            if 'dst_after' in r and r['dst_after'] != ('[y]' if r['hit'] else '[x]'):
                errors.append(f"moved destination: {r['dst_after']!r}")
                break
        return errors

    def natural_check(s, records, server):
        errors = []
        if s['attempts'] != 128 or s['parked'] != 128 or not s['hits']:
            errors.append(f"natural MVCC window: {s}")
        if s['served'] != 128 or s['hit_defects'] or s['nonhit_defects']:
            errors.append(f"natural script wake: {s}")
        if any(r.get('eval') != '1' for r in records if 'eval' in r):
            errors.append('natural script observed an intermediate pop')
        return errors

    def creators_check(s, records, server):
        errors = []
        if set(s['results']) != set(CREATORS.split(',')):
            errors.append('creator inventory incomplete')
        for r in records:
            if 'i' not in r or not r.get('hit') or not r.get('served_within_grace'):
                continue
            reply = r.get('waiter_reply', '').replace(r['key'], '<key>')
            name = r['creator']
            if server == 'redis':
                if not reply.startswith('[') or '<key>' not in reply:
                    errors.append(f'{name}: oracle did not return the created collection')
                creator_oracle.setdefault(name, reply)
            if name not in creator_oracle or reply != creator_oracle[name]:
                errors.append(f'{name}: value differs from the oracle: {reply!r}')
        return errors + [f"{name}: {r}" for name, r in s['results'].items()
                         if r['hits'] != 2 or r['served'] != 2 or r['defects']]

    def removed_check(s, records, server):
        errors = []
        if set(s['results']) != set(REMOVALS.split(',')):
            errors.append('removal inventory incomplete')
        for name, r in s['results'].items():
            expected = 'error: WRONGTYPE' if name in ('SET+RENAME', 'MSET+RENAME') else 'error: NOGROUP'
            if r['hits'] != 10 or r['outcomes'] != {expected: 10}:
                errors.append(f"{name}: hits={r['hits']} outcomes={r['outcomes']}")
        for r in records:
            if 'i' not in r or not r.get('hit'):
                continue
            expected = ('(error) WRONGTYPE Operation against a key holding the wrong kind of value'
                        if r['case'] in ('SET+RENAME', 'MSET+RENAME') else
                        f"(error) NOGROUP No such key '{r['key']}' or consumer group 'g' in XREADGROUP with GROUP option")
            if r.get('waiter_reply') != expected:
                errors.append(f"{r['case']}: exact error mismatch: {r.get('waiter_reply')!r}")
                break
        return errors

    def mpop_check(s, records, server):
        errors = []
        if s['attempts'] != 3200 or not s['contended'] or s['defects'] or s['error'] or s['other']:
            errors.append(f"attempts={s['attempts']} contended={s['contended']} null={s['defects']} errors={s['error'] + s['other']}")
        if not all(r['fallback_after'] > 0 for r in records if 'fallback_after' in r):
            errors.append('fallback drained')
        return errors

    geometries = [('redis', '2s', 0, 0)] + [
        ('tomokv', *g) for g in itertools.product(['2s', '1s'], [0, 1], [0, 1])]
    for server, mode, rl, atomic in geometries:
        if a.case == 'scripts':
            for pusher in ['eval', 'evalsha', 'fcall']:
                for variant in ['plain'] + (['hold'] if server == 'tomokv' and atomic else []):
                    run(server, mode, rl, atomic, 'item1_script_push.py',
                        ['--attempts', '3', '--grace', '0.3', '--variant', variant, '--pusher', pusher], script_check)
            if server == 'tomokv' and atomic:
                for order in ['after', 'race']:
                    run(server, mode, rl, atomic, 'item1_natural.py',
                        ['--attempts', '128', '--order', order, '--grace', '0.3', '--long-wait', '0.3'], natural_check)
        elif a.case == 'moves':
            for placement in (['random'] if server == 'redis' else ['same-shard', 'same-owner', 'cross-owner']):
                run(server, mode, rl, atomic, 'item2_move_nil.py',
                    ['--attempts', '30', '--grace', '0.05', '--placement', placement], move_check)
        elif a.case == 'creators':
            for placement in (['random'] if server == 'redis' else ['same-shard', 'cross-owner']):
                run(server, mode, rl, atomic, 'item4_creators.py',
                    ['--creators', CREATORS, '--max-attempts', '2', '--confirm', '2', '--grace', '0.3',
                     '--long-wait', '0.3', '--placement', placement], creators_check)
        elif a.case == 'removed':
            run(server, mode, rl, atomic, 'item5_stream_removed.py',
                ['--cases', REMOVALS, '--max-hits', '10', '--confirm', '10', '--grace', '0.3',
                 '--long-wait', '0.3'], removed_check)
        else:
            for command in ['LMPOP', 'ZMPOP']:
                run(server, mode, rl, atomic, 'item6_mpop_null.py',
                    ['--cmd', command, '--ops', '200', '--rounds', '1'], mpop_check)
    return int(any(not r['passed'] for r in results))


if __name__ == '__main__':
    sys.exit(main())
