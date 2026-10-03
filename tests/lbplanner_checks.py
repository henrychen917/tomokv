#!/usr/bin/env python3
"""Run the serverless hand-off and require each broken mechanism to fail its named witness."""
from pathlib import Path
import json
import subprocess

root = Path(__file__).resolve().parents[1]
controls = {
    'no-publish': 'monitor must produce a finished plan; unarmed witness fails',
    'stale-flip': 'stale topology plan dropped without drain',
    'stale-lb': 'stale topology plan dropped without drain',
    'duplicate': 'finished plan consumed exactly once',
    'copy-on-io': 'IO handoff allocates and frees nothing',
}
rows = []
for name in ['production', *controls]:
    binary = root / ('build/lbplanner-unit' if name == 'production' else f'build/lbplanner-controls/{name}/unit')
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    output = result.stdout + result.stderr
    good = (result.returncode == 0 and 'PASS LB monitor handoff' in output if name == 'production'
            else result.returncode == 1 and 'FAIL core concurrency: ' + controls[name] in output)
    rows.append(dict(arm=name, passed=good, returncode=result.returncode, output=output))
    print(('PASS' if good else 'FAIL'), name, output.strip())
(root / 'build/lbplanner-checks.json').write_text(json.dumps(rows, indent=2) + '\n')
assert all(row['passed'] for row in rows), 'hand-off witness or a named negative control failed'
