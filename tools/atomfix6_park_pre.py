#!/usr/bin/env python3
"""Repeat the observed PRE park witness in both namespaces/read-local settings."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
root = Path(__file__).resolve().parents[1]
out = root / 'docs/atomfix6/park-pre-expanded'
out.mkdir(parents=True, exist_ok=True)
objects = sorted((root / 'build/pre/src').rglob('*.o'))
objects = [p for p in objects if p.name not in ('main.o', 'version.o')]
helpers = sorted((root / 'build/pre/third_party').rglob('*.o'))
rows = []
for namespace in ('normal', 'db0'):
    binary = root / f'build/atomfix6/park/PRE-expanded-{namespace}'
    flags = []
    selected = objects
    if namespace == 'db0':
        flags = ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        selected = [p for p in sorted((root / 'build/pre/db0/src').rglob('*.o'))
                    if p.name not in ('main.o', 'version.o')] + objects
    argv = ['g++', '-std=c++20', '-O2', '-g0', '-march=native', '-pthread',
            '-DTOMO_JEMALLOC', '-I' + str(root / 'build/pre-park-source'), '-I.', *flags,
            'tests/atomfix6_park_unit.cc', *map(str, selected + helpers),
            '-Wl,--compress-debug-sections=zlib', '-o', str(binary),
            '-ljemalloc', '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
    (out / f'{namespace}-build.json').write_text(json.dumps(argv, indent=2) + '\n')
    with (out / f'{namespace}-build.log').open('w') as log:
        subprocess.run(argv, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    for mode in ('1s', '2s'):
        result = subprocess.run([str(binary), mode], cwd=root, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / f'{namespace}-{mode}.log').write_text(result.stdout)
        valid = (result.returncode == 1 and
                 result.stdout.count('polls=8 scans=2019') == 2 and
                 'read-local=0' in result.stdout and 'read-local=1' in result.stdout)
        rows.append(dict(namespace=namespace, mode=mode, rc=result.returncode,
                         expected_failure=valid, binary_sha256=digest))
    binary.unlink()  # Generated negative control; hashes and logs retain the receipt.
(out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
assert all(r['expected_failure'] for r in rows), rows
print('PRE held-head witness: all eight mode/namespace/read-local arms fail as expected')
