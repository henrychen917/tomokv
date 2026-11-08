#!/usr/bin/env python3
"""Run the stale-owner native control through the unchanged gate job interface."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from wave14 import ROOT, DOC, BUILD, sha, save

assert os.sched_getaffinity(0) <= set(range(32))
ready = DOC/'jobs/r7-owner-fixed.json'
deadline = time.monotonic() + 3600
while not ready.exists():
    if time.monotonic() >= deadline:
        raise TimeoutError('positive R7 owner job did not finish')
    time.sleep(1)
positive = json.loads(ready.read_text())
assert positive['exit_code'] == 0, 'repair the positive fixture before running its control'
binary = ROOT/'build/reorder-engagement-unit'
before = BUILD/'r7-final/reorder-engagement-before'
saved = BUILD/'r7-final/reorder-engagement-restored'
assert before.exists() and not saved.exists()
original_hash = sha(binary)
shutil.copy2(binary, saved)
try:
    # This selected diagnostic run intentionally swaps only its native witness.
    # The release server remains untouched. Fresh mtime avoids rebuilding away
    # the planted object; the matching positive native binary is restored below.
    shutil.copyfile(before, binary)
    os.chmod(binary, 0o755)
    command = ['python3', 'tools/wave14.py', 'jobs', '--tag', 'r7-owner-before',
        '--jobs', 'reorder_engagement', '--binary', 'build/wave14/post-r7/tomokv',
        '--server-cores', '16-23', '--load-cores', '0-7', '--ports', '20093-20095']
    result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, LC_ALL='C'))
    record = json.loads((DOC/'jobs/r7-owner-before.json').read_text())
    run = Path(record['run_directory'])
    log = (run/'jobs/reorder_engagement/engagement.log').read_text()
    expected = 'R7 owner did not acknowledge tracking during LB IoDrain'
    assert result.returncode != 0 and expected in log, (result.returncode, log)
    save(DOC/'r7-owner-negative-witness.json', dict(expected=expected,
        before_unit_sha256=sha(before), positive_unit_sha256=original_hash,
        gate_exit_code=result.returncode, gate_record_sha256=sha(DOC/'jobs/r7-owner-before.json'),
        log_sha256=sha(run/'jobs/reorder_engagement/engagement.log')))
finally:
    shutil.copy2(saved, binary)
    assert sha(binary) == original_hash
    saved.unlink()
