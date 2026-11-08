#!/usr/bin/env python3
"""Collect small, reviewable A2 receipts; keep binaries and compiler logs in build/."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build/readability-a2'
OUT = ROOT / 'docs/readability-a2/evidence'
OUT.mkdir(exist_ok=True)


def copy(source, name):
    assert source.stat().st_size < 1_000_000, source
    shutil.copyfile(source, OUT / name)


def write(name, value):
    text = json.dumps(value, indent=2) + '\n'
    assert len(text.encode()) < 1_000_000, name
    (OUT / name).write_text(text)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


for name in ('style.json', 'source-proof.json', 'binary-neutral.log', 'builds.json',
             'gate-command.json', 'gates-test.log', 'ledger-test.log',
             'lottery-runner-test.log', 'caller-inventory-test.log',
             'format-check-post.log', 'format-check-pre-final.json',
             'format-check-pre-final.log'):
    copy(WORK / name, name)
copy(WORK / 'candidates/results.json', 'candidates.json')

summary = dict(source={}, symbols={})
generated = {}
symbol_inventories = {}
for shape in ('pre', 'post'):
    rows = json.loads((WORK / f'tools-{shape}/results.json').read_text())
    assert len(rows) == 52 and all(r['passed'] for r in rows)
    copy(WORK / f'tools-{shape}/results.json', f'tools-{shape}.json')
    generated[shape] = json.loads((WORK / f'tools-{shape}/generated-tokens.json').read_text())
    summary['source'][shape] = dict(positive=len(rows), broken_anchor_rejections=len(rows),
                                    emitted_files=len(generated[shape]))
    symbols = []
    for prefix in ('symbols', 'storesize'):
        symbols += json.loads((WORK / f'{prefix}-{shape}/results.json').read_text())
    assert len(symbols) == 9 and all(r['passed'] for r in symbols)
    write(f'symbols-{shape}.json', symbols)
    symbol_inventories[shape] = {r['tool']: r['removed_symbols'] for r in symbols}
    summary['symbols'][shape] = dict(positive=len(symbols), missing_symbol_rejections=len(symbols),
                                     inventories=symbol_inventories[shape])
assert generated['pre'] == generated['post'] and len(generated['post']) == 313
assert symbol_inventories['pre'] == symbol_inventories['post']
write('emitted-tokens.json', generated['post'])
write('tool-summary.json', summary)

gate_log = (WORK / 'gate.log').read_text()
run = Path(re.search(r'^  artifacts: (.+)$', gate_log, re.M)[1]).resolve()
assert run.is_relative_to(ROOT / 'build')
jobs = {}
for directory in sorted((run / 'jobs').iterdir()):
    rc, passed, failed = map(int, (directory / 'done').read_text().split())
    labels = []
    for line in (directory / 'ledger').read_text().splitlines():
        fields = line.split('\t')
        if fields[0] in ('ok', 'FAIL'):
            labels.append(dict(status=fields[0], label=fields[2]))
    jobs[directory.name] = dict(exit=rc, passed=passed, failed=failed, rows=labels)
write('gate-results.json', dict(run=str(run), jobs=jobs,
      passed=sum(j['passed'] for j in jobs.values()), failed=sum(j['failed'] for j in jobs.values()),
      counted_jobs=sum(bool(j['rows']) for j in jobs.values())))
copy(WORK / 'gate.log', 'gate.log')
assert all(j['exit'] == 0 and j['failed'] == 0 for j in jobs.values()), 'gate failures remain'

sys.path.insert(0, str(ROOT / 'tests'))
import gate_ledger_fixture as fixture
declared = fixture.validate_fixture(ROOT)
fixture_rows = json.loads((ROOT / fixture.FIXTURE).read_text())['labels']
write('labels.json', dict(declared=len(declared), fixture_rows=len(fixture_rows),
      nic='separate optional ledger row; not exercised by this partial run',
      gate_sha256=sha(ROOT / 'tests/gate.sh'), fixture_sha256=sha(ROOT / fixture.FIXTURE)))

pre = Path('/home/user/Projects/bins/readability-pre-5c363128/tomokv')
write('binary.json', dict(pre=str(pre), pre_sha256=sha(pre),
      post='build/tomokv', post_sha256=sha(ROOT / 'build/tomokv'),
      info_git_sha1='5c363128', info_git_dirty='0',
      compiler=subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
      proof=(WORK / 'binary-neutral.log').read_text().strip()))
print('collected', len(list(OUT.iterdir())), 'small receipts from', run)
