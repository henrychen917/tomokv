#!/usr/bin/env python3
"""Run the round4 black-box repros as non-vacuous gate witnesses, without rates."""
import argparse
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CREATORS = ('COPY-list,RESTORE-list,RENAME-list(ctl),SORTSTORE-list(ctl),LMOVE-list(ctl),'
            'COPY-zset,RESTORE-zset,ZUNIONSTORE,ZINTERSTORE,ZDIFFSTORE,ZRANGESTORE,'
            'GEOSEARCHSTORE,RENAME-zset(ctl),COPY-stream,RENAME-stream(ctl)')
REMOVALS = 'SET+RENAME,EXPIRE(EXISTS)+RENAME,FLUSHDB+RENAME,FLUSHALL+RENAME,DEL+RENAME(ctl)'


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
    results = []

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
        if s['hits'] != 3 or s['served'] != 3:
            errors.append(f"wake: hits={s['hits']}/3 served={s['served']}/3")
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
        return errors

    def creators_check(s, records, server):
        return [f"{name}: {r}" for name, r in s['results'].items()
                if r['hits'] != 2 or r['served'] != 2 or r['defects']]

    def removed_check(s, records, server):
        errors = []
        for name, r in s['results'].items():
            expected = 'error: WRONGTYPE' if name == 'SET+RENAME' else 'error: NOGROUP'
            if r['hits'] != 10 or r['outcomes'] != {expected: 10}:
                errors.append(f"{name}: hits={r['hits']} outcomes={r['outcomes']}")
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
