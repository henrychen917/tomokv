#!/usr/bin/env python3
"""Recreate the disposable headline object tree for the instruction probes."""
import io
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'build/wave9/pre-source'
os.sched_setaffinity(0, set(range(64, 96)))
if DEST.exists():
    raise SystemExit(f'Refusing to overwrite an existing source arm: {DEST}')
DEST.mkdir(parents=True)
archive = subprocess.check_output(['git', 'archive', 'a214652ec', 'src', 'third_party',
                                   'Makefile', 'tools/assert_map.py'], cwd=ROOT)
with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
    stream.extractall(DEST, filter='data')
subprocess.run(['make', '-j32', 'all'], cwd=DEST, check=True)
