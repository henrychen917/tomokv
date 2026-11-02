#!/usr/bin/env python3
"""Check the frozen lane artifacts and final receipts without starting a server."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/storefix5'
os.chdir(ROOT)
assert os.sched_getaffinity(0) <= set(range(16, 24)), 'lane CPU boundary'
assert os.getenv('LC_ALL') == 'C', 'lane locale'


def read(path):
    return json.loads(path.read_text())


def command(argv):
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return dict(argv=argv, exit=result.returncode, output=result.stdout)


freshness = [command(row['argv']) for row in read(DOC / 'freshness-final.json')]
assert len(freshness) == 59 and all(row['exit'] == 0 for row in freshness), 'make freshness'
build_bytes = int(subprocess.check_output(['du', '-s', '-B1', 'build'], text=True).split()[0])
assert build_bytes < 15 * 1024**3, ('build disk budget', build_bytes)
arms = {}
for line in (DOC / 'ARMS.sha256').read_text().splitlines():
    expected, name = line.split()
    path = ROOT / 'build/storefix5' / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == expected, ('arm identity', name)
    arms[name] = dict(path=str(path.relative_to(ROOT)), sha256=digest)
identity = read(DOC / 'release-code-identity.json')
assert identity['code_equal'] and identity['POST']['sha256'] == arms['POST']['sha256']
assert hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest() == identity['fresh']['sha256']

gate = (ROOT / 'tests/gate.sh').read_text()
pre_gate = subprocess.check_output(['git', 'show', 'ea48a6b27:tests/gate.sh'], text=True)
counts = re.findall(r'^EXPECT_(?:QUICK|FULL)=.*$', gate, re.M)
assert counts == re.findall(r'^EXPECT_(?:QUICK|FULL)=.*$', pre_gate, re.M), 'EXPECT constants'
lines = gate.splitlines()
collect_line = next(i for i, line in enumerate(lines, 1) if line.strip() == 'collect_job storefix5')
quick_line = next(i for i, line in enumerate(lines, 1)
                  if line.strip() == 'if [ "$TIER" = quick ]; then' and i > collect_line)
assert collect_line < quick_line, 'new rows are before quick exit'

matrices = []
for run in read(DOC / 'gate-summary.json')['runs']:
    if Path(run['log']).name not in ('gate-differ-uring-final.log', 'gate-differ-epoll-final.log'):
        continue
    rows = [job for job in run['jobs'] if 'differ' in job]
    assert len(rows) == 4, ('matrix coverage', run['log'])
    assert sorted(row['differ']['passed'] for row in rows) == [231, 235, 235, 239]
    for row in rows:
        assert row['exit'] == 0 and row['differ']['failed'] == 0, ('differ result', row['name'])
        assert {7, 19, 20, 23} <= set(row['differ']['seeds']), ('standard seeds', row['name'])
        matrices.append(dict(log=run['log'], job=row['name'], **row['differ']))
assert len(matrices) == 8 and sum(row['passed'] for row in matrices) == 1880, 'differ total'

manifest = read(DOC / 'gate-receipts.json')
archive = DOC / manifest['archive']
assert archive.stat().st_size == manifest['bytes']
assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['sha256'], 'archive digest'
listeners = command(['ss', '-ltnH', '( sport >= :21600 and sport <= :21699 )'])
assert listeners['exit'] == 0 and not listeners['output'].strip(), 'lane servers remain'
remaining_data = [str(path.relative_to(ROOT)) for directory in (ROOT / 'build').glob('gate-run.*')
                  for path in directory.rglob('*') if path.is_file() and
                  path.suffix in ('.rdb', '.tomo', '.aof', '.manifest')]
assert not remaining_data, ('persisted test data', remaining_data[:10])
diff = command(['git', 'diff', '--check'])
assert diff['exit'] == 0, 'diff whitespace'

receipt = dict(arms=arms, build_bytes=build_bytes, freshness=freshness, expected_rows=counts,
               new_row_collect_line=collect_line, quick_exit_line=quick_line,
               dq=2, df=2, differential_matrices=matrices, differential_passes=1880,
               archive_sha256=manifest['sha256'], archive_files=len(manifest['files']),
               listeners=listeners, remaining_data=remaining_data, diff_check=diff,
               note='Integrity only; unresolved correctness/timing rows retain their verdicts.')
(DOC / 'final-audit.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('PASS: three arm digests, 59 freshness checks, 1880 differential rows, archive and cleanup')
