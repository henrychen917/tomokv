#!/usr/bin/env python3
"""Retain a ccfix5 correctness receipt without converting outer gate failures to PASS."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import differ_fanout as fanout


def collect(name, group, log, exit_code):
    text = log.read_text()
    matches = re.findall(r'^  artifacts: (.+)$', text, re.M)
    assert len(matches) == 1, 'missing or ambiguous run directory'
    source = Path(matches[0])
    plan = fanout.load_plan(source / 'differ-plan.json')
    # Revalidate all journals, comparison artifacts, private rows and completions.
    folded = fanout.fold(plan, group, source)
    destination = ROOT / 'docs/ccfix5/matrices' / name
    assert not destination.exists(), 'refusing to overwrite a receipt'
    destination.mkdir(parents=True)
    shutil.copy2(log, destination / 'gate.log')
    parts = {}
    for part in folded['parts']:
        job = source / 'jobs' / ('differ-' + part)
        out = destination / part
        out.mkdir()
        output = (job / 'output.log').read_text()
        shutil.copy2(job / 'output.log', out / 'output.log')
        selected = [job / 'differ/complete.json', job / 'differ/legs.tsv']
        selected += list((job / 'differ').glob('ccfix-a*.txt'))
        selected += list((job / 'differ').glob('read-local-a*.tsv'))
        for path in selected:
            if path.exists():
                shutil.copy2(path, out / path.name)
        entry = json.loads((job / 'differ/complete.json').read_text())
        entry['verdicts'] = [line.strip() for line in output.splitlines()
                             if any(x in line for x in ('DIFFER GATE:', 'lane fired', 'differ ccfix'))]
        if part != 'equivalence':
            ccfix_logs = list((job / 'differ').glob('ccfix-a*.txt'))
            assert len(ccfix_logs) == len(plan['manifest']['seeds']), 'missing ccfix seed'
            entry['pending_windows'] = sum(path.read_text().count(
                'EXPECTED-DEVIATION CC11 pending ') for path in ccfix_logs)
            assert entry['pending_windows'] == (3 * len(ccfix_logs) if part.endswith('-1') else 0)
        if part.startswith('armed-'):
            witness = re.search(r'lane fired.*ok \(hits=(\d+) fallbacks=(\d+) at peak; '
                                r'final_hits=(\d+) final_fallbacks=(\d+)\)', output)
            assert witness and int(witness[1]) > 0, 'missing non-vacuity witness'
            entry['read_local'] = dict(zip(('peak_hits', 'peak_fallbacks', 'final_hits', 'final_fallbacks'),
                                          map(int, witness.groups())))
        parts[part] = entry
    archive = destination / 'complete-run.tar.gz'
    with tarfile.open(archive, 'w:gz') as saved:
        saved.add(source, arcname=source.name)
    record = dict(name=name, source=str(source), group=group, gate_exit_code=exit_code,
                  private_correctness_complete=True, folded=folded, parts=parts,
                  outer_ledger=(source / 'ledger.partial').read_text(),
                  archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    (destination / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('group', choices=('armed', 'split'))
    parser.add_argument('log', type=Path)
    parser.add_argument('--exit-code', required=True, type=int)
    args = parser.parse_args()
    collect(args.name, args.group, args.log, args.exit_code)
