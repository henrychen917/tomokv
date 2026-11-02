#!/usr/bin/env python3
"""Serverless sampler/retirement falsifiers; production sources stay unchanged."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/storefix5/retirement'
BUILD = ROOT / 'build/storefix5/retirement'
assert os.sched_getaffinity(0) <= set(range(16, 24))
os.environ['LC_ALL'] = 'C'
OUT.mkdir(parents=True, exist_ok=True)
BUILD.mkdir(parents=True, exist_ok=True)
sources = ['tests/store_regression.cc', 'src/cmd/t_hash.cc', 'src/cmd/t_hash_ttl.cc',
           'src/cmd/hexpread.cc', 'src/cmd/storesize.cc', 'src/store/flush.cc']
rows = []
for name, relative, old, new, expected in [
    ('no-notification-guard', 'src/store/flatstore_random.inc',
     '!(snapshot_active_ && table == 1) && read_retirement_available()',
     '!(snapshot_active_ && table == 1)',
     'deferred expiry emits no premature notification or AOF delete'),
    ('no-visibility-guard', 'src/store/flatstore_random.inc',
     'if (key.ns == physical && atomic_physical_key_visible(\n'
     '                hash_key(key), key, atomic_read_epoch_)) choose(key);',
     'if (key.ns == physical) choose(key);',
     'RANDOMKEY must not return a logically invisible key'),
    ('no-scan-guard', 'src/store/flatstore.h',
     '            if (!read_retirement_available()) return;\n'
     '            notify_flat_store_emit(this, NOTIFY_EXPIRED, NotifyEventId::Expired, o->key());',
     '            notify_flat_store_emit(this, NOTIFY_EXPIRED, NotifyEventId::Expired, o->key());',
     'RANDOMKEY entered a full retirement sink'),
]:
    directory = BUILD / name
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'src', directory / 'src', dirs_exist_ok=True)
    (directory / 'tests').mkdir(exist_ok=True)
    shutil.copy2(ROOT / sources[0], directory / sources[0])
    path = directory / relative
    text = path.read_text()
    assert text.count(old) == 1
    path.write_text(text.replace(old, new))
    argv = ['g++', '-std=c++20', '-O2', '-g', '-gz=zlib', '-march=native', '-pthread',
            '-ffunction-sections', '-fdata-sections', '-DTOMO_STORE_REGRESSION_TEST', '-I.',
            *sources, '-Wl,--gc-sections', '-Wl,--compress-debug-sections=zlib', '-o', 'probe']
    masked = None
    if name == 'no-visibility-guard':
        fixture = directory / sources[0]
        strengthened = fixture.read_text()
        check = '        require(object != nullptr, "RANDOMKEY must not return a logically invisible key");\n'
        assert strengthened.count(check) == 1
        fixture.write_text(strengthened.replace(check, ''))
        with (OUT / 'masked-visibility-before-build.log').open('w') as log:
            subprocess.run(argv, cwd=directory, stdout=log, stderr=subprocess.STDOUT, check=True)
        before = subprocess.run([str(directory / 'probe'), 'randomkey'], capture_output=True, text=True)
        masked = dict(exit=before.returncode, stdout=before.stdout, stderr=before.stderr,
                      binary_sha256=hashlib.sha256((directory / 'probe').read_bytes()).hexdigest())
        assert before.returncode == 0, masked
        (OUT / 'masked-visibility-before.json').write_text(json.dumps(masked, indent=2) + '\n')
        fixture.write_text(strengthened)
    with (OUT / (name + '-build.log')).open('w') as log:
        subprocess.run(argv, cwd=directory, stdout=log, stderr=subprocess.STDOUT, check=True)
    run = subprocess.run([str(directory / 'probe'), 'randomkey'], capture_output=True, text=True)
    row = dict(name=name, argv=argv, exit=run.returncode, stdout=run.stdout, stderr=run.stderr,
               expected_failure=expected, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if masked is not None:
        row['masked_test_before'] = masked
    (OUT / (name + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    assert run.returncode == 1 and expected in run.stderr, row
    rows.append(row)
    print(name, 'EXPECTED FAIL', flush=True)
(OUT / 'controls.json').write_text(json.dumps(rows, indent=2) + '\n')
