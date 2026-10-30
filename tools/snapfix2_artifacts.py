#!/usr/bin/env python3
"""Compile/identity/serverless instruction evidence for snapfix2; no performance workloads.

Reuse snapfix's object normalizer and instruction tracer, with this lane's frozen roots and
CPUs. The GDB tracer launches only a serverless fixture, never attaches to a server.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

import snapfix_identity as identity
from lbstall_artifacts import HOT

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/snapfix2'
OUT = ROOT / 'docs/snapfix2'
ARMS = {'pre': (BUILD / 'pre-source', BUILD / 'pre'),
        'base': (BUILD / 'base-source', BUILD / 'base'), 'post': (ROOT, ROOT / 'build')}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def recipes(arm):
    source, build = ARMS[arm]
    text = subprocess.check_output(['make', '-n', '-W', 'Makefile',
                                    'BUILD_ROOT=' + str(build), 'all'], cwd=source, text=True)
    compile_cmds, link = {}, None
    for line in text.replace('\\\n', ' ').splitlines():
        if not line.startswith('g++ '):
            continue
        cmd = shlex.split(line)
        if '-c' in cmd:
            compile_cmds[str(Path(cmd[cmd.index('-o') + 1]).relative_to(build))] = cmd
        elif str(build / 'tomokv') in cmd:
            link = cmd
    assert link
    return compile_cmds, link


def compare(paths):
    old_path, new_path, rename = paths
    old = identity.bodies(old_path, rename)
    new = identity.bodies(new_path)
    changed = sorted(n for n in old.keys() & new.keys() if old[n] != new[n])
    old_plain = identity.bodies(old_path, rename, False) if changed else {}
    new_plain = identity.bodies(new_path, False, False) if changed else {}
    padding = [n for n in changed if old_plain[n] == new_plain[n]]
    changed = [n for n in changed if n not in padding]
    names = subprocess.check_output(['c++filt'], input='\n'.join(changed), text=True).splitlines()
    return dict(functions=len(new), equal=len(old.keys() & new.keys()) - len(changed) - len(padding),
                changed=names, symbols=changed, padding=padding,
                hot=[n for n in names if HOT.search(n)],
                added=sorted(new.keys() - old.keys()), removed=sorted(old.keys() - new.keys()))


def identities(old_arm):
    old_root, new_root = ARMS[old_arm][1], ARMS['post'][1]
    _, link = recipes('post')
    units = [str(Path(x).relative_to(new_root)) for x in link if x.endswith('.o')]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = dict(zip(units, pool.map(compare, [(old_root / u, new_root / u, old_arm == 'pre')
                                                   for u in units])))
    save(OUT / 'identity' / (old_arm + '-post.json'), rows)
    for unit, row in rows.items():
        if row['changed'] or row['added'] or row['removed']:
            print(unit, 'changed', len(row['changed']), 'hot', len(row['hot']),
                  'added', len(row['added']), 'removed', len(row['removed']), flush=True)


def trial(item):
    arm, unit, value = item
    source, objects = ARMS[arm]
    cmd = recipes(arm)[0][unit]
    base_budget = next((int(x.split('=')[1]) for x in cmd if x.startswith('large-unit-insns=')), 10000)
    stem = f'{arm}-{unit.replace("/", "_")}-{value}'
    dest = BUILD / 'budgets' / (stem + '.o')
    receipt = OUT / 'budgets' / (stem + '.json')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dump = dest.with_suffix('.inline')
    if value is not None:
        if any(x.startswith('large-unit-insns=') for x in cmd):
            cmd = [f'large-unit-insns={value}' if x.startswith('large-unit-insns=') else x for x in cmd]
        else:
            cmd += ['--param', f'large-unit-insns={value}']
    cmd[cmd.index('-o') + 1] = str(dest)
    cmd = ['taskset', '-c', '0-15', *cmd, '-g0', f'-fdump-ipa-inline={dump}']
    with dest.with_suffix('.log').open('w') as log:
        subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    text = dump.read_text()
    initial = int(re.search(r'Starting with size (\d+)', text)[1])
    dump.unlink()
    row = compare((ARMS['base'][1] / unit, dest, False))
    row.update(arm=arm, unit=unit, budget=base_budget if value is None else value,
               initial=initial, command=cmd, sha256=sha(dest))
    save(receipt, row)
    print(stem, 'IPA', initial, 'changed', len(row['changed']), 'hot', len(row['hot']), flush=True)
    return row


def scopes(arms, trace_only=False):
    import snapfix_scope as s
    s.OUT, s.BUILD, s.CPUS, s.ARMS = OUT / 'instructions', BUILD / 'commands', '8-15', ARMS
    s.OUT.mkdir(parents=True, exist_ok=True)
    s.BUILD.mkdir(parents=True, exist_ok=True)
    if not trace_only:
        for arm in arms:
            for ns in ('normal', 'db0'):
                s.build(arm, ns)
    cases = [(arm, ns, cmd, mode, batch, atomic, -1) for arm in arms
             for ns in ('normal', 'db0') for cmd in ('GET', 'SET', 'INCR', 'MGET', 'MSET')
             for mode in ('1s', '2s') for batch in (1, 32)
             for atomic in ((0, 1) if cmd == 'MSET' else (1,))]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(s.trace, cases))
    save(s.OUT / 'results.json', rows)
    keys = ('namespace', 'command', 'mode', 'batch', 'atomic', 'threshold')
    pairs = []
    for new in [r for r in rows if r['arm'] == 'post']:
        for arm in ('pre', 'base'):
            old = next(r for r in rows if r['arm'] == arm and all(r[k] == new[k] for k in keys))
            pairs.append({k: new[k] for k in keys} | dict(reference=arm, pre=old['total'],
                         post=new['total'], delta=new['total'] - old['total'],
                         functions_equal=new['functions'] == old['functions']))
    save(s.OUT / 'comparison.json', pairs)
    # The tracer records SHA-256 and last lines before these large transient logs are removed.
    for path in s.BUILD.glob('*.log'):
        path.unlink()
    assert all(r['delta'] == 0 and r['functions_equal'] for r in pairs), 'command instruction regression'


def freshness():
    """Build the gate's actual production-unit inventory, then query every target.
    The aggregate mdbqsbr target is phony; query its two real recursive all targets."""
    source = (ROOT / 'tests/gate.sh').read_text()
    body = source.split('job_production_units(){', 1)[1].split('# -q verifies', 1)[0]
    units = sorted(set(re.findall(r'build/[A-Za-z0-9_-]+', body)))
    assert len(units) == 45, ('review the gate unit inventory', units)
    commands, checks = [], []

    def build(command, name):
        command = ['taskset', '-c', '0-15', *command]
        log = OUT / ('freshness-' + name + '.log')
        with log.open('w') as f:
            result = subprocess.run(command, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
        commands.append(dict(command=command, exit=result.returncode, log=str(log), sha256=sha(log)))
        assert result.returncode == 0, (command, log)

    build(['make', '-j16', 'all', *units, 'mdbqsbr-live-arms'], 'production')
    build(['make', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk', '-j16',
           'build/blockfix-cost'], 'blockfix')

    def query(command, target, cwd=ROOT, binary=None):
        command = ['taskset', '-c', '0-15', *command]
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        row = dict(target=target, command=command, cwd=str(cwd), exit=result.returncode,
                   stdout=result.stdout, stderr=result.stderr)
        if binary:
            row.update(binary=str(binary), sha256=sha(binary))
        checks.append(row)

    for target in ['all', *units]:
        query(['make', '-q', target], target, binary=ROOT / ('build/tomokv' if target == 'all' else target))
    recipe = subprocess.check_output(['make', '-n', 'mdbqsbr-live-arms'], cwd=ROOT, text=True)
    recursive = [shlex.split(line) for line in recipe.splitlines()
                 if line.startswith('make BUILD_ROOT=build/mdbqsbr2-')]
    assert len(recursive) == 2, recipe
    for cmd in recursive:
        build_root = next(x.split('=', 1)[1] for x in cmd if x.startswith('BUILD_ROOT='))
        query([*cmd[:-1], '-q', 'all'], build_root + '/all', binary=ROOT / build_root / 'tomokv')
    query(['make', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk', '-q',
           'build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256'], 'blockfix-cost',
          binary=ROOT / 'build/blockfix-cost')
    for arm in ['pre', 'base']:
        tree, objects = ARMS[arm]
        query(['make', 'BUILD_ROOT=' + str(objects), '-q', 'all'], arm + '/all', tree,
              objects / 'tomokv')
    save(OUT / 'freshness.json', dict(builds=commands, queries=checks,
         phony='mdbqsbr-live-arms built; its two real recursive all targets queried with the same flags'))
    assert all(r['exit'] == 0 for r in checks), 'stale production target; see freshness.json'
    print(f'{len(checks)} make -q queries passed', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['identity', 'survey', 'trial', 'scope', 'freshness'])
    p.add_argument('--arms', default='pre,base,post')
    p.add_argument('--reference', default='base', choices=['pre', 'base'])
    p.add_argument('--unit')
    p.add_argument('--trace-only', action='store_true')
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('values', nargs='*', type=int)
    a = p.parse_args()
    if a.action == 'identity':
        identities(a.reference)
    elif a.action == 'scope':
        scopes(a.arms.split(','), a.trace_only)
    elif a.action == 'freshness':
        freshness()
    else:
        if a.unit:
            units = [a.unit]
        else:
            rows = json.loads((OUT / 'identity/base-post.json').read_text())
            units = [u for u, r in rows.items() if r['changed'] or r['added'] or r['removed']]
        items = [(arm, u, v) for arm in a.arms.split(',') for u in units for v in (a.values or [None])]
        with concurrent.futures.ThreadPoolExecutor(a.jobs) as pool:
            list(pool.map(trial, items))


if __name__ == '__main__':
    main()
