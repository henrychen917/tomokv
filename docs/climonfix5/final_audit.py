#!/usr/bin/env python3
"""Verify retained arms, source, archived proof and final build freshness."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/climonfix5'
CAMPAIGNS = ('directed-final-v11', 'affected-final', 'tcl-final', 'replyoff-final',
             'differ-uring', 'differ-epoll', 'pad-boot')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    os.sched_setaffinity(0, set(range(16, 32)))
    os.environ['LC_ALL'] = 'C'
    arms = json.loads((DOC / 'arms.json').read_text())
    campaigns = []
    for name in CAMPAIGNS:
        record = json.loads((DOC / 'jobs' / (name + '.json')).read_text())
        assert record['exit'] == record['failed'] == 0, name
        assert record['binary_unchanged'], name
        expected = arms['PAD-A' if name == 'pad-boot' else 'POST']['sha256']
        assert record['binary_sha256'] == expected, name
        campaigns.append(dict(name=name, passed=record['passed'], failed=record['failed'],
                              receipt_sha256=digest(DOC / 'jobs' / (name + '.json'))))
    freshness = []
    unit_audit = json.loads((DOC / 'production-units.json').read_text())
    for row in unit_audit['rows']:
        if row['name'] == 'make all':
            continue
        result = subprocess.run(row['command'], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        freshness.append(dict(name=row['name'], command=row['command'],
                              exit=result.returncode, output=result.stdout))
    assert len(freshness) == 57
    (DOC / 'final-freshness.json').write_text(json.dumps(freshness, indent=2) + '\n')
    assert all(row['exit'] == 0 for row in freshness), 'stale production unit'
    identities = []
    for name in ('PRE', 'C4', 'POST', 'PAD-A'):
        arm = arms[name]
        actual = digest(ROOT / arm['path'])
        assert actual == arm['sha256'], name
        identities.append(dict(arm=name, path=arm['path'], sha256=actual))
    for row in arms['oracle']:
        assert digest(Path(row['path'])) == row['sha256'], row['path']
    for path in ('build/tomokv', 'build/tomokv-climonfix5-POST'):
        assert digest(ROOT / path) == arms['POST']['sha256'], path
    source = json.loads((DOC / 'source-identity.json').read_text())
    for path, expected in source.items():
        if path.startswith(('src/', 'tests/', 'docs/')):
            assert digest(ROOT / path) == expected, path
    subprocess.run(['git', 'diff', '--exit-code', 'e4a0e13ab', '--', 'src'],
                   cwd=ROOT, check=True)
    subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)
    counts = json.loads((DOC / 'instruction-summary.json').read_text())
    assert counts['pass'] and len(counts['inputs']) == 852
    for row in counts['inputs']:
        assert digest(ROOT / row['file']) == row['sha256'], row['file']
    archives = []
    for row in json.loads((DOC / 'job-evidence-index.json').read_text()):
        path = ROOT / row['archive']
        assert digest(path) == row['archive_sha256'], path
        with tarfile.open(path, 'r:gz') as archive:
            manifest = json.load(archive.extractfile('climonfix5-archive-manifest.json'))
            for member in manifest:
                data = archive.extractfile(member['path']).read()
                assert len(data) == member['bytes'], (path, member['path'])
                assert hashlib.sha256(data).hexdigest() == member['sha256'], (path, member['path'])
        archives.append(dict(path=row['archive'], sha256=row['archive_sha256'], files=len(manifest)))
    for stem in ('scope', 'development'):
        index = json.loads((DOC / (stem + '-log-index.json')).read_text())
        path = DOC / (stem + '-logs.tar.gz')
        assert digest(path) == index['archive_sha256'], path
        with tarfile.open(path, 'r:gz') as archive:
            for member in index['files']:
                data = archive.extractfile(member['path']).read()
                assert len(data) == member['bytes']
                assert hashlib.sha256(data).hexdigest() == member['sha256'], member['path']
        archives.append(dict(path=str(path.relative_to(ROOT)), sha256=digest(path), files=len(index['files'])))
    result = dict(production_source='e4a0e13ab', arms=identities, campaigns=campaigns,
                  freshness_checks=len(freshness), instruction_inputs=len(counts['inputs']),
                  archives=archives, passed=True)
    (DOC / 'artifact-integrity.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(campaigns=len(campaigns), freshness=len(freshness),
                         archives=len(archives), passed=True)))


if __name__ == '__main__':
    main()
