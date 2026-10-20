#!/usr/bin/env python3
"""wave3 gate-row accounting (source only; never executes the gate).

Counts the quick (rows before the quick-tier exit) and full source declarations with the checker's
own tests/gate_ledger_fixture.source_labels, for this tree and for f821104a9, lists the labels this
branch adds or removes, checks the label fixture multiset against the source (in memory: EXPECT_FULL
stays maintainer-owned), and runs the unmodified checker for its verdict text. Quick-tier cut as in
docs/dbdefault/row_audit.py. usage: ledger_check.py <out.json>
"""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests'))
import gate_ledger_fixture as fixture

BASE = 'f821104a9'


def quick_part(text):
    first = text.index('\nstart_workers\n')
    cut = text.index('\nif [ "$TIER" = quick ]; then', first)
    end = text.index('\n# Every worker has reaped', cut)
    return text[:cut] + text[end:]


def counts(text):
    return len(fixture.source_labels(quick_part(text))), fixture.source_labels(text)


def main():
    source = (ROOT / 'tests/gate.sh').read_text()
    base = subprocess.check_output(['git', 'show', BASE + ':tests/gate.sh'], cwd=ROOT, text=True)
    quick, full = counts(source)
    base_quick, base_full = counts(base)
    added = Counter(full) - Counter(base_full)
    removed = Counter(base_full) - Counter(full)
    quick_labels = Counter(fixture.source_labels(quick_part(source)))
    data = json.loads((ROOT / fixture.FIXTURE).read_text())
    labels = data['labels']
    missing = Counter(full) - Counter(labels)
    extra = Counter(labels) - Counter(full)
    expect_quick = int(re.search(r'^EXPECT_QUICK=(\d+)', source, re.M)[1])
    expect_full = int(re.search(r'^EXPECT_FULL=(\d+)', source, re.M)[1])
    in_memory = re.sub(r'^EXPECT_FULL=\d+', f'EXPECT_FULL={len(full)}', source, flags=re.M)
    try:
        fixture.check(in_memory, labels)
        in_memory_ok = True
    except ValueError as error:
        in_memory_ok = str(error)
    unmodified = subprocess.run([sys.executable, 'tests/gate_ledger_fixture.py'], cwd=ROOT,
                                capture_output=True, text=True)
    result = dict(base=BASE, base_quick=base_quick, base_full=len(base_full), quick=quick, full=len(full),
                  DQ=quick - base_quick, DF=len(full) - len(base_full),
                  expect_quick=expect_quick, expect_full=expect_full,
                  added=sorted(added.elements()), removed=sorted(removed.elements()),
                  added_before_quick_exit=sum(1 for label in added.elements() if quick_labels[label]),
                  fixture_labels=len(labels), fixture_missing=sorted(missing.elements()),
                  fixture_extra=sorted(extra.elements()), fixture_matches_source=not missing and not extra,
                  checker_accepts_fixture_at_source_count=in_memory_ok,
                  unmodified_checker=dict(rc=unmodified.returncode,
                                          output=(unmodified.stdout + unmodified.stderr).strip()[:600]))
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('added', 'removed')}, indent=1))


if __name__ == '__main__':
    main()
