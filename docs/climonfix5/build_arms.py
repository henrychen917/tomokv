#!/usr/bin/env python3
"""Build immutable comparison inputs inside this lane; never boot a server."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'build/climonfix5'
DOC = ROOT / 'docs/climonfix5'
COMMITS = {'pre': '393d6ceb1', 'c4': 'c369ccc41'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    os.sched_setaffinity(0, set(range(16, 32)))
    BUILD.mkdir(parents=True, exist_ok=True)
    for arm in sys.argv[1:] or COMMITS:
        source = BUILD / (arm + '-source')
        source.mkdir(exist_ok=True)
        commit = subprocess.check_output(['git', 'rev-parse', COMMITS[arm]], cwd=ROOT, text=True).strip()
        archive = subprocess.check_output(['git', 'archive', commit, 'src', 'third_party',
                                          'Makefile', 'tools/assert_map.py'], cwd=ROOT)
        if not (source / 'Makefile').exists():
            with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
                stream.extractall(source, filter='data')
        command = ['make', '-j16', 'all']
        with (DOC / (arm + '-build.log')).open('w') as log:
            subprocess.run(command, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['make', '-q', 'all'], cwd=source, check=True)
        binary = BUILD / ('tomokv-' + arm.upper())
        binary.write_bytes((source / 'build/tomokv').read_bytes())
        binary.chmod(0o755)
        record = dict(commit=commit, archive_sha256=hashlib.sha256(archive).hexdigest(),
                      command=command, affinity=list(range(16, 32)), binary=str(binary),
                      sha256=sha(binary), fresh=True)
        (DOC / (arm + '-build.json')).write_text(json.dumps(record, indent=2) + '\n')
        print(arm, record['sha256'], flush=True)

if __name__ == '__main__':
    main()
