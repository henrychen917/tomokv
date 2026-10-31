#!/usr/bin/env python3
"""Re-fold the gate's standard differential receipts and retain their frozen plans."""
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave12'
sys.path.insert(0, str(ROOT / 'tests'))
import differ_fanout as fanout


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    output = []
    post = digest((ROOT / 'build/wave12/tomokv-POST').read_bytes())
    for engine in ('uring', 'epoll'):
        receipt = json.loads((DOC / f'jobs/landing-differ-{engine}.json').read_text())
        assert receipt['exit'] == 0 and receipt['binary_sha256'] == post
        assert receipt['source_tree_unchanged'] and receipt['tests_tools_unchanged']
        assert receipt['env']['GATE_DIFFER_NET_IO'] == engine
        run = Path(receipt['artifacts'])
        plan = fanout.load_plan(run / 'differ-plan.json')
        assert plan['manifest']['permanent'] == [7, 19] and plan['repeats'] == 4
        folds = {group: fanout.fold(plan, group, run) for group in ('split', 'armed')}
        files = [run / 'differ-plan.json']
        logs = []
        for part in fanout.PARTS:
            directory = run / 'jobs' / ('differ-' + part)
            files += [directory / 'done', directory / 'ledger', directory / 'family.tsv']
            proof = directory / 'differ'
            files += sorted(proof.rglob('*.json')) + sorted(proof.rglob('*.tsv'))
            assert not (proof / 'proof-seeds.json').exists(), 'focused proof is not standard coverage'
            for path in sorted(proof.rglob('*.log')):
                data = path.read_bytes()
                logs.append(dict(path=str(path.relative_to(ROOT)), bytes=len(data), sha256=digest(data)))
        archives = []
        for path in dict.fromkeys(files):
            data = path.read_bytes()
            destination = DOC / 'differ-proofs' / engine / (str(path.relative_to(run)) + '.gz')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(gzip.compress(data, mtime=0))
            archives.append(dict(path=str(path.relative_to(ROOT)), sha256=digest(data),
                                 archive=str(destination.relative_to(ROOT)),
                                 archive_sha256=digest(destination.read_bytes())))
        log_data = (json.dumps(logs, indent=2) + '\n').encode()
        log_path = DOC / 'differ-proofs' / engine / 'comparison-log-hashes.json.gz'
        log_path.write_bytes(gzip.compress(log_data, mtime=0))
        output.append(dict(engine=engine, binary_sha256=post, seeds=plan['manifest'],
                           suites=plan['suites'], repeats=plan['repeats'],
                           equivalence_seeds=plan['equivalence_seeds'], folds=folds,
                           archives=archives, log_hashes=str(log_path.relative_to(ROOT)),
                           log_hashes_sha256=digest(log_path.read_bytes()),
                           passed=all(f['complete'] for f in folds.values())))
    (DOC / 'differential-proof.json').write_text(json.dumps(output, indent=2) + '\n')
    for row in output:
        print(row['engine'], row['seeds']['seeds'],
              {k: v['comparisons'] for k, v in row['folds'].items()}, row['passed'])


if __name__ == '__main__':
    main()
