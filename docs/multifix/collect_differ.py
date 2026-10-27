#!/usr/bin/env python3
"""Bind both completed differential jobs to their plans and terminal receipts."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/multifix'
PARTS = ('split-0', 'split-1', 'armed-0', 'armed-1', 'equivalence')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


report = {}
for engine in ('uring', 'epoll'):
    receipt = OUT / 'jobs' / f'final-differ-{engine}.json'
    job = json.loads(receipt.read_text())
    assert job['exit'] == 0 and job['binary_unchanged'], job
    artifact = Path(job['artifacts'])
    plan_path = artifact / 'differ-plan.json'
    plan = json.loads(plan_path.read_text())
    assert plan['manifest']['permanent'] == [7, 19, 20, 23]
    assert plan['repeats'] == 4 and len(plan['suites']) == 47
    parts = []
    for part in PARTS:
        base = artifact / 'jobs' / f'differ-{part}'
        log = base / 'output.log'
        text = log.read_text()
        terminal = re.findall(r'DIFFER GATE: pass=(\d+) fail=(\d+) runtime=([^\n]+)', text)
        assert len(terminal) == 1 and terminal[0][1] == '0', (engine, part, terminal)
        assert (base / 'done').exists()
        ledger = (base / 'ledger').read_text()
        assert len(ledger.splitlines()) == 1 and ledger.startswith('ok\t'), ledger
        parts.append({
            'part': part,
            'pass': int(terminal[0][0]),
            'fail': int(terminal[0][1]),
            'runtime': terminal[0][2],
            'command_coverage': re.findall(r'DIFFER COMMAND COVERAGE: ([^\n]+)', text),
            'geometry_skips': sorted(set(re.findall(r'differ (\w+) .*SKIP \(([^\n]+)\)', text))),
            'output': str(log.relative_to(ROOT)),
            'output_sha256': digest(log),
            'ledger': ledger.strip(),
        })
    report[engine] = {
        'job_receipt': str(receipt.relative_to(ROOT)),
        'job_receipt_sha256': digest(receipt),
        'binary_sha256': job['binary_sha256'],
        'plan_sha256': digest(plan_path),
        'plan': plan,
        'parts': parts,
    }

(OUT / 'final-differ.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({engine: [(r['part'], r['pass'], r['fail']) for r in arm['parts']]
                  for engine, arm in report.items()}, indent=2))
