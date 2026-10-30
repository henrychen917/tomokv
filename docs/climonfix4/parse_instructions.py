#!/usr/bin/env python3
"""Build dispatch-only complements to the owner/scatter instruction scopes."""
import io
import argparse
import os
import subprocess
import tarfile
import instructions as scope

os.sched_setaffinity(0, set(range(16, 32)))
p = argparse.ArgumentParser()
p.add_argument('--arms', default='pre,post')
args = p.parse_args()
source = scope.ROOT / 'build/climonfix4/parse-pre'
if 'pre' in args.arms.split(','):
    source.mkdir(exist_ok=True)
    archive = subprocess.check_output(['git', 'archive', '393d6ceb1', 'src', 'third_party',
                                       'Makefile', 'tools/assert_map.py'], cwd=scope.ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(source, filter='data')
    with (source / 'build.log').open('w') as log:
        subprocess.run(['make', '-j16', 'all'], cwd=source, stdout=log,
                       stderr=subprocess.STDOUT, check=True)
scope.ARMS['pre'] = source, source / 'build'
scope.BUILD = scope.ROOT / 'build/climonfix4/parse-commands'
scope.OUT = scope.ROOT / 'docs/climonfix4/parse-build'
scope.BUILD.mkdir(exist_ok=True)
scope.OUT.mkdir(exist_ok=True)
for arm in args.arms.split(','):
    for ns in ('normal', 'db0'):
        scope.build(arm, ns, scope.ROOT / 'tests/climonfix4_scope.cc')
