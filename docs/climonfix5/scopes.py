#!/usr/bin/env python3
"""Finite production command scopes, including callbacks through the embedded Lua VM.

No server, clock rate, performance counters or throughput measurement. Only
the selected production namespace is counted; all local code is traversed so
Lua's indirect redis.call callbacks cannot escape the scope.
"""
import argparse
import bisect
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'build/climonfix5/scopes'
DOC = ROOT / 'docs/climonfix5/scopes'
sys.path.insert(0, str(ROOT / 'tools'))
from rlfence_artifacts import instructions

def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def build(arm, ns, kind):
    source = ROOT if arm == 'post' else ROOT / ('build/climonfix5/' + arm + '-source')
    objects = source / 'build'
    dest = BUILD / (arm + '-' + ns + '-' + kind)
    dest.mkdir(parents=True, exist_ok=True)
    recipe = subprocess.check_output(['make', '-C', str(source), 'BUILD_ROOT=' + str(objects),
        '-n', '-W', str(objects / 'src/main.o'), 'all'], text=True)
    link = shlex.split(next(s for s in recipe.splitlines() if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
    fixture = {'session': 'climonfix5_scope.cc', 'hot': 'wave9_scope.cc', 'parse': 'climonfix4_scope.cc'}[kind]
    command = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread', '-DTOMO_JEMALLOC', '-I' + str(source)]
    if ns == 'db0': command += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
    command += ['-c', str(ROOT / 'tests' / fixture), '-o', str(dest / 'probe.o')]
    rename = ['objcopy', '--redefine-sym', 'main=scope_original_main', str(objects / 'db0/src/main.o'), str(dest / 'original-main.o')]
    link = [str(dest / 'original-main.o') if s == str(objects / 'db0/src/main.o') else s for s in link]
    link += [str(dest / 'probe.o')]
    link[link.index('-o') + 1] = str(dest / 'probe')
    with (dest / 'build.log').open('w') as log:
        for cmd in (command, rename, link):
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    save(DOC / (dest.name + '-build.json'), dict(compile=command, rename=rename, link=link, sha256=sha(dest / 'probe')))
    print('BUILT', dest.name, flush=True)

def prepare(arm, ns, kind):
    binary = BUILD / (arm + '-' + ns + '-' + kind) / 'probe'
    symbols = []
    for line in subprocess.check_output(['nm', '-S', '--defined-only', str(binary)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[2] in ('t', 'T', 'w', 'W'):
            symbols.append((int(fields[0], 16), int(fields[0], 16) + int(fields[1], 16), fields[3]))
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
        call = (2 if 'clock_gettime' in asm else 1) if asm.startswith('call') else 0
        rows.append((pc, len(raw), call, fn))
    plan = binary.with_name('step-plan')
    plan.write_text(f'{begin:x} {end:x} {len(rows)} {len(ranges)}\n' + ''.join(
        f'{pc:x} {length} {call} {fn}\n' for pc, length, call, fn in rows))
    return binary, plan, ranges

def run(case, prepared, kind):
    arm, ns, command, mode, batch, atomic = case
    binary, plan, ranges = prepared[arm, ns]
    label = '-'.join(map(str, (kind,) + case))
    dest = DOC / (label + '.json')
    if dest.exists() and json.loads(dest.read_text())['probe_sha256'] == sha(binary):
        return json.loads(dest.read_text())
    temporary = BUILD / (label + '-steps.json')
    cmd = [str(BUILD / 'step'), str(plan), str(temporary), str(binary), command, mode, str(batch), str(atomic), '-1']
    with (DOC / (label + '.log')).open('w') as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    raw = json.loads(temporary.read_text())
    pcs = raw.pop('pc_counts')
    raw['pc_trace_sha256'] = hashlib.sha256(json.dumps(pcs, separators=(',', ':')).encode()).hexdigest()
    raw['pc_trace_entries'] = len(pcs)
    functions = {}
    for n, r in zip(raw.pop('counts')[1:], ranges):
        if n: functions[r[3]] = functions.get(r[3], 0) + n
    assert functions
    row = dict(zip(('arm', 'namespace', 'command', 'mode', 'batch', 'atomic'), case))
    row.update(raw, scope=kind, total=sum(functions.values()), functions=functions, probe_sha256=sha(binary))
    save(dest, row)
    temporary.unlink()
    print(label, row['total'], flush=True)
    return row

def main():
    os.sched_setaffinity(0, set(range(16, 32)))
    parser = argparse.ArgumentParser()
    parser.add_argument('--arms', default='pre,c4,post')
    parser.add_argument('--kind', choices=('session', 'hot', 'parse'), default='session')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--command')
    parser.add_argument('--batch', type=int)
    parser.add_argument('--namespace', choices=('normal', 'db0'))
    parser.add_argument('--mode', choices=('1s', '2s'))
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True);DOC.mkdir(parents=True, exist_ok=True)
    arms = args.arms.split(',')
    namespaces = (args.namespace,) if args.namespace else ('normal', 'db0')
    if args.build:
        for arm in arms:
            for ns in namespaces: build(arm, ns, args.kind)
        return
    subprocess.run(['gcc', '-O2', str(ROOT / 'docs/climonfix5/step.c'), '-o', str(BUILD / 'step')], check=True)
    prepared = {(a, n): prepare(a, n, args.kind) for a in arms for n in namespaces}
    commands = ['GET', 'SET', 'INCR', 'MGET', 'MSET']
    if args.kind == 'hot': commands += ['READLOCAL-GET']
    if args.kind == 'session':
        commands = ['PING', 'WATCH'] + [v + '-' + s for v in ('EVAL', 'EVAL-header', 'EVALSHA', 'EVALSHA-header', 'FCALL', 'EXEC', 'EXEC-abort') for s in ('single', 'cross')]
    if args.command: commands = [args.command]
    cases = [(a, n, c, m, b, atomic) for a in arms for n in namespaces for c in commands
             for m in ((args.mode,) if args.mode else (('1s',) if c == 'READLOCAL-GET' else ('1s', '2s')))
             for b in ((args.batch,) if args.batch else (1, 32))
             for atomic in ((0,) if args.kind == 'parse' else ((0, 1) if c == 'MSET' else (1,)))]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(lambda c: run(c, prepared, args.kind), cases))
    save(DOC / (args.kind + '-results-' + args.arms + '.json'), rows)

if __name__ == '__main__':
    main()
