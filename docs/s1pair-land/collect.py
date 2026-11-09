#!/usr/bin/env python3
"""Collect completed selected-job evidence; never starts a server or a gate."""
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'build/s1pair-land'
OUT = Path(__file__).resolve().parent
TAGS = ('pre-s1pair', 'post-s1pair', 'post-existing', 'post-differ')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    result = {'scope': 'selected correctness jobs only; no full gate or rate measurements',
              'batches': {}, 'arms': {}}
    existing = re.search(r'JOBS="(.*?)"', (OUT / 'run_existing.sh').read_text(), re.S)[1].split()
    expected = {
        'pre-s1pair': {'release', 's1pair'},
        'post-s1pair': {'release', 's1pair'},
        'post-existing': set(existing) | {'release', 'production_units'},
        'post-differ': {'release', 'differ-split-0', 'differ-split-1',
                        'differ-armed-0', 'differ-armed-1', 'differ-equivalence'},
    }
    for tag in TAGS:
        rc = int((BUILD / (tag + '.rc')).read_text())
        log = (BUILD / (tag + '.log')).read_text()
        run = Path(re.search(r'  artifacts: (.*)', log)[1])
        names = re.search(r'^PARTIAL jobs \(including prerequisites\): (.*)$', log, re.M)[1].split()
        assert len(names) == len(set(names)) and set(names) == expected[tag], (tag, names)
        jobs = []
        for name in names:
            directory = run / 'jobs' / name
            code, passed, failed = map(int, (directory / 'done').read_text().split())
            ledger = directory / 'ledger'
            rows = []
            if ledger.exists():
                for line in ledger.read_text().splitlines():
                    verdict, seconds, label = line.split('\t', 2)
                    rows.append(dict(verdict=verdict, seconds=float(seconds), label=label))
            assert sum(r['verdict'] == 'ok' for r in rows) == passed, (tag, name)
            assert sum(r['verdict'] == 'FAIL' for r in rows) == failed, (tag, name)
            jobs.append(dict(job=name, returncode=code, passed=passed, failed=failed, rows=rows,
                             artifacts=str(directory.relative_to(ROOT))))
        result['batches'][tag] = dict(returncode=rc, run=str(run.relative_to(ROOT)), jobs=jobs,
                                     passed=sum(j['passed'] for j in jobs),
                                     failed=sum(j['failed'] for j in jobs))
        for suffix in ('.log', '.ledger.partial', '.ledger.partial.timings'):
            source = BUILD / (tag + suffix)
            assert source.stat().st_size <= 1_000_000, source
            shutil.copy2(source, OUT / source.name)
    for arm in ('pre', 'post'):
        record = json.loads((BUILD / (arm + '-arm.json')).read_text())
        assert sha256(Path(record['path'])) == record['sha256'], arm
        result['arms'][arm] = record
    production = Path(result['batches']['post-existing']['run']) / 'unit-ready'
    result['fresh_unit_markers'] = sorted(p.name for p in (ROOT / production).iterdir())
    payload = json.dumps(result, indent=2) + '\n'
    assert len(payload.encode()) <= 1_000_000
    (OUT / 'job-results.json').write_text(payload)
    for tag, batch in result['batches'].items():
        print(tag, len(batch['jobs']), 'jobs;', batch['passed'], 'ok;', batch['failed'], 'FAIL;',
              'rc', batch['returncode'])


if __name__ == '__main__':
    main()
