#!/usr/bin/env python3
"""Build/run deterministic serverless negative controls, never a server or timer.

Run after `taskset -c 112-127 make -j16 build/multidb-unit`. Only build/ is
mutated; production sources and the positive binary are left untouched.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
assert os.sched_getaffinity(0) <= set(range(112, 128)), 'pin this driver to 112-127'
OUT = ROOT / 'build/mdbstamp-controls'
OUT.mkdir(exist_ok=True)
source = (ROOT / 'src/cmd/multidb.cc').read_text()
dry = subprocess.check_output(['make', '-nB', 'build/multidb-unit'], text=True)
link, = [shlex.split(line) for line in dry.splitlines() if ' -o build/multidb-unit ' in line]
flags = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native',
         '-pthread', '-DTOMO_JEMALLOC', '-I.', '-Isrc/cmd']
results = []


def run(name, command, expected=0, assertion=None):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log = OUT / (name + '.log')
    log.write_text('$ ' + shlex.join(command) + '\n' + result.stdout + f'\nSTATUS {result.returncode}\n')
    record = dict(name=name, command=shlex.join(command), status=result.returncode,
                  assertion=assertion, log=str(log.relative_to(ROOT)))
    results.append(record)
    (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    assert result.returncode == expected, (name, result.returncode, result.stdout[-3000:])
    if assertion:
        assert assertion in result.stdout, (name, 'wrong assertion', result.stdout[-3000:])
    print(f'{name}: status={result.returncode}' + (f' {assertion}' if assertion else ''), flush=True)
    return result.stdout


mutations = {
    'no-direct': ('if (stamp_regular_range(op)) return;', 'if (false && stamp_regular_range(op)) return;'),
    'stride-one': ('key += spec->key_step', 'key += 1'),
    'no-fallback': ('if (stamp_regular_range(op)) return;', 'if (stamp_regular_range(op)) return;\n    return;'),
    'no-copy-override': ('if (op.cmd_name().eq_icase("copy") && op.argc() >= 3)',
                         'if (false && op.cmd_name().eq_icase("copy") && op.argc() >= 3)'),
    'ignore-private': ('if constexpr (kSingleDatabase) return;\n    stamp(server, op, logical, map);',
                       'if constexpr (kSingleDatabase) return;\n    multidb_stamp(server, op, logical);'),
    'wrong-physical': ('op.physical_db = map[logical];', 'op.physical_db = logical;'),
}
for name, (before, after) in mutations.items():
    assert source.count(before) == 1, (name, 'mutation anchor changed')
    path = OUT / (name + '.cc')
    path.write_text(source.replace(before, after))
    obj = str(OUT / (name + '.o'))
    run('build-' + name, flags + ['-c', str(path), '-o', obj])
    command = [obj if word == 'build/src/cmd/multidb.o' else
               str(OUT / name) if word == 'build/multidb-unit' else word for word in link]
    run('link-' + name, command)

controls = [
    ('no-direct', 'regular-alloc', 'regular-zero-allocation'),
    ('no-direct', 'regular-metadata', 'regular-no-metadata-entry'),
    ('no-direct', 'registry', 'registry-classification'),
    ('stride-one', 'mset-stride', 'mset-stride'),
    ('stride-one', 'msetnx-stride', 'msetnx-stride'),
    ('no-fallback', 'sort-store', 'sort-store'),
    ('no-fallback', 'eval', 'eval'),
    ('no-fallback', 'xread', 'xread'),
    ('no-fallback', 'zunionstore', 'zunionstore'),
    ('no-copy-override', 'copy-db-replace', 'copy-db-replace'),
    ('ignore-private', 'get24', 'get24'),
    ('ignore-private', 'copy-db-replace', 'copy-db-replace'),
    ('ignore-private', 'move', 'move'),
    ('wrong-physical', 'regular', 'regular-shadow-namespaces'),
    ('wrong-physical', 'registry', 'registry-range-equivalence'),
]
for mutation, selection, assertion in controls:
    run(mutation + '-' + selection,
        ['taskset', '-c', '112-119', str(OUT / mutation), '--stamp-check', selection],
        1, 'FAIL mdbstamp: ' + assertion)
# Every explicit semantic assertion has its own nonidentity-map negative control,
# including keyless and malformed commands with no extracted keys at all.
names = subprocess.check_output(['taskset', '-c', '112-119', 'build/multidb-unit',
                                 '--stamp-check', 'list'], text=True).splitlines()
for name in names:
    run('wrong-physical-' + name,
        ['taskset', '-c', '112-119', str(OUT / 'wrong-physical'), '--stamp-check', name],
        1, 'FAIL mdbstamp: ' + name)
run('ignore-private-exec', ['taskset', '-c', '112-119', str(OUT / 'ignore-private'), '--owners-only'],
    1, 'SWAPDB/SELECT/MOVE share one untorn EXEC array')
