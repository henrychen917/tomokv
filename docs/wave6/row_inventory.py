#!/usr/bin/env python3
"""Record source-declared rows and collection positions, never execution results."""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from gate_ledger_fixture import source_labels

gate = (ROOT / 'tests/gate.sh').read_text()
headline = subprocess.check_output(
    ['git', 'show', 'ef5204b2e:tests/gate.sh'], cwd=ROOT, text=True)
protected = lambda text: re.findall(r'^EXPECT_(?:QUICK|FULL)=\d+', text, re.M)
assert protected(gate) == protected(headline) == ['EXPECT_QUICK=739', 'EXPECT_FULL=756']
cut = gate.index('\nif [ "$TIER" = quick ]; then')
last = gate.index('\n# Every worker has reaped', cut)
full = Counter(source_labels(gate))
quick = Counter(source_labels(gate[:cut] + gate[last:]))
fixture = Counter(json.loads((ROOT / 'tests/fixtures/nullrefresh-ledger-labels.json').read_text())['labels'])
manifest = json.loads((ROOT / 'docs/wave6/job-manifest.json').read_text())
collections = []
for job in manifest['lanes']:
    match = re.search(r'^collect_job ' + re.escape(job) + r'\b.*$', gate, re.M)
    assert match, job
    collections.append(dict(job=job, rows=7 if job == 'notifycompat' else 1,
                            line=gate.count('\n', 0, match.start()) + 1,
                            before_quick_exit=match.start() < cut))
result = dict(expected_unchanged=protected(gate), source_quick=quick.total(),
              source_full=full.total(), fixture=fixture.total(),
              missing=dict(full - fixture), extra=dict(fixture - full),
              quick_exit_line=gate.count('\n', 0, cut) + 2,
              lane_collections=collections,
              DQ=quick.total() - 739, DF=full.total() - 756)
assert not result['missing'] and not result['extra']
assert (result['DQ'], result['DF']) == (29, 29)
assert sum(row['rows'] for row in collections) == 29
assert all(row['before_quick_exit'] for row in collections)
(ROOT / 'docs/wave6/rows.json').write_text(json.dumps(result, indent=2) + '\n')
print(result['source_quick'], result['source_full'], 'quick exit line', result['quick_exit_line'])
