"""wave3 (from docs/aoforder/hash-expiry/run.py): aoforder's hash-expiry live-tear probe, which failed on
aoforder's own POST by design (fixed only by hexpread HX-1). PRE = f821104a9 must still witness the
tear (AOF always and AOF off); the integrated binary must pass: live MGET = ["1","1"] and, with AOF,
LOADAOF and a distinct-process restart equal live. Probe runs on drivers 89-95, servers 80-87.
usage (worktree root): python3 docs/wave3/tools/hash_expiry_run.py <out-dir>"""
from pathlib import Path
import json, subprocess, sys, time
root = Path(sys.argv[1]).resolve(); root.mkdir(parents=True, exist_ok=False)
rows = []
arms = [('pre', 'build/wave3/refs/pre-src/build/tomokv', 'yes', 'tear'),
        ('pre-off', 'build/wave3/refs/pre-src/build/tomokv', 'no', 'tear'),
        ('integrated', 'build/tomokv', 'yes', 'pass'),
        ('integrated-off', 'build/tomokv', 'no', 'pass')]
for arm, binary, appendonly, expect in arms:
    for mode in ('1s', '2s'):
        label = arm + '-' + mode
        command = ['taskset', '-c', '89-95', 'python3', 'docs/wave3/tools/hash_expiry_probe.py', '--binary', binary,
                   '--artifacts', str(root / label), '--mode', mode, '--appendonly', appendonly]
        start = time.monotonic()
        with (root / (label + '.log')).open('w') as log:
            r = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        text = (root / (label + '.log')).read_text()
        tear = r.returncode == 1 and 'AssertionError: hash-field expiry tore an undecided MSET in the live keyspace' in text
        ok = (expect == 'tear' and tear) or (expect == 'pass' and r.returncode == 0)
        rows.append(dict(label=label, binary=binary, appendonly=appendonly, expect=expect, rc=r.returncode,
                         tear_witnessed=tear, as_expected=ok, seconds=round(time.monotonic() - start, 2)))
        (root / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n'); print(rows[-1], flush=True)
raise SystemExit(not all(row['as_expected'] for row in rows))
