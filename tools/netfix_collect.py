#!/usr/bin/env python3
"""Retain netfix gate attempts and their verdicts without turning retries into passes."""
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/netfix/evidence'


def main():
    archives = EVIDENCE / 'gate-attempts'
    archives.mkdir(exist_ok=True)
    runs = {}
    for log in sorted(EVIDENCE.glob('*.log')):
        text = log.read_text(errors='replace')
        for match in re.finditer(r'^  artifacts: (.*)$', text, re.M):
            directory = Path(match[1])
            if directory.parent != ROOT / 'build' or not directory.is_dir():
                continue
            entry = runs.setdefault(directory.name, dict(directory=str(directory), logs=[], jobs={}))
            entry['logs'].append(str(log.relative_to(ROOT)))
            entry['summary'] = [line for line in text.splitlines() if line.startswith('GATE(PARTIAL):')]
            for job in sorted((directory / 'jobs').iterdir()):
                if not job.is_dir():
                    continue
                done, ledger = job / 'done', job / 'ledger'
                entry['jobs'][job.name] = dict(
                    done=done.read_text().strip() if done.exists() else None,
                    rows=ledger.read_text().splitlines() if ledger.exists() else [])
    for name, entry in runs.items():
        directory = Path(entry['directory'])
        # Only completed attempts are frozen. Live logs must not be misrepresented
        # as a complete archive. Keep logs for aborted attempts in the source tree.
        if not entry['summary']:
            continue
        archive = archives / (name + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as out:
            for path in sorted(directory.rglob('*')):
                if not path.is_file() or path.suffix in ('.key', '.crt', '.pem', '.o'):
                    continue
                if (path.suffix in ('.log', '.txt', '.json', '.tsv', '.sh') or
                    path.name in ('done', 'ledger', 'ledger.partial', 'timings', 'complete')):
                    out.add(path, arcname=str(Path(name) / path.relative_to(directory)))
        entry['archive'] = str(archive.relative_to(ROOT))
    (EVIDENCE / 'gate-runs.json').write_text(json.dumps(runs, indent=2) + '\n')
    print(f'{len(runs)} attempts recorded; only completed attempts archived')


def copy(run, job, dest):
    """Replace one per-row evidence directory with a completed gate job's small text receipts."""
    source = Path(run) / 'jobs' / job
    assert (source / 'done').exists() and (source / 'ledger').exists(), source
    dest = Path(dest)
    assert dest.parent == EVIDENCE, dest
    if dest.exists():
        for path in dest.iterdir():
            assert path.is_file(), path
            path.unlink()
    dest.mkdir(exist_ok=True)
    for name in ('ledger', 'output.log', 'proof.log'):
        shutil.copy2(source / name, dest / name)
    proof = source / 'proof'
    for path in sorted(proof.glob('*.json')):
        shutil.copy2(path, dest / path.name)
    for leg in sorted(path for path in proof.iterdir() if path.is_dir() and path.name != 'certs'):
        if (leg / 'command.json').exists():
            shutil.copy2(leg / 'command.json', dest / (leg.name + '-command.json'))
    print(f'{dest.relative_to(ROOT)} <- {source}')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--copy']:
        copy(*sys.argv[2:5])
    else:
        main()
