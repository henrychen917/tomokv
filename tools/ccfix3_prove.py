#!/usr/bin/env python3
"""Build/run ccfix3 serverless witnesses on CPUs 112-127; never starts a server or load generator."""
import argparse
import json
from pathlib import Path
import resource
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/ccfix3'
BUILD = ROOT / 'build/ccfix3'
CXX = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native',
       '-pthread', '-DTOMO_JEMALLOC']
LIBS = ['-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm']


def objects(arm, db0=False):
    var = 'DB0_OBJ' if db0 else 'OBJ'
    root = BUILD / arm
    return subprocess.check_output(['make', '-s', '--no-print-directory',
        f'BUILD_ROOT={root}', '--eval', f'ccfix3-objects:;@echo $({var})',
        'ccfix3-objects'], cwd=ROOT, text=True).split()


def compile_test(name, source, obj, includes=None, defines=None):
    binary = BUILD / name
    command = CXX + (defines or []) + (includes or ['-I.']) + [str(source)] + obj + \
              ['-o', str(binary)] + LIBS
    with (BUILD / (name + '.build.log')).open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    return binary


def run(name, binary, args=(), fails=False):
    cpus = '112-119' if name.startswith('atomic-unit') else '112'
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
    for arm, headers in [('PRE', BUILD / 'pre-src'), ('POST', ROOT)]:
        flags = compile_test('flags-' + arm, ROOT / 'tests/ccfix_unit.cc', [],
                             ['-I' + str(headers)], ['-DTOMO_CCFIX_FLAGS_ONLY'])
        run('flags-' + arm, flags, fails=(arm == 'PRE'))
    owner_core = [o for o in core if not o.endswith('/xshard.o')]
    atomic = compile_test('atomic-unit', ROOT / 'tests/ccfix2_atomic_unit.cc', owner_core)
    for mode in ('1s', '2s'):
        run('atomic-unit-' + mode, atomic, ['armed', mode])
    run('atomic-unit-no-arm', atomic, ['no-arm', '2s'], fails=True)


def instructions():
    rows = {}
    for db0 in (False, True):
        suffix = '-db0' if db0 else ''
        for arm in ('PRE', 'POST'):
            headers = {'PRE': BUILD / 'pre-src', 'POST': ROOT}[arm]
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
        assert rows['PRE' + suffix] == rows['POST' + suffix], rows
    print('PASS all five 100,000-call intervals byte-equal in both namespaces', flush=True)


def layouts():
    import struct
    from ccfix_audit import audit
    rows = {}
    for arm, headers in [('PRE', BUILD / 'pre-src'), ('POST', ROOT)]:
        for db0 in (False, True):
            key = arm + ('/db0' if db0 else '/multi')
            target = BUILD / (key.replace('/', '-') + '-layout.o')
            defines = ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else []
            subprocess.run(CXX + defines + ['-DTOMO_CORE_CONCURRENCY_TEST', '-I' + str(headers),
                '-c', str(ROOT / 'tests/multidb_layout.cc'), '-o', str(target)], check=True)
            elf = audit.Elf(target)
            symbol = next(x for x in elf.symbols if x['name'] == 'multidb_layout_values')
            data = elf.section_data(symbol['sec'])[symbol['value']:symbol['value'] + symbol['size']]
            rows[key] = list(struct.unpack('<' + 'Q' * (len(data) // 8), data))
            assert rows[key][1:9] == [336, 1984, 1408, 1440, 944, 192, 144, 624]
    for suffix in ('/db0', '/multi'):
        assert rows['PRE' + suffix] == rows['POST' + suffix]
    (OUT / 'layout.json').write_text(json.dumps(rows, indent=2) + '\n')
    print('PASS all exported layouts match PRE in both namespaces')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proof', choices=('units', 'instructions', 'layouts'))
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    OUT.mkdir(parents=True, exist_ok=True)
    {'units': units, 'instructions': instructions, 'layouts': layouts}[args.proof]()
