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
    'record-reuse': 'record reuse waits for the cancelled drain reader, without blocking IO',
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

# One witness row: a real contended shape lock, 128 buffered requests, both modes.
# The frozen PRE/POST1 receipts demonstrate this assertion rejects the old mechanism.
timing_arms = []
for name, binary, argument in [('POST2', 'build/lbplanner-unit', 'timing'),
                               ('PAD-A2', 'build/lbplanner-unit-pad', 'timing-pad')]:
    result = subprocess.run([str(root / binary), argument], capture_output=True, text=True, timeout=60)
    output = result.stdout + result.stderr
    cases = [json.loads(line[7:]) for line in output.splitlines() if line.startswith('TIMING=')]
    good = result.returncode == 0 and len(cases) == 6 and 'PASS LB client-drain timing witness' in output
    timing_arms.append(dict(arm=name, passed=good, returncode=result.returncode, cases=cases, output=output))
for name, message in {
    'timing-lock': 'contended shape lock never delays source or destination record reads',
    'timing-late-pause': 'busy candidate refuses on pass one with its executor predicate',
    'timing-budget': 'drain budget charges only actual ACK waits',
}.items():
    result = subprocess.run([str(root / f'build/lbplanner-controls/{name}/unit'), 'timing'],
                            capture_output=True, text=True, timeout=60)
    output = result.stdout + result.stderr
    good = result.returncode == 1 and 'FAIL core concurrency: ' + message in output
    timing_arms.append(dict(arm=name, passed=good, returncode=result.returncode, output=output))
good = all(arm['passed'] for arm in timing_arms)
rows.append(dict(arm='client-drain-first-tail', passed=good, arms=timing_arms))
print(('PASS' if good else 'FAIL'), 'client-drain-first-tail: POST2/PAD-A2, both modes, three isolated negative controls')
if not good:
    print(json.dumps(timing_arms, indent=2))
for name, binary, expected, message in [
    ('PAD-A', 'build/lbplanner-unit-pad', 0, 'PASS PAD-A PRE behavior'),
    ('POST-rejects-PRE', 'build/lbplanner-unit', 1, 'PAD monitor never runs LB search'),
]:
    result = subprocess.run([str(root / binary), 'pad'], capture_output=True, text=True, timeout=60)
    output = result.stdout + result.stderr
    good = result.returncode == expected and message in output
    rows.append(dict(arm=name, passed=good, returncode=result.returncode, output=output))
    print(('PASS' if good else 'FAIL'), name, output.strip())
for name, binary, argument, expected, message in [
    ('LBOSC3', 'build/lbplanner-unit', 'lbosc3', 0, 'PASS LBOSC3 both modes'),
    ('LBOSC3-PAD-A', 'build/lbosc3-unit-pad', 'lbosc3-pre', 0, 'PASS LBOSC3 both modes'),
    ('LBOSC3-rejects-PRE', 'build/lbosc3-unit-pad', 'lbosc3', 1,
     'key objective chooses the least transfer inside the residual band'),
    ('LBOSC3-PRE-rejects-POST', 'build/lbplanner-unit', 'lbosc3-pre', 1,
     'key objective chooses the least transfer inside the residual band'),
]:
    result = subprocess.run([str(root / binary), argument], capture_output=True, text=True, timeout=60)
    output = result.stdout + result.stderr
    good = result.returncode == expected and message in output
    rows.append(dict(arm=name, passed=good, returncode=result.returncode, output=output))
    print(('PASS' if good else 'FAIL'), name, output.strip())
(root / 'build/lbplanner-checks.json').write_text(json.dumps(rows, indent=2) + '\n')
assert all(row['passed'] for row in rows), 'hand-off witness or a named negative control failed'
