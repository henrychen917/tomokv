#!/usr/bin/env python3
"""Build/run ccfix2 serverless witnesses; never starts a server or load generator."""
import argparse
import json
from pathlib import Path
import resource
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/ccfix2'
BUILD = ROOT / 'build/ccfix2'
CXX = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native',
       '-pthread', '-DTOMO_JEMALLOC']
LIBS = ['-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm']


def objects(arm, db0=False):
    var = 'DB0_OBJ' if db0 else 'OBJ'
    root = BUILD / arm
    return subprocess.check_output(['make', '-s', '--no-print-directory',
        f'BUILD_ROOT={root}', '--eval', f'ccfix2-objects:;@echo $({var})',
        'ccfix2-objects'], cwd=ROOT, text=True).split()


def compile_test(name, source, obj, includes=None, defines=None):
    binary = BUILD / name
    command = CXX + (defines or []) + (includes or ['-I.']) + [str(source)] + obj + \
              ['-o', str(binary)] + LIBS
    with (BUILD / (name + '.build.log')).open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    return binary


def run(name, binary, args=(), fails=False):
    cpus = '16-23' if name.startswith('atomic-unit') else '24'
    command = ['taskset', '-c', cpus, str(binary), *args]
    result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    (OUT / (name + '.log')).write_text(result.stdout + f'\nexit={result.returncode}\n')
    assert (result.returncode != 0) == fails, (name, result.returncode, result.stdout)
    print(name, 'expected failure' if fails else 'PASS', flush=True)
    return result.stdout


def units():
    core = [o for o in objects('POST') if not o.endswith('/main.o')]
    unit = compile_test('unit', ROOT / 'tests/ccfix_unit.cc', core)
    run('unit', unit)
    broken = [str(BUILD / 'POST/src/cmd/t_server.o') if o.endswith('/t_server.o') else o
              for o in objects('BASE') if not o.endswith('/main.o')]
    control = compile_test('unit-no-hook', ROOT / 'tests/ccfix_unit.cc', broken)
    run('unit-no-hook', control, fails=True)
    owner_core = [o for o in core if not o.endswith('/xshard.o')]
    atomic = compile_test('atomic-unit', ROOT / 'tests/ccfix2_atomic_unit.cc', owner_core)
    for mode in ('1s', '2s'):
        run('atomic-unit-' + mode, atomic, ['armed', mode])
    run('atomic-unit-no-arm', atomic, ['no-arm', '2s'], fails=True)
    control_root = BUILD / 'no-scatter-hook'
    (control_root / 'src/cmd').mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'src/cmd/xshard.cc', control_root / 'src/cmd/xshard.cc')
    source = (ROOT / 'src/cmd/scatter_engine.inc').read_text()
    start = source.index('            // The tracked lookup bypasses find_notify.')
    stop = source.index('            if (read_lookup)', start)
    source = source[:start] + source[stop:]
    (control_root / 'src/cmd/scatter_engine.inc').write_text(source)
    negative = compile_test('atomic-unit-no-scatter-hook', ROOT / 'tests/ccfix2_atomic_unit.cc',
                            owner_core, ['-I' + str(control_root), '-Isrc/cmd', '-I.'])
    run('atomic-unit-no-scatter-hook', negative, ['armed', '2s'], fails=True)


def instructions():
    rows = {}
    for db0 in (False, True):
        suffix = '-db0' if db0 else ''
        for arm in ('PRE', 'BASE', 'POST'):
            headers = {'PRE': BUILD / 'pre-src', 'BASE': BUILD / 'base-src', 'POST': ROOT}[arm]
            obj = [o for o in objects(arm, db0) if not o.endswith('/main.o')]
            if db0:
                # The DB0 runtime retains namespace bridges into the normal core.
                obj += [o for o in objects(arm) if not o.endswith('/main.o')]
            defines = ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else []
            binary = compile_test('instr-' + arm + suffix, ROOT / 'tests/ccfix_instr.cc', obj,
                                  ['-I' + str(headers), '-I.'], defines)
            name = 'instructions-' + arm + suffix
            rows[arm + suffix] = run(name, binary)
            (OUT / (name + '.csv')).write_text(rows[arm + suffix])
    (OUT / 'instruction-comparison.json').write_text(json.dumps(rows, indent=2) + '\n')
    for suffix in ('', '-db0'):
        assert rows['PRE' + suffix] == rows['BASE' + suffix] == rows['POST' + suffix], rows
    print('PASS all five 100,000-call intervals byte-equal in both namespaces', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proof', choices=('units', 'instructions'))
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    OUT.mkdir(parents=True, exist_ok=True)
    (units if args.proof == 'units' else instructions)()
