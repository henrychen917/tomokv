#!/usr/bin/env python3
"""Same command fixture and named-function scope as crlffix_scope.py, via ptrace.

Single-step only an owned, finite serverless child. Count all executed instructions
in the selected namespace, including NOPs. Skip external library calls; freeze
clock_gettime exactly as the existing GDB counter does. Check fixture exit/data.
"""
import argparse
import bisect
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
import instructions as scope
from rlfence_artifacts import instructions

OUT = scope.ROOT / 'docs/climonfix4/instructions-pc'
OUT.mkdir(parents=True, exist_ok=True)


def prepare(arm, ns):
    binary = scope.BUILD / (arm + '-' + ns) / 'probe'
    symbols = []
    for line in subprocess.check_output(['nm', '-S', '--defined-only', str(binary)], text=True).splitlines():
        words = line.split()
        if len(words) == 4 and words[2] in ('t', 'T', 'w', 'W'):
            symbols.append((int(words[0], 16), int(words[0], 16) + int(words[1], 16), words[3]))
    names = subprocess.check_output(['c++filt'], input='\n'.join(s[2] for s in symbols), text=True).splitlines()
    prefix = 'tomo::' if ns == 'normal' else 'tomo_db0::'
    ranges = sorted(s + (name,) for s, name in zip(symbols, names)
                    if prefix in name and 'CoreConcurrencyTest::' not in name)
    starts = [r[0] for r in ranges]
    begin = next(s[0] for s in symbols if s[2] == '_Z11scope_beginv')
    end = next(s[0] for s in symbols if s[2] == '_Z9scope_endv')
    rows = []
    for pc, raw, asm, _ in instructions(subprocess.check_output(['objdump', '-dw', str(binary)], text=True)):
        idx = bisect.bisect_right(starts, pc) - 1
        fn = idx + 1 if idx >= 0 and pc < ranges[idx][1] else 0
        kind = (2 if 'clock_gettime' in asm else 1) if asm.startswith('call') else 0
        rows.append((pc, len(raw), kind, fn))
    plan = binary.with_name('step-plan')
    plan.write_text(f'{begin:x} {end:x} {len(rows)} {len(ranges)}\n' + ''.join(
        f'{pc:x} {length} {kind} {fn}\n' for pc, length, kind, fn in rows))
    return binary, plan, ranges


def run(case, prepared):
    arm, ns, command, mode, batch, atomic, threshold = case
    binary, plan, ranges = prepared[arm, ns]
    label = '-'.join(map(str, case))
    dest = OUT / (label + '.json')
    temporary = scope.BUILD / (label + '-step.json')
    cmd = [str(scope.ROOT / 'build/climonfix4/commands/step-pc'), str(plan), str(temporary),
           str(binary), command, mode, str(batch), str(atomic), str(threshold)]
    with (OUT / (label + '.log')).open('w') as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
    raw = json.loads(temporary.read_text())
    pcs = raw.pop('pc_counts')
    raw['pc_trace_sha256'] = hashlib.sha256(json.dumps(pcs, separators=(',', ':')).encode()).hexdigest()
    raw['pc_trace_entries'] = len(pcs)
    functions = {}
    for n, r in zip(raw.pop('counts')[1:], ranges):
        if n: functions[r[3]] = functions.get(r[3], 0) + n
    assert functions
    row = dict(zip(('arm', 'namespace', 'command', 'mode', 'batch', 'atomic', 'threshold'), case))
    row.update(raw, total=sum(functions.values()), functions=functions,
               probe_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    scope.save(dest, row)
    temporary.unlink()
    print(label, row['total'], flush=True)
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--arms', default='pre,post')
    p.add_argument('--smoke', action='store_true')
    p.add_argument('--kind',choices=('commands','exec','local'),default='commands')
    args = p.parse_args()
    arms = args.arms.split(',')
    prepared = {(arm, ns): prepare(arm, ns) for arm in arms for ns in ('normal', 'db0')}
    cases = [(arm, ns, command, mode, batch, atomic, -1) for arm in arms
             for ns in ('normal', 'db0') for command in ('GET', 'SET', 'INCR', 'MGET', 'MSET')
             for mode in ('1s', '2s') for batch in (1, 32)
             for atomic in ((0, 1) if command == 'MSET' else (1,))]
    if args.kind == 'exec':
        cases = [(a,n,c,m,b,v,-1) for a in arms for n in ('normal','db0')
                 for c in ('EXEC-single','EXEC-cross') for m in ('1s','2s')
                 for b in (1,2,4) for v in (0,1)]
    if args.kind == 'local':
        cases = [(a,n,'READLOCAL-GET','1s',b,1,-1) for a in arms
                 for n in ('normal','db0') for b in (1,32)]
    if args.smoke: cases = [c for c in cases if c[2:6] == ('GET', '1s', 1, 1)]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(lambda case: run(case, prepared), cases))
    scope.save(OUT / (args.kind+'-results-' + args.arms + '.json'), rows)
    for arm in arms:
        scope.save(OUT/(args.kind+'-results-'+arm+'.json'),[r for r in rows if r['arm']==arm])
    if len(arms) == 2:
        pairs = []
        for row in rows:
            if row['arm'] != arms[1]: continue
            keys = ('namespace', 'command', 'mode', 'batch', 'atomic', 'threshold')
            old = next(r for r in rows if r['arm'] == arms[0] and all(r[k] == row[k] for k in keys))
            pairs.append({k: row[k] for k in keys} | dict(pre=old['total'], post=row['total'],
                         delta=row['total'] - old['total'], functions_equal=row['functions'] == old['functions']))
        scope.save(OUT / (args.kind+'-comparison.json'), pairs)


if __name__ == '__main__':
    main()
