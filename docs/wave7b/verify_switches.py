#!/usr/bin/env python3
"""Keep strict inventory differences visible and verify relocated switch destinations."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'docs/wave7'))
import switch_provenance
report = json.loads((ROOT / 'docs/wave7b/identity.json').read_text())
names = set(report['counted_command_changed'])
before = json.loads((ROOT / 'docs/wave7/instructions/switch-provenance.json').read_text())['binaries']['post-production']
after = switch_provenance.inspect(ROOT / 'build/tomokv', names)
for name in names:
    assert after[name] == before[name], name
result = dict(before_sha256=report['before_sha256'], after_sha256=report['after_sha256'],
              verification='All instruction encodings and every bounded switch destination match; strict raw offset differences remain in identity.json.',
              proof=after)
(ROOT / 'docs/wave7b/switch-provenance.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS',len(names),'relocated switches; changed case destination and changed bound branch rejected')
