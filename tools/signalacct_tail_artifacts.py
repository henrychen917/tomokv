#!/usr/bin/env python3
"""Serverless tail controls and isolated build trees; never starts a server.

Run under taskset -c 112-127. Builds remain ordinary Makefile builds in build/.
PAD A uses frozen 76ef4beae work-span behaviour with PAIR-POST's exact layout.
The separate release POST is required to detect the pair's code-size effect.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import signalacct_artifacts as original
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/signalacct-tail'
PRE = '76ef4beae'
LANDED = '36d1e875e'


def git_file(commit, name):
    return subprocess.check_output(['git', 'show', f'{commit}:{name}'], cwd=ROOT).decode()


def tree(name):
    dest = OUT / name.removeprefix('signalacct-')
    for directory in ('src', 'third_party', 'tests', 'tools'):
        shutil.copytree(ROOT / directory, dest / directory, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(ROOT / 'Makefile', dest / 'Makefile')
    return dest


def prepare():
    off = tree('off')
    rows = []
    for filename, name, member in [('io_loop.h', 'run_loop', True),
                                    ('reorder.cc', 'IoLoop::r7_run_loop', False)]:
        path = off / 'src/core' / filename
        source = path.read_text()
        frozen = git_file(PRE, 'src/core/' + filename)
        extract = lambda s: original.sync.function(s, name, member)
        old, current = extract(frozen), extract(source)
        indent = lambda s: '\n'.join('    ' + line if line and not line.startswith('#') else line
                                     for line in s.splitlines()) if member else s
        source = original.once(source, indent(current), indent(old))
        assert extract(source) == old
        path.write_text(source)
        rows.append(dict(path=str(path.relative_to(ROOT)),
                         frozen_body_sha256=hashlib.sha256(old.encode()).hexdigest(),
                         exact_frozen_body=True))
    original.PRE = off
    original.OUT = OUT
    original.tree = tree
    (OUT / 'reference.txt').write_text(PRE + '\n')
    pair = original.prepare_pair()
    witness = original.prepare_witness()
    (OUT / 'off-source.json').write_text(json.dumps(dict(reference=PRE, bodies=rows,
        scope='New tenure accounting compiled out; frozen busy Span envelopes. '
              'All other current code, including the closing-client fix, is common.'), indent=2) + '\n')
    print(json.dumps(dict(off=str(off), pair=str(pair), witness=str(witness)), indent=2))


def controls():
    include = OUT / 'nofix'
    path = include / 'src/core/signalacct.h'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(git_file(LANDED, 'src/core/signalacct.h'))
    rows = {}
    for arm in ('fixed', 'nofix'):
        binary = OUT / ('unit-' + arm)
        command = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native']
        if arm == 'nofix':
            command += ['-I' + str(include)]
        command += ['-I.', '-iquote', 'src/core', 'tests/signalacct_tail_unit.cc', '-o', str(binary)]
        subprocess.run(command, cwd=ROOT, check=True)
        result = subprocess.run([str(binary)], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (OUT / (arm + '-unit.log')).write_text(result.stdout)
        if arm == 'fixed':
            assert result.returncode == 0, result.stdout
        else:
            assert result.returncode == 1 and 'fix removed: eager' in result.stdout, result.stdout
        count = subprocess.check_output([str(binary), '--instructions'], cwd=ROOT, text=True)
        (OUT / (arm + '-instructions.jsonl')).write_text(count)
        with (OUT / (arm + '-unit.asm')).open('w') as log:
            subprocess.run(['objdump', '-drwC', str(binary)], stdout=log, check=True)
        rows[arm] = [json.loads(line) for line in count.splitlines()]
    for pre, post in zip(rows['nofix'], rows['fixed']):
        assert pre['trace'] == post['trace'] and pre['passes'] == post['passes']
        assert pre['publications'] == pre['passes']
        assert pre['clocks'] == post['clocks']
        assert pre['instructions_per_pass'] - post['instructions_per_pass'] > 10, (pre, post)
    rows['negative_control'] = 'Frozen landed header rejects the store-count proof and restores extra instructions'
    rows['scope'] = 'Retired user instructions in a finite deterministic helper fixture; no server, rate or timing measurement'
    (OUT / 'instructions.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(rows, indent=2))


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'controls', 'pair', 'manifest'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.action == 'prepare':
        prepare()
    elif args.action == 'controls':
        controls()
    elif args.action == 'pair':
        original.OUT = OUT
        original.pair(ROOT / 'build/tomokv-pair-post', ROOT / 'build/tomokv-pad-a')
    else:
        rows = []
        for name in ('tomokv', 'tomokv-off', 'tomokv-pair-post', 'tomokv-pad-a', 'tomokv-tail-witness'):
            path = ROOT / 'build' / name
            elf = Elf(path)
            rows.append(dict(arm=name, sha256=original.sha(path),
                             text_bytes=elf.sections[elf.names.index('.text')][5]))
        (OUT / 'arms.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
