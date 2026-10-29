#!/usr/bin/env python3
"""Archive completed selected-job evidence without disposable checkouts or data."""
import argparse, hashlib, json, os, re, subprocess, tarfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(32, 48))
p = argparse.ArgumentParser()
p.add_argument('names', nargs='*')
p.add_argument('--final', action='store_true')
a = p.parse_args()
receipts = ROOT / 'docs/scriptfix3/jobs'
output = ROOT / 'docs/scriptfix3/job-archives'
output.mkdir(exist_ok=True)
names = a.names or [f.stem for f in sorted(receipts.glob('*.json'))]
index = []
for name in names:
    receipt = json.loads((receipts / (name + '.json')).read_text())
    run = Path(receipt['artifacts'])
    assert run.is_relative_to(ROOT / 'build')
    archive = output / (name + '.tar.gz')
    inventory = output / (name + '.json')
    if not inventory.exists():
        assert not archive.exists(), 'incomplete archive must be examined first'
        rows = []
        with tarfile.open(archive, 'w:gz', compresslevel=6) as tar:
            for source in sorted(run.rglob('*')):
                relative = source.relative_to(run)
                if not source.is_file() or source.is_symlink():
                    continue
                if any(part in ('checkout', 'data', '__pycache__') for part in relative.parts):
                    continue
                data = source.read_bytes()
                assert not data.startswith(b'\x7fELF'), str(source)
                tar.add(source, arcname=str(relative), recursive=False)
                rows.append(dict(path=str(relative), bytes=len(data),
                                 sha256=hashlib.sha256(data).hexdigest()))
        inventory.write_text(json.dumps(dict(run=str(run), files=rows,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest()), indent=2) + '\n')
    saved = json.loads(inventory.read_text())
    assert saved['archive_sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    index.append(dict(name=name, exit=receipt['exit'], summary=receipt['summary'],
        binary_sha256=receipt['binary_sha256'], binary_unchanged=receipt['binary_unchanged'],
        archive=str(archive.relative_to(ROOT)), sha256=saved['archive_sha256'],
        files=len(saved['files'])))
(ROOT / 'docs/scriptfix3/proof-archives.json').write_text(json.dumps(index, indent=2) + '\n')
print(json.dumps(index, indent=2))

if a.final:
    required = ['final-uring', 'final-epoll', 'final-fused-uring', 'final-fused-epoll',
        'bounds-1s-uring-a0', 'bounds-1s-epoll-a0', 'bounds-2s-uring-a0', 'bounds-2s-epoll-a0',
        'script-persistence-split', 'script-persistence-fused', 'pre-behavior', 'pad-a-behavior']
    by_name = {row['name']: row for row in index}
    assert set(required) <= by_name.keys(), 'unfinished required proof'
    arm_hashes = json.loads((ROOT / 'docs/scriptfix3/binaries.json').read_text())
    for arm in arm_hashes.values():
        assert hashlib.sha256((ROOT / arm['path']).read_bytes()).hexdigest() == arm['sha256']
    assert hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest() == arm_hashes['POST']['sha256']
    completed = []
    for name in required:
        row = by_name[name]
        arm = 'PRE' if name == 'pre-behavior' else 'PAD-A' if name == 'pad-a-behavior' else 'POST'
        assert row['binary_unchanged'] and row['binary_sha256'] == arm_hashes[arm]['sha256']
        match = re.fullmatch(r'GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL;.*', row['summary'][0])
        assert match
        completed.append(dict(name=name, arm=arm, passed=int(match[1]), failed=int(match[2]), exit=row['exit']))
    fresh = []
    for old in json.loads((ROOT / 'docs/scriptfix3/freshness.json').read_text()):
        run = subprocess.run(old['argv'], cwd=ROOT, capture_output=True, text=True)
        fresh.append(dict(argv=old['argv'], exit=run.returncode, stdout=run.stdout, stderr=run.stderr))
    (ROOT / 'docs/scriptfix3/final-freshness.json').write_text(json.dumps(fresh, indent=2) + '\n')
    differ = []
    for name in ('final-uring', 'final-epoll'):
        receipt = json.loads((receipts / (name + '.json')).read_text())
        run = Path(receipt['artifacts'])
        plan = json.loads((run / 'differ-plan.json').read_text())
        parts = []
        for part in ('split-0','split-1','armed-0','armed-1','equivalence'):
            data = json.loads((run / 'jobs' / ('differ-' + part) / 'differ/complete.json').read_text())
            assert data['complete']
            parts.append(dict(part=part, comparisons=data['comparisons']))
        differ.append(dict(name=name, seeds=plan['manifest']['seeds'], parts=parts,
            fused_sort='unchanged stock exclusion; this suite requires split 6:2'))
    proof = dict(jobs=completed, post_passed_row_executions=sum(row['passed'] for row in completed if row['arm']=='POST'),
        final_failed_rows=sum(row['failed'] for row in completed), differ=differ,
        freshness_checks=len(fresh), freshness_failures=sum(row['exit'] != 0 for row in fresh),
        intermediate_failure='compatibility: fused Tcl unit/tracking timeout; preserved separately, final Tcl job passed both modes',
        DQ=0, DF=0, performance='NOT RUN: maintainer-owned')
    (ROOT / 'docs/scriptfix3/proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, indent=2))
    assert not proof['final_failed_rows'] and not proof['freshness_failures']
    assert all(row['exit'] == 0 for row in completed)
