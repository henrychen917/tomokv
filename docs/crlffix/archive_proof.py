#!/usr/bin/env python3
"""Keep compact, complete gate receipts; omit copied upstream trees and databases."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'proof'
OUT.mkdir(exist_ok=True)
RUNS = {
    'pre-row': 'gate-pre-final',
    'post-broad-initial': 'gate-post',
    'post-broad': 'gate-final',
    'post-row': 'gate-final-row',
    'post-tcl-isolated': 'gate-tcl-isolated',
    'post-epoll': 'gate-epoll',
    'post-uring': 'gate-uring-final',
    'broken': 'gate-broken',
    'pad-a': 'gate-pad-final',
    'differ-epoll': 'differ-epoll',
    'differ-uring': 'differ-uring',
}


def main():
    index = {}
    for label, logname in RUNS.items():
        log = ROOT / 'build/crlffix' / (logname + '.log')
        if not log.exists(): continue
        text = log.read_text()
        match = re.search(r'^  artifacts: (.+)$', text, re.M)
        assert match, log
        run = Path(match[1])
        verdict = re.search(r'GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL;', text)
        index[label] = dict(run=str(run), complete=bool(verdict))
        if not verdict: continue
        index[label].update(passed=int(verdict[1]), failed=int(verdict[2]))
        selected = {log}
        for name in ('ledger.partial', 'timings.partial', 'plan.sh', 'differ-plan.json', 'phases.tsv'):
            if (run / name).exists(): selected.add(run / name)
        for job in (run / 'jobs').iterdir():
            for name in ('ledger', 'done', 'timings', 'output.log', 'crlffix.log'):
                if (job / name).exists(): selected.add(job / name)
            if job.name == 'crlffix':
                selected.update((job / 'proof').rglob('*.json'))
            if job.name == 'redis_tcl':
                selected.update(job.glob('redis-tcl-*/summary.json'))
                selected.update(job.glob('redis-tcl-*.log'))
            if job.name.startswith('differ-'):
                selected.update(p for p in (job / 'differ').rglob('*')
                                if p.is_file() and p.suffix in ('.json', '.log', '.txt', '.tsv', '.resp'))
            if job.name == 'production_units':
                selected.update(job.glob('*.log'))
                selected.update((run / 'unit-ready').glob('*'))
        dest = OUT / (label + '.tar.gz')
        with dest.open('wb') as raw:
            with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode='w') as archive:
                    for p in sorted(selected):
                        name = 'gate.log' if p == log else str(p.relative_to(run))
                        archive.add(p, arcname=name, recursive=False)
        index[label].update(archive=str(dest.relative_to(ROOT)), files=len(selected),
                            sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
    for name in ('gates-test', 'gates-test-final', 'pre-build', 'post-v2-build', 'units-final-build'):
        source = ROOT / 'build/crlffix' / (name + '.log')
        if source.exists():
            (OUT / (name + '.log.gz')).write_bytes(gzip.compress(source.read_bytes(), mtime=0))
    (OUT / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps(index, indent=2))


if __name__ == '__main__':
    main()
