#!/usr/bin/env python3
"""Validate complete lane differential receipts and retain their original logs."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from differ_fanout import PARTS, fold, load_plan, read_journal

source = ROOT / 'build/storesize5/differ'
out = ROOT / 'docs/storesize5'
plan = load_plan(ROOT / 'docs/at15b/differ-plan.json')
expected = {row['seed']: row['exact_positions'] for row in
            json.loads((out / 'generator-positions.json').read_text())}
folds = []
for group in ('split', 'armed'):
    actual = fold(plan, group, source)
    saved = json.loads((source / ('differ-' + group + '-fold.json')).read_text())
    assert saved['complete'] is True and saved['verdict'] == 'PASS'
    assert all(saved[key] == value for key, value in actual.items())
    folds.append(saved)
    (out / ('differ-' + group + '-fold.json')).write_text(json.dumps(saved, indent=2) + '\n')

parts, directed, properties = [], [], []
pattern = re.compile(r'exact_positions=(\d+) publication_polls=(\d+) '
                     r'publication_ms=([\d.]+) published=(\d+) exact=(\d+) converged=(\w+)')
for part in PARTS:
    directory = source / 'jobs' / ('differ-' + part) / 'differ'
    done = json.loads((directory / 'complete.json').read_text())
    parts.append(done)
    if part == 'equivalence':
        continue
    atomic = int(part[-1])
    for suite, _, seed, repeat, rc, name in read_journal(directory):
        if suite not in ('multi', 'multidb') or repeat:
            continue
        text = (directory / name).read_text()
        match = re.search(r'DIFFER \w+: (\d+) ops, (\d+) diffs, (\d+) clock tolerances -> (\w+)', text)
        assert rc == 0 and match and match.groups()[1:] == ('0', '0', 'PASS'), (part, name, match)
        directed.append(dict(part=part, suite=suite, atomic=atomic, seed=seed,
                             operations=int(match[1]), diffs=0, clock_tolerances=0))
        if suite == 'multidb':
            counts = pattern.search(text)
            assert counts and int(counts[1]) == expected[seed] and int(counts[2]) > 0
            assert 0 <= float(counts[3]) <= 100 and counts.groups()[3:] == ('1', '1', 'True')
            properties.append(dict(part=part, seed=seed, exact_positions=int(counts[1]),
                                   polls=int(counts[2]), milliseconds=float(counts[3])))
assert len(directed) == 48 and len(properties) == 24
assert sum(row['exact_positions'] for row in properties) == 7200
report = dict(folds=folds, parts=parts, directed=directed, publication=properties,
              exact_positions=7200, convergence_checks=24,
              maximum_publication_ms=max(row['milliseconds'] for row in properties))
(out / 'differ-results.json').write_text(json.dumps(report, indent=2) + '\n')

# Preserve every original matrix log, coverage artifact, completion and wrapper
# receipt. Exclude server data directories and retain deterministic archive bytes.
files = [p for p in sorted(source.rglob('*')) if p.is_file() and
         (p.suffix in ('.log', '.txt', '.json', '.tsv') or p.name in ('done', 'ledger'))]
manifest = []
tar_bytes = io.BytesIO()
with tarfile.open(fileobj=tar_bytes, mode='w') as archive:
    for path in files:
        relative = path.relative_to(source).as_posix()
        data = path.read_bytes()
        entry = tarfile.TarInfo(relative)
        entry.size = len(data)
        entry.mode = 0o644
        archive.addfile(entry, io.BytesIO(data))
        manifest.append(dict(path=relative, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
(out / 'differ-receipts.tar.gz').write_bytes(gzip.compress(tar_bytes.getvalue(), mtime=0))
(out / 'differ-receipts-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({key: report[key] for key in
                  ('exact_positions', 'convergence_checks', 'maximum_publication_ms')}, indent=2))
for row in folds:
    print(row['group'], 'complete=true verdict=PASS', 'comparisons=' + str(row['comparisons']))
