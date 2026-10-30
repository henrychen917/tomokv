#!/usr/bin/env python3
"""Export a complete tracked tree, changing only the landing counts and fixture."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(64, 96)))
destination = ROOT / sys.argv[1]
assert not destination.exists(), 'Keep previous self-test attempts intact'
destination.mkdir(parents=True)
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
archive = subprocess.check_output(['git', 'archive', '--format=tar', commit], cwd=ROOT)
with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as source:
    source.extractall(destination, filter='data')
gate = destination / 'tests/gate.sh'
original = gate.read_text()
assert original.count('EXPECT_QUICK=946\n') == 1
assert original.count('EXPECT_FULL=963 ') == 1
gate.write_text(original.replace('EXPECT_QUICK=946\n', 'EXPECT_QUICK=977\n')
               .replace('EXPECT_FULL=963 ', 'EXPECT_FULL=994 '))
fixture = destination / 'tests/fixtures/nullrefresh-ledger-labels.json'
fixture.write_bytes((ROOT / 'docs/wave11/landing-label-fixture.json').read_bytes())
names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '-z', commit], cwd=ROOT).split(b'\0')
differences = []
for raw in names:
    if not raw:
        continue
    name = os.fsdecode(raw)
    source, target = ROOT / name, destination / name
    if source.is_symlink():
        assert target.is_symlink() and os.readlink(source) == os.readlink(target)
    elif source.read_bytes() != target.read_bytes():
        differences.append(name)
assert differences == ['tests/fixtures/nullrefresh-ledger-labels.json', 'tests/gate.sh'], differences
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
receipt = dict(copy=str(destination), commit=commit, tracked_files=sum(bool(n) for n in names),
               archive_sha256=hashlib.sha256(archive).hexdigest(),
               only_tracked_file_differences=differences,
               root_expect=re.findall(r'^EXPECT_(?:QUICK|FULL)=\d+', original, re.M),
               copy_expect=re.findall(r'^EXPECT_(?:QUICK|FULL)=\d+', gate.read_text(), re.M),
               root_gate_sha256=sha(ROOT / 'tests/gate.sh'), copy_gate_sha256=sha(gate),
               landing_fixture_sha256=sha(fixture),
               tracked_fixture_sha256=sha(ROOT / 'tests/fixtures/nullrefresh-ledger-labels.json'),
               passed=True)
(ROOT / 'docs/wave11/abba-copy-replay.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
