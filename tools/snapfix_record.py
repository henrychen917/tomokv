#!/usr/bin/env python3
"""Archive one finished tests/gate.sh run (partial ledger, per-job verdicts, small results) into
docs/snapfix/proof/<name>/. Never starts a server or a gate; it only copies files that the run
already wrote and binds them to the command line and the candidate binary's SHA-256."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SMALL = 512 * 1024  # copy evidence files up to this size; larger ones are referenced by digest


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path, help='build/gate-run.XXXXXX directory')
    p.add_argument('--name', required=True)
    p.add_argument('--command', required=True, help='exact command line used')
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--log', type=Path, help='captured gate stdout/stderr')
    p.add_argument('--output-root', type=Path, default=ROOT / 'docs/snapfix/proof')
    a = p.parse_args()
    dest = a.output_root / a.name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    record = dict(run=str(a.run.resolve()), command=a.command, binary=str(a.binary.resolve()),
                  binary_sha256=sha(a.binary), files={}, referenced={}, jobs={})
    for name in ('ledger.partial', 'ledger.partial.timings', 'plan.sh', 'phases.tsv', 'families.tsv',
                 'row-timeouts.json', 'differ-plan.json'):
        src = a.run / name
        if src.exists():
            shutil.copy2(src, dest / name)
            record['files'][name] = sha(src)
    if a.log and a.log.exists():
        shutil.copy2(a.log, dest / 'gate-output.log')
        record['files']['gate-output.log'] = sha(a.log)
    for job in sorted((a.run / 'jobs').iterdir()):
        verdict = {}
        for name in ('ledger', 'done', 'timings'):
            src = job / name
            if src.exists():
                verdict[name] = src.read_text()
        record['jobs'][job.name] = verdict
        for src in sorted(job.rglob('*')):
            if not src.is_file() or src.name in ('ledger', 'done', 'timings'):
                continue
            rel = src.relative_to(a.run)
            if src.suffix in ('.json', '.log', '.txt', '.tsv') and src.stat().st_size <= SMALL:
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out)
                record['files'][str(rel)] = sha(src)
            else:
                record['referenced'][str(rel)] = dict(bytes=src.stat().st_size, sha256=sha(src))
    (dest / 'record.json').write_text(json.dumps(record, indent=2) + '\n')
    oks = sum(v.get('ledger', '').count('ok\t') for v in record['jobs'].values())
    fails = sum(v.get('ledger', '').count('FAIL\t') for v in record['jobs'].values())
    print(json.dumps(dict(name=a.name, jobs=len(record['jobs']), ok=oks, fail=fails,
                          copied=len(record['files']), referenced=len(record['referenced']))))


if __name__ == '__main__':
    main()
