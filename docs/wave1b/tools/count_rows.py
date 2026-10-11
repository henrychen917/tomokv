#!/usr/bin/env python3
"""Count gate rows declared before the quick-tier exit (DQ) and in full (DF), using
tests/gate_ledger_fixture.py's own source_labels (no execution). Usage:
count_rows.py <repo-root> [<gate.sh path or git rev:path>]"""
import json, re, subprocess, sys
from collections import Counter
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / 'tests'))
import gate_ledger_fixture as g
if len(sys.argv) > 2 and ':' in sys.argv[2]:
    gate = subprocess.check_output(['git', '-C', str(root), 'show', sys.argv[2]], text=True)
elif len(sys.argv) > 2:
    gate = Path(sys.argv[2]).read_text()
else:
    gate = (root / 'tests/gate.sh').read_text()
full = g.source_labels(gate)
quick_marker = '\nif [ "$TIER" = quick ]; then\n'
assert gate.count(quick_marker) == 1, 'quick-tier exit not unique'
quick_gate = gate.replace(quick_marker, '\n# Every worker has reaped (quick-tier cut for counting)\n' + quick_marker)
quick = g.source_labels(quick_gate)
eq = re.findall(r'^EXPECT_QUICK=([0-9]+)', gate, re.M); ef = re.findall(r'^EXPECT_FULL=([0-9]+)', gate, re.M)
print(json.dumps(dict(quick=len(quick), full=len(full), EXPECT_QUICK=int(eq[0]), EXPECT_FULL=int(ef[0]),
                      dq=len(quick) - int(eq[0]), df=len(full) - int(ef[0]))))
if '--labels' in sys.argv:
    Path(sys.argv[sys.argv.index('--labels') + 1]).write_text(json.dumps(dict(quick=quick, full=full), indent=1))
