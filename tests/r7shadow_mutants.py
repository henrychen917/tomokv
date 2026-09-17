#!/usr/bin/env python3
"""Build throwaway scheduler defects and require the real serverless unit to fail."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin this unit builder to CPUs 112-127'
source = (ROOT / 'src/core/reorder.h').read_text()
mutants = {
    'no-shadow': (source.replace('} else if (newest_ < task.op_id) {', '} else if (false) {'),
                  'own-pipe shadows were not armed'),
    'no-clear': (source.replace('if (!shadow_bit(n.task) || shadow_pending(n.task)) continue;', 'continue;'),
                 'Done shadow was not promoted'),
    'no-bound': (source.replace('if (!priority_left_) {', 'if (false) {'),
                 'carry/ratio pick bound exceeded'),
}
for name, (header, expected) in mutants.items():
    assert header != source
    directory = ROOT / 'build' / ('r7shadow-mutant-' + name)
    path = directory / 'src/core/reorder.h'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header)
    binary = directory / 'unit'
    command = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
               '-I' + str(directory), '-I.', '-iquote', 'src/core', 'tests/r7shadow_unit.cc', '-o', str(binary)]
    with (directory / 'build.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(binary)], cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=30)
    (directory / 'unit.log').write_text(result.stdout)
    assert result.returncode == 1 and expected in result.stdout, (name, result.returncode, result.stdout)
    print('PASS rejected', name + ':', expected, flush=True)
