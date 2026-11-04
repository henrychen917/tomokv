#!/usr/bin/env python3
"""parkwake: compile-only GCC IPA unit sizes and per-function bodies; no server, no workload.

initial                    compile every object that carries a large-unit-insns pin, PRE and POST,
                           with -fdump-ipa-inline; record GCC's "Starting with size" (the initial
                           IPA unit size the inline-unit-growth=0 budget is measured against). The
                           size-compensated POST budget is PRE budget + (POST unit - PRE unit), the
                           rule earlier lanes used (tools/wave15_budgets.py).
scan OBJECT BUDGET...      compile the POST object at each budget (-g0) and compare every function
                           body, canonicalized by tools/ccfix_audit.py's normalizer, with the PRE
                           object at PRE's own budget. Prints the differing functions.
select                     scan every pinned object over a window around its compensated value and
                           write docs/parkwake/budgets/selected.json.
"""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
PRE = ROOT / 'build/parkwake/pre-source'
OUT = ROOT / 'build/parkwake/budgets'
DOC = ROOT / 'docs/parkwake/budgets'


def budgets(makefile):
    return {m[1]: int(m[2]) for m in re.finditer(
        r'^\$\(BUILD_ROOT\)/([^:\n]+):[^\n]*large-unit-insns=(\d+)', makefile.read_text(), re.M)}


def recipe(source, obj):
    text = subprocess.check_output(['make', '-B', '-n', 'build/' + obj], cwd=source, text=True)
    return shlex.split(next(s for s in reversed(text.splitlines())
                            if s.startswith('g++ ') and s.endswith(' -o build/' + obj)))


def bodies(path):
    import ccfix_audit  # noqa: F401  (installs the canonical normalizer on lbstall_artifacts.Elf)
    import lbstall_artifacts as audit
    elf = audit.Elf(path)
    functions = elf.functions()
    names = sorted(functions)
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    return {label: hashlib.sha256(repr(elf.canonical(functions[s])).encode()).hexdigest()
            for s, label in zip(names, labels)}


def compile_unit(job):
    arm, obj, value = job['arm'], job['object'], job.get('budget')
    source = PRE if arm == 'pre' else ROOT
    tag = obj.replace('/', '_') + '-' + arm + ('' if value is None else '-' + str(value))
    receipt = OUT / (tag + '.json')
    if receipt.exists():
        return json.loads(receipt.read_text())
    cmd = ['-g0' if x == '-g' else x for x in recipe(source, obj)]
    if value is not None:
        cmd = ['large-unit-insns=' + str(value) if x.startswith('large-unit-insns=') else x for x in cmd]
    dest = OUT / (tag + '.o')
    cmd[cmd.index('-o') + 1] = str(dest)
    cmd += ['-fdump-ipa-inline', '-dumpbase', str(OUT / tag)]
    with (OUT / (tag + '.log')).open('w') as log:
        subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    dump, = OUT.glob(tag + '.[0-9]*i.inline')
    with dump.open() as f:
        unit = next(int(m[1]) for line in f if (m := re.search(r'Starting with size (\d+)', line)))
    dump.unlink()
    result = dict(job, unit=unit, command=cmd)
    if value is not None:
        result['bodies'] = bodies(dest)
        result['code_digest'] = hashlib.sha256(json.dumps(result['bodies'], sort_keys=True).encode()).hexdigest()
    dest.unlink()
    receipt.write_text(json.dumps(result, indent=2) + '\n')
    print('compiled', tag, 'IPA', unit, flush=True)
    return result


def scan(obj, values, pool):
    old = budgets(PRE / 'Makefile')
    jobs = [dict(arm='pre', object=obj, budget=old[obj])] + \
           [dict(arm='post', object=obj, budget=v) for v in values]
    rows = list(pool.map(compile_unit, jobs))
    pre, trials = rows[0], rows[1:]
    out = []
    for row in trials:
        names = sorted(set(pre['bodies']) | set(row['bodies']))
        changed = [n for n in names if pre['bodies'].get(n) != row['bodies'].get(n)]
        out.append(dict(object=obj, budget=row['budget'], unit=row['unit'], code_digest=row['code_digest'],
                        changed=changed))
    return out


def main():
    # parkwake lane: CPUs 32-63 only.
    assert os.sched_getaffinity(0) <= set(range(32, 64)), 'parkwake compiles on CPUs 32-63 only'
    os.environ['LC_ALL'] = 'C'
    OUT.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    phase = sys.argv[1]
    old, new = budgets(PRE / 'Makefile'), budgets(ROOT / 'Makefile')
    workers = int(os.getenv('PARKWAKE_BUILD_WORKERS', '15'))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        if phase == 'initial':
            jobs = [dict(arm=arm, object=obj) for obj in sorted(old) for arm in ('pre', 'post')]
            rows = list(pool.map(compile_unit, jobs))
            table = []
            for obj in sorted(old):
                pre = next(r for r in rows if r['object'] == obj and r['arm'] == 'pre')
                post = next(r for r in rows if r['object'] == obj and r['arm'] == 'post')
                table.append(dict(object=obj, pre_budget=old[obj], post_budget=new.get(obj),
                                  pre_unit=pre['unit'], post_unit=post['unit'],
                                  delta=post['unit'] - pre['unit'],
                                  compensated=old[obj] + post['unit'] - pre['unit']))
            (DOC / 'initial.json').write_text(json.dumps(table, indent=2) + '\n')
            for row in table:
                if row['delta']:
                    print(row['object'], 'PRE', row['pre_unit'], 'POST', row['post_unit'],
                          'delta', row['delta'], 'budget', row['pre_budget'], '->', row['compensated'])
        elif phase == 'scan':
            for row in scan(sys.argv[2], [int(v) for v in sys.argv[3:]], pool):
                print(row['object'], row['budget'], 'IPA', row['unit'], len(row['changed']), 'changed', flush=True)
                for name in row['changed']:
                    print('    ', name[:200])
        elif phase == 'select':
            table = json.loads((DOC / 'initial.json').read_text())
            span = int(os.getenv('PARKWAKE_SCAN_SPAN', '24'))
            step = int(os.getenv('PARKWAKE_SCAN_STEP', '8'))
            choices = []
            for row in table:
                if not row['delta']:
                    continue
                center = row['compensated']
                values = sorted({center + d for d in range(-span, span + 1, step)} | {row['pre_budget']})
                trials = scan(row['object'], values, pool)
                best = min(trials, key=lambda t: (len(t['changed']), abs(t['budget'] - center)))
                choices.append(dict(object=row['object'], pre_budget=row['pre_budget'],
                                    compensated=center, budget=best['budget'],
                                    changed=best['changed'],
                                    trials=[{k: t[k] for k in ('budget', 'unit', 'code_digest')} |
                                            dict(changed=len(t['changed'])) for t in trials]))
                print(row['object'], row['pre_budget'], '->', best['budget'], len(best['changed']),
                      'changed', flush=True)
            (DOC / 'selected.json').write_text(json.dumps(choices, indent=2) + '\n')
        else:
            raise SystemExit('usage: parkwake_budgets.py initial | scan OBJECT BUDGET... | select')


if __name__ == '__main__':
    main()
