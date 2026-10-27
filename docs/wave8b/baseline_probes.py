#!/usr/bin/env python3
"""Reconstruct the two original headline fixtures and require their committed full SHA."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64, 80)))
COMMIT = 'fe065d3bd'
fixture = ROOT / 'tests/wave8b_scope.cc'
saved = fixture.read_bytes()
stat = fixture.stat()
out = ROOT / 'build/wave8b/baseline-probes'
out.mkdir(exist_ok=True)
(out / 'fixture-before-rebuild.cc').write_bytes(saved)
original = subprocess.check_output(['git', 'show', COMMIT + ':tests/wave8b_scope.cc'])
rows = []
try:
    fixture.write_bytes(original)
    for namespace in ('normal', 'db0'):
        name = f'docs/wave8b/instructions/headline-{namespace}-build.json'
        receipt = json.loads(subprocess.check_output(['git', 'show', COMMIT + ':' + name]))
        dest = out / ('headline-' + namespace)
        dest.mkdir(exist_ok=True)
        compile_command = receipt['compile'].copy()
        old_object = compile_command[compile_command.index('-o') + 1]
        compile_command[compile_command.index('-o') + 1] = str(dest / 'probe.o')
        link = [str(dest / 'probe.o') if arg == old_object else arg for arg in receipt['link']]
        link[link.index('-o') + 1] = str(dest / 'probe')
        with (dest / 'rebuild.log').open('w') as log:
            subprocess.run(compile_command, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(link, stdout=log, stderr=subprocess.STDOUT, check=True)
        actual = hashlib.sha256((dest / 'probe').read_bytes()).hexdigest()
        row = dict(namespace=namespace, original_commit=COMMIT, original_receipt=name,
                   expected_sha256=receipt['sha256'], actual_sha256=actual,
                   path=str(dest / 'probe'), compile=compile_command, link=link)
        rows.append(row)
        print(namespace, actual, 'original SHA identical:', actual == receipt['sha256'], flush=True)
        assert actual == receipt['sha256'], row
finally:
    fixture.write_bytes(saved)
    os.utime(fixture, ns=(stat.st_atime_ns, stat.st_mtime_ns))
assert fixture.read_bytes() == saved
(ROOT / 'docs/wave8b/baseline-probes.json').write_text(json.dumps(rows, indent=2) + '\n')
