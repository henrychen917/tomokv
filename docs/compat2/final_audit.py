#!/usr/bin/env python3
"""Check final source/binary identity and build freshness without running a server."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/compat2'
BASE = 'bce4eb0aa6ab5b855903e201f6f19b321e09cba0'
assert set(os.sched_getaffinity(0)) <= set(range(64, 80))
results = []


def run(argv):
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
    stdout = result.stdout if len(result.stdout) < 4096 else dict(
        length=len(result.stdout), sha256=hashlib.sha256(result.stdout.encode()).hexdigest())
    results.append(dict(argv=argv, returncode=result.returncode,
                        stdout=stdout, stderr=result.stderr))
    (OUT / 'final-audit.json').write_text(json.dumps(results, indent=2) + '\n')
    assert result.returncode == 0, (argv, result.stdout, result.stderr)
    return result.stdout


targets = json.loads((OUT / 'units-complete/targets.json').read_text())
for target in ['all', *targets]:
    run(['make', '-q', target])
for name, flags in [('park', '-DTOMO_MDBQSBR_LIVE_PARK'),
                    ('no-wake', '-DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE')]:
    run(['make', '-q', f'BUILD_ROOT=build/mdbqsbr2-{name}',
         'CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread ' + flags, 'all'])
run(['git', 'diff', '--check', BASE])
run(['python3', 'tools/reorder_sync.py'])
before = run(['git', 'show', BASE + ':tests/gate.sh'])
after = (ROOT / 'tests/gate.sh').read_text()
pattern = r'^EXPECT_(?:QUICK|FULL)=.*$'
assert re.findall(pattern, before, re.M) == re.findall(pattern, after, re.M)
lines = after.splitlines()
collection = lines.index('collect_job compat2') + 1
quick_exit = lines.index('if [ "$TIER" = quick ]; then') + 1
assert collection < quick_exit
paths = run(['git', 'diff', '--name-only', BASE, '--', 'Makefile', 'src', 'tests', 'tools']).splitlines()
source_manifest = dict(base=BASE, files={
    path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths})
(OUT / 'source-manifest.json').write_text(json.dumps(source_manifest, indent=2) + '\n')
frozen = {
    'build/compat2/pre-source/build/tomokv': 'cedd6d07c8a274b71fe76fc4ef28f2bbfb0381e1ad8705a1bb880cb8290ee607',
    'build/compat2/tomokv-post': 'b8a21b0f8e880877b46a71b27e89a86ee5071c766da459417d773ba8a52c0596',
    'build/tomokv': 'b8a21b0f8e880877b46a71b27e89a86ee5071c766da459417d773ba8a52c0596',
    'build/compat2/tomokv-pad-a': '5c830403b32304512fe6b72ecf8d5d47e4e5f506cd7e294101798acc78b94ac1',
}
for path, expected in frozen.items():
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
print(json.dumps(dict(freshness_checks=len(targets) + 3, source_files=len(paths),
                      collection_line=collection, quick_exit_line=quick_exit,
                      expectations_unchanged=True, frozen_binaries=frozen), indent=2))
