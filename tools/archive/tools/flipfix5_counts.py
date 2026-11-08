#!/usr/bin/env python3
"""flipfix5 serverless instruction scopes, using the established production fixture.

Two probes, each linked against an arm's production objects (fixture COMDATs last, so production
definitions keep precedence) and single-stepped by tools/crlffix_step.c, which owns its finite
child: no server, listener, debugger attach, core dump, throughput or timing measurement.

  command  tests/txnorder_command_scope.cc: GET/SET/INCR/MGET/MSET, batch 1/32, both modes,
           both namespaces, atomic 0/1 (the flushfix2 command-scope grid).
  control  tests/flipfix5_control_scope.cc: one ExLoopT<false>/IoLoop FLIP control pass in a
           selected stage state, through the linked production symbol.

Counts include executed NOPs in named TomoKV bodies and exclude library callees and fixture glue.
"""
import argparse
import bisect
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

from rlfence_artifacts import instructions

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/flipfix5/counts'
OUT = ROOT / 'docs/flipfix5/counts'
PRE_COMMIT = 'e2b237926'
ARMS = {'pre': (ROOT / 'build/flipfix5/pre-source', ROOT / 'build/flipfix5/pre-source/build'),
        'post': (ROOT, ROOT / 'build')}
PROBES = {'command': 'tests/txnorder_command_scope.cc', 'control': 'tests/flipfix5_control_scope.cc'}
CONTROL_CELLS = ('ex-idle', 'ex-exdrain-owed', 'ex-exdrain-acked', 'ex-exinstall-owed',
                 'ex-exinstall-acked', 'io-idle', 'io-iodrain-owed', 'io-iodrain-acked',
                 'io-roleready-owed', 'io-roleready-acked')
CPUS = '16-31'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def pre_source():
    source, objects = ARMS['pre']
    if (objects / 'tomokv').exists():
        return
    source.mkdir(parents=True, exist_ok=True)
    archive = subprocess.check_output(['git', 'archive', PRE_COMMIT, 'Makefile', 'src', 'third_party',
                                       'tools/assert_map.py'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        files.extractall(source, filter='data')
    with (BUILD / 'pre-production-build.log').open('w') as log:
        subprocess.run(['taskset', '-c', CPUS, 'make', '-C', str(source), '-j16', 'all'],
                       stdout=log, stderr=subprocess.STDOUT, check=True)


def build(arm, ns, probe):
    source, objects = ARMS[arm]
    dest = BUILD / f'{probe}-{arm}-{ns}'
    dest.mkdir(parents=True, exist_ok=True)
    recipe = subprocess.check_output(['make', '-C', str(source), 'BUILD_ROOT=' + str(objects),
                                      '-n', '-W', str(objects / 'src/main.o'), 'all'], text=True)
    link = shlex.split(next(line for line in recipe.splitlines()
                            if ' -o ' + str(objects / 'tomokv') + ' ' in line))
    flags = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread', '-DTOMO_JEMALLOC',
             '-I' + str(source)]
    if ns == 'db0':
        flags += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
    # The probe source is the POST tree's file for both arms; it names only APIs PRE has.
    compile_cmd = flags + ['-c', str(ROOT / PROBES[probe]), '-o', str(dest / 'probe.o')]
    renamed_main = dest / 'original-main.o'
    rename_cmd = ['objcopy', '--redefine-sym', 'main=execfair_original_main',
                  str(objects / 'db0/src/main.o'), str(renamed_main)]
    link = [str(renamed_main) if arg == str(objects / 'db0/src/main.o') else arg for arg in link]
    link += [str(dest / 'probe.o')]
    link[link.index('-o') + 1] = str(dest / 'probe')
    with (dest / 'build.log').open('w') as log:
        for cmd in (compile_cmd, rename_cmd, link):
            subprocess.run(['taskset', '-c', CPUS] + cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    receipt = dict(compile=compile_cmd, rename=rename_cmd, link=link,
                   sha256=hashlib.sha256((dest / 'probe').read_bytes()).hexdigest())
    save(OUT / f'{probe}-{arm}-{ns}-build.json', receipt)
    return receipt


def prepare(arm, ns, probe):
    binary = BUILD / f'{probe}-{arm}-{ns}' / 'probe'
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
    probe, arm, ns, argv = case
    binary, plan, ranges = prepared[probe, arm, ns]
    label = '-'.join([probe, arm, ns] + [str(a) for a in argv])
    raw_file = BUILD / (label + '.json')
    cmd = ['taskset', '-c', CPUS, str(BUILD / 'step'), str(plan), str(raw_file), str(binary)] + \
        [str(a) for a in argv]
    with (BUILD / (label + '.log')).open('w') as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    raw = json.loads(raw_file.read_text())
    functions = {}
    for n, r in zip(raw.pop('counts')[1:], ranges):
        if n:
            functions[r[3]] = functions.get(r[3], 0) + n
    assert functions, label
    row = dict(probe=probe, arm=arm, namespace=ns, argv=[str(a) for a in argv])
    row.update(raw, total=sum(functions.values()), functions=functions,
               probe_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    save(OUT / (label + '.json'), row)
    raw_file.unlink()
    print(label, row['total'], flush=True)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--arms', default='pre,post')
    p.add_argument('--probes', default='command,control')
    p.add_argument('--build-only', action='store_true')
    p.add_argument('--trace-only', action='store_true')
    p.add_argument('--commands', default='GET,SET,INCR,MGET,MSET')
    p.add_argument('--jobs', type=int, default=8)
    args = p.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    arms = args.arms.split(',')
    probes = args.probes.split(',')
    if not args.trace_only:
        subprocess.run(['gcc', '-O2', str(ROOT / 'tools/crlffix_step.c'), '-o', str(BUILD / 'step')], check=True)
        if 'pre' in arms:
            pre_source()
        for probe in probes:
            for arm in arms:
                for ns in ('normal', 'db0'):
                    build(arm, ns, probe)
    if args.build_only:
        return
    prepared = {(probe, arm, ns): prepare(arm, ns, probe)
                for probe in probes for arm in arms for ns in ('normal', 'db0')}
    cases = []
    for probe in probes:
        for arm in arms:
            for ns in ('normal', 'db0'):
                if probe == 'command':
                    cases += [(probe, arm, ns, (command, mode, batch, atomic, -1))
                              for command in args.commands.split(',') for mode in ('1s', '2s')
                              for batch in (1, 32) for atomic in (0, 1)]
                else:
                    cases += [(probe, arm, ns, (cell,)) for cell in CONTROL_CELLS]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        rows = list(pool.map(lambda case: run(case, prepared), cases))
    save(OUT / ('results-' + args.arms + '-' + args.probes + '.json'), rows)
    if {'pre', 'post'}.issubset(arms):
        pairs = []
        for r in rows:
            if r['arm'] != 'post':
                continue
            old = next(o for o in rows if o['arm'] == 'pre' and o['probe'] == r['probe'] and
                       o['namespace'] == r['namespace'] and o['argv'] == r['argv'])
            pairs.append(dict(probe=r['probe'], namespace=r['namespace'], argv=r['argv'],
                              pre=old['total'], post=r['total'], delta=r['total'] - old['total'],
                              functions_equal=r['functions'] == old['functions']))
        save(OUT / 'comparison.json', pairs)


if __name__ == '__main__':
    main()
