#!/usr/bin/env python3
"""Require PRE/PAD failures, POST success, and exact C1 PRE/PAD reply equivalence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--label', default='-complete')
p.add_argument('--rows-label', default='-complete')
p.add_argument('--mset-post', default='build/compat2/mset-post-complete/tomokv')
a = p.parse_args()
OUT = ROOT / ('docs/compat2/controls' + a.label)
OUT.mkdir(parents=True, exist_ok=False)
results = []


def run(name, command, expected, cores='73-79'):
    with (OUT / (name + '.log')).open('w') as log:
        rc = subprocess.run(['taskset', '-c', cores, *map(str, command)], cwd=ROOT,
                            stdout=log, stderr=subprocess.STDOUT).returncode
    results.append(dict(name=name, command=list(map(str, command)), returncode=rc, expected=expected))
    (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(name, rc, flush=True)
    assert rc == expected, (name, rc, expected)


for mode in ('1s', '2s'):
    for engine in ('epoll', 'uring'):
        for arm in ('pre', 'post'):
            image = ROOT / f'build/compat2/mset-{arm}' / 'tomokv'
            if arm == 'pre':
                image = ROOT / 'build/compat2/mset-pre-v2/tomokv'
            else:
                image = ROOT / a.mset_post
            name = f'mset-{arm}-{mode}-{engine}'
            run(name, ['python3', 'tests/expire_notify.py', '--binary', image, '--output', OUT / name,
                '--mode', mode, '--engine', engine, '--cores', '64-71', '--port', '26840',
                '--synthetic-mset'], 1 if arm == 'pre' else 0)
        for case in ('autharity', 'expire_notify'):
            name = f'pad-{case}-{mode}-{engine}'
            options = ['--oracle', '/home/user/Projects/redis74/src/redis-server',
                       '--oracle-cores', '72'] if case == 'autharity' else []
            run(name, ['python3', f'tests/{case}.py', '--binary', 'build/compat2/tomokv-pad-a',
                '--output', OUT / name, '--mode', mode, '--engine', engine, '--cores', '64-71',
                '--port', '26840', *options], 1)
            if case == 'autharity':
                before = json.loads((ROOT / f'docs/compat2/rows{a.rows_label}/pre-autharity-{mode}-{engine}' /
                                     'results.json').read_text())
                pad = json.loads((OUT / name / 'results.json').read_text())
                def replies(rows):
                    # Redis COMMAND returns child metadata in hash-table order.
                    # Require the same unique probes and bytes, independent of order.
                    indexed = {(r['command'], r['kind'], tuple(r['argv']),
                                r['authenticated'], r['restricted_user']): r['target']
                               for r in rows}
                    assert len(indexed) == len(rows)
                    return indexed
                assert replies(before['rows']) == replies(pad['rows'])
                (OUT / (name + '-equivalent.json')).write_text(json.dumps(dict(
                    comparisons=len(pad['rows']), pre_pad_replies_equal=True)) + '\n')
for mode in ('1s', '2s'):
    run('ktls-pad-window-' + mode, ['build/compat2/ktls-lifetime-pad-a', mode], 1, cores='64-71')
    run('ktls-post-window-' + mode, ['build/ktls-lifetime-unit', mode], 0, cores='64-71')
hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
          for path in [ROOT / 'build/compat2/pre-source/build/tomokv', ROOT / 'build/tomokv',
                       ROOT / 'build/compat2/tomokv-pad-a', ROOT / 'build/compat2/mset-pre-v2/tomokv',
                       ROOT / a.mset_post]}
(OUT / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
