"""Retain finished correctness receipts; never synthesizes passing results."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/trackfix'


def archive(source, destination, receipt_only=False):
    if destination.exists():
        return
    files = []
    for path in sorted(source.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        if receipt_only and not (path.suffix in ('.log', '.txt', '.json', '.held', '.replayed')
                or path.name in ('ledger', 'timings', 'done', 'returncode', 'argv.json')
                or path.name.startswith('gate-srv-')):
            continue
        files.append(path)
    with tarfile.open(destination, 'w:gz') as output:
        for path in files:
            output.add(path, arcname=str(path.relative_to(source)), recursive=False)
    destination.with_suffix(destination.suffix + '.json').write_text(json.dumps(dict(
        source=str(source), files=len(files), bytes=sum(p.stat().st_size for p in files),
        sha256=hashlib.sha256(destination.read_bytes()).hexdigest()), indent=2) + '\n')


def main():
    gate_results = []
    for dest in sorted((DOC / 'proof').iterdir()):
        if not (dest / 'returncode').exists():
            continue
        log = (dest / 'gate.log').read_text(errors='replace')
        match = re.search(r'^  artifacts: (.+)$', log, re.M)
        if match:
            source = Path(match[1])
            archive(source / 'jobs', dest / 'jobs.tar.gz', receipt_only=True)
            if dest.name.endswith('newrows-final') or dest.name == 'pad-a-accounting':
                jobs = ('trackfix_accounting',) if dest.name == 'pad-a-accounting' else ('trackfix_order', 'trackfix_accounting')
                for job in jobs:
                    rows = dest / 'rows' / job
                    rows.mkdir(parents=True, exist_ok=True)
                    original = source / 'jobs' / job
                    for path in [*original.glob('order-*.log'), original / 'oracle.log']:
                        shutil.copy2(path, rows / path.name)
                    windows = {str(p.relative_to(original)): p.read_text()
                               for p in sorted(original.rglob('*'))
                               if p.suffix in ('.held', '.replayed')}
                    (rows / 'schedule-receipts.json').write_text(
                        json.dumps(windows, indent=2) + '\n')
                    failures = Counter()
                    for path in original.glob('order-*.log'):
                        for line in path.read_text().splitlines():
                            if line.startswith('FAIL '):
                                failures[line.split(': ', 1)[-1].split(':', 1)[0]] += 1
                    (rows / 'summary.json').write_text(json.dumps(dict(
                        legs=len(list(original.glob('order-*.log'))), failures=failures,
                        held=sum(k.endswith('.held') for k in windows),
                        replayed=sum(k.endswith('.replayed') for k in windows)), indent=2) + '\n')
        ledger = dest / 'ledger.partial'
        counts = Counter(line.split('\t', 1)[0] for line in ledger.read_text().splitlines()) if ledger.exists() else {}
        gate_results.append(dict(label=dest.name, returncode=int((dest / 'returncode').read_text()),
                                 passed=counts.get('ok', 0), failed=counts.get('FAIL', 0)))
    (DOC / 'gate-results.json').write_text(json.dumps(gate_results, indent=2) + '\n')

    differ_results = []
    for dest in sorted((DOC / 'differ').iterdir()):
        if not dest.is_dir() or not (dest / 'result.json').exists():
            continue
        archive(ROOT / 'build/trackfix/differ' / dest.name, dest / 'receipts.tar.gz')
        log = (dest / 'output.log').read_text()
        counts = re.search(r'DIFFER GATE: pass=(\d+) fail=(\d+)', log)
        result = json.loads((dest / 'result.json').read_text())
        result.update(passed=int(counts[1]), failed=int(counts[2]),
                      failures=[line for line in log.splitlines() if 'FAIL' in line])
        differ_results.append(result)
    (DOC / 'differ-results.json').write_text(json.dumps(differ_results, indent=2) + '\n')


if __name__ == '__main__':
    main()
