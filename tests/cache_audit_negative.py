#!/usr/bin/env python3
"""Prove the layout witness rejects each removed mechanism; never execute a server."""
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/audit/negative'


def disabled_layout(text, arm, boundary):
    declarations, locks = text.split(boundary, 1)
    return (declarations.replace(f'TOMO_CACHE_AUDIT_ARM >= {arm}', 'TOMO_CACHE_AUDIT_ARM >= 6')
            .replace(f'TOMO_CACHE_AUDIT_ARM < {arm}', 'TOMO_CACHE_AUDIT_ARM < 6') +
            boundary + locks)


def main():
    assert os.sched_getaffinity(0) <= set(range(112, 128)), 'pin to 112-127'
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    cases = [
        ('parked', 'src/core/thread.h', 1, '\nstruct ThreadCtxLayoutLock {'),
        ('reply', 'src/exec/op.h', 2, '\nstruct OpLayoutLock {'),
        ('nchan', 'src/core/thread.h', 3, '\nstruct ThreadCtxLayoutLock {'),
        ('rob', 'src/net/rob.h', 4, '\nstruct RobLayoutLock {'),
        ('allocation', 'src/core/shard.h', None, None),
        ('deallocation', 'src/core/shard.h', None, None),
    ]
    results = []
    for name, header, arm, boundary in cases:
        folder = OUT / name
        shutil.copytree(ROOT / 'src', folder / 'src', dirs_exist_ok=True)
        target = folder / header
        target.parent.mkdir(parents=True, exist_ok=True)
        original = (ROOT / header).read_text()
        if arm:
            mutant = disabled_layout(original, arm, boundary)
        elif name == 'allocation':
            mutant = original.replace('::operator new(bytes, std::align_val_t{kAllocationAlignment})',
                                      '::operator new(bytes, std::align_val_t{16})')
        else:
            mutant = original.replace('::operator delete(ptr, std::align_val_t{kAllocationAlignment})',
                                      '::operator delete(ptr, std::align_val_t{16})')
        assert mutant != original, f'{name}: mutation did not apply'
        target.write_text(mutant)
        binary = folder / 'witness'
        compile = subprocess.run(['g++', '-std=c++20', '-O2', '-Wall', '-Wextra', '-pthread',
                                  '-DTOMO_CACHE_AUDIT_ARM=5', '-I', str(folder), '-I', str(ROOT),
                                  str(ROOT / 'tests/cache_layout_test.cc'), '-o', str(binary)],
                                 text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (folder / 'compile.log').write_text(compile.stdout)
        if arm:
            assert compile.returncode != 0 and 'static assertion failed' in compile.stdout, name
            reason = 'compile-time separation lock'
        else:
            assert compile.returncode == 0, compile.stdout
            probe = subprocess.run([str(binary), '5'], text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
            (folder / 'run.log').write_text(probe.stdout)
            assertion = 'requested_alignment == 64' if name == 'allocation' else 'deleted_alignment == 64'
            assert probe.returncode != 0 and assertion in probe.stdout, (name, probe.stdout)
            reason = 'runtime allocator-overload witness'
        results.append(dict(mutant=name, rejected_by=reason))
        print(f'PASS: {name} removed -> rejected by {reason}', flush=True)
    (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
