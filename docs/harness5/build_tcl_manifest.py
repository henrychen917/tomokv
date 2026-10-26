"""Derive the gated Redis Tcl subset: every assertion that passes on TomoKV in both modes.

Candidates are the upstream files with at least one assertion passing in both TomoKV modes
in the survey. Every test that failed or hung in ANY TomoKV run (full-file survey, reach
discovery and final passes, earlier rounds of this builder) is named in the file's
--skipfile. Each round runs every candidate in 2s and 1s; a test failing in any run joins
the skip list and the round repeats, until ROUNDS consecutive rounds agree: identical
complete passing multiset in both modes, no failure, no hang. Skipping a failing test can
change later state, so stability is measured under the final skip list, never assumed.
The manifest records upstream hashes, skip lists (with the reason each was added), extra
runtest arguments and the exact passing multiset. No assertion body is modified.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'docs/harness5'))
import redis_tcl as suite
from reach_tcl import hung_test, TAGS

UPSTREAM = Path('/home/user/Projects/redis')
SUPPORT = ['tests/support/' + n for n in ('aofmanifest.tcl', 'benchmark.tcl', 'cli.tcl', 'cluster.tcl',
           'cluster_util.tcl', 'redis.tcl', 'response_transformers.tcl', 'server.tcl', 'test.tcl',
           'tmpfile.tcl', 'util.tcl')] + ['runtest', 'tests/test_helper.tcl', 'src/version.h']


def name(event):
    return event['test'].split(' in tests/')[0]


def survey_failures():
    """Every test that failed or hung on TomoKV anywhere in the survey evidence."""
    failed, passing = {}, {}
    rows = []
    for mode in ('2s', '1s'):
        rows += json.loads(gzip.open(ROOT / f'docs/harness5/redis-tcl-{mode}.json.gz').read())['rows']
    reach = ROOT / 'build/h5reach'
    for path in (reach / 'd2s/report.json', reach / 'd1s/report.json'):
        rows += json.loads(path.read_text())['rows']
    rows += [r for r in json.loads(gzip.open(reach / 'final/report.json.gz').read())['rows'] if r['mode'] != 'redis']
    for row in rows:
        unit = row['file']
        bad = failed.setdefault(unit, {})
        for event in row['events']:
            if event['status'] in ('err', 'exception') and name(event):
                bad.setdefault(name(event), f"failed on TomoKV {row['mode']} in the survey")
        for skipped in row.get('skip_tests', []):
            bad.setdefault(skipped, f"hung on TomoKV in the survey (reach discovery)")
        hung = hung_test(row)
        if hung:
            bad.setdefault(hung, f"hung on TomoKV {row['mode']} in the survey")
    for mode in ('2s', '1s'):
        for row in json.loads(gzip.open(ROOT / f'docs/harness5/redis-tcl-{mode}.json.gz').read())['rows']:
            passing.setdefault(row['file'], {})[mode] = {name(e) for e in row['events'] if e['status'] == 'ok'}
    candidates = sorted(u for u, modes in passing.items()
                        if '/moduleapi/' not in u and modes.get('2s', set()) & modes.get('1s', set()))
    return candidates, failed


def run_mode(options, mode, tree, cores, ports, candidates, skips, round_index, out):
    """One TomoKV mode over every candidate file; returns its observations (no shared writes)."""
    port, controller, base = ports
    inventory, seconds, setups, problems, new_skips = {}, {}, {}, [], {}
    for unit in candidates:
        folder = out / f'round{round_index}' / mode
        skipfile = folder / (unit.replace('/', '_') + '.skip')
        skipfile.parent.mkdir(parents=True, exist_ok=True)
        skipfile.write_text(''.join(n + '\n' for n in sorted(skips[unit])), encoding='utf-8')
        args = argparse.Namespace(output=folder, binary=options.binary.resolve(), mode=mode, cores=cores,
            port=port, baseport=base, idle_timeout=60, file_timeout=300, ratio=options.ratio)
        row = suite.run_file(args, tree, unit, extra=['--skipfile', str(skipfile), *TAGS.get(unit, [])])
        ok = Counter(name(e) for e in row['events'] if e['status'] == 'ok')
        setup = suite.setup_errors(row)
        inventory[unit], seconds[unit], setups[unit] = ok, row['seconds'], setup
        before = len(problems)
        done = False
        for event in row['events']:
            if event['status'] == 'done':
                done = True
            if (done and event['status'] == 'exception' and 'expected non-negative integer but got ""' in event['data']
                    and 'read $::test_server_fd $bytes' in event['data']):
                continue  # upstream's post-completion controller EOF (also on Redis); counts() excludes it too
            if event['status'] == 'err' and not name(event):
                continue  # a block-setup error: named by signature, compared across modes and rounds
            if event['status'] in ('err', 'exception'):
                problems.append((unit, mode, name(event) or '<file>', event['data'][:200]))
                if name(event):
                    new_skips.setdefault((unit, name(event)), f'failed on TomoKV {mode} in builder round {round_index}')
        hung = hung_test(row)
        if hung:
            problems.append((unit, mode, hung, 'hung'))
            new_skips.setdefault((unit, hung), f'hung on TomoKV {mode} in builder round {round_index}')
        expected_rc = 1 if (setup or len(problems) > before) else 0
        if not row['complete'] or row['error'] or row['exit_code'] != expected_rc:
            problems.append((unit, mode, '<file>', f"complete={row['complete']} rc={row['exit_code']} error={row['error']}"))
        print(f"round {round_index} {mode} {unit}: {sum(ok.values())} ok, {row['failed']} fail, "
              f"complete={row['complete']} {row['seconds']:.1f}s", flush=True)
    return inventory, seconds, problems, new_skips, setups


def main():
    from concurrent.futures import ThreadPoolExecutor
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--cores-2s', required=True)
    p.add_argument('--cores-1s', required=True)
    p.add_argument('--ports-2s', required=True, help='server,controller,base')
    p.add_argument('--ports-1s', required=True, help='server,controller,base')
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--rounds', type=int, default=3)
    p.add_argument('--max-rounds', type=int, default=8)
    p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--seed-history', type=Path, action='append')
    options = p.parse_args()
    out = options.output.resolve()
    modes = {m: dict(cores=getattr(options, f'cores_{m}'),
                     ports=tuple(int(v) for v in getattr(options, f'ports_{m}').split(','))) for m in ('2s', '1s')}
    for m, spec in modes.items():
        spec['tree'] = out / f'checkout-{m}'
        suite.prepare(UPSTREAM, spec['tree'], controller_port=spec['ports'][1])
    candidates, failed = survey_failures()
    skips = {u: dict(failed.get(u, {})) for u in candidates}
    for seed in options.seed_history or []:
        # Named failures an earlier builder run already observed (same binary and upstream).
        for row in json.loads(seed.read_text()):
            for unit, mode, test, data in row['problems']:
                if unit in skips and test != '<file>' and 'expected non-negative integer but got' not in data:
                    skips[unit].setdefault(test, f"failed or hung on TomoKV {mode} in an earlier builder run (round {row['round']})")
    history, stable, previous = [], 0, None
    for round_index in range(options.max_rounds):
        with ThreadPoolExecutor(2) as pool:
            futures = {m: pool.submit(run_mode, options, m, spec['tree'], spec['cores'], spec['ports'],
                                      candidates, skips, round_index, out) for m, spec in modes.items()}
            results = {m: f.result() for m, f in futures.items()}
        inventory = {u: {m: results[m][0][u] for m in modes} for u in candidates}
        seconds = {u: {m: results[m][1][u] for m in modes} for u in candidates}
        problems = results['2s'][2] + results['1s'][2]
        for m in modes:
            for (unit, test), reason in results[m][3].items():
                skips[unit].setdefault(test, reason)
        setups = {u: {m: results[m][4][u] for m in modes} for u in candidates}
        agree = all(inventory[u]['2s'] == inventory[u]['1s'] and setups[u]['2s'] == setups[u]['1s']
                    for u in candidates)
        same = previous is not None and all(inventory[u] == previous[0][u] and setups[u] == previous[1][u]
                                            for u in candidates)
        clean = not problems and agree
        stable = (stable + 1 if stable and same else 1) if clean else 0
        history.append(dict(round=round_index, problems=problems, modes_agree=agree, seconds=seconds,
                            passing={u: sum(inventory[u]['2s'].values()) for u in candidates}))
        (out / 'history.json').write_text(json.dumps(history, indent=1) + '\n')
        print(f'round {round_index}: problems={len(problems)} modes_agree={agree} stable={stable}', flush=True)
        previous = (inventory, setups)
        if stable >= options.rounds:
            break
    else:
        raise SystemExit('no stable passing subset within the round budget')
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    files = {}
    for unit in candidates:
        passed = sorted(inventory[unit]['2s'].elements())
        if not passed:
            continue
        recent = [h['seconds'][unit] for h in history[-options.rounds:]]
        files[unit] = dict(sha256=sha(UPSTREAM / 'tests' / (unit + '.tcl')), passed_tests=passed,
                           skip_tests=dict(sorted(skips[unit].items())), extra_args=TAGS.get(unit, []),
                           known_setup_errors=[dict(command=c, reply=r, count=n)
                                               for (c, r), n in sorted(setups[unit]['2s'].items())],
                           seconds={m: round(max(r[m] for r in recent), 2) for m in ('2s', '1s')})
    manifest = dict(schema=2, redis_version='7.4.10',
        source_commit='f103d127b9747965e28f20615ef790332661fc68',
        selection=('every upstream assertion passing in BOTH TomoKV modes; each file runs with --skipfile naming '
                   'every test that failed or hung on TomoKV in the survey or the builder; the passing multiset was '
                   f'identical in {options.rounds} consecutive clean rounds in both modes; no assertion body modified'),
        binary_sha256=sha(options.binary), support={n: sha(UPSTREAM / n) for n in SUPPORT}, files=files)
    options.manifest.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    print('files', len(files), 'assertions', sum(len(f['passed_tests']) for f in files.values()),
          'skipped', sum(len(f['skip_tests']) for f in files.values()))


if __name__ == '__main__':
    main()
