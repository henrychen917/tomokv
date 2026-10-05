#!/usr/bin/env python3
"""Link the same serverless witness object to frozen PRE objects, then prove controls.

Run after building both release arms and execabort-watch-{unit,db0-unit}.
Does not build or start a server. Run from the worktree root.
"""
import json
from pathlib import Path
import subprocess

pre = Path('build/gt13split-pre')
ns = [str(p) for p in sorted((pre / 'src').rglob('*.o')) if p.name != 'main.o']
db = [str(p) for p in sorted((pre / 'db0/src').rglob('*.o')) if p.name != 'main.o']
assert ns and db
for variant, witness, objects in (
        ('unit', 'build/tests/execabort_watch_unit.o', ns),
        ('db0-unit', 'build/db0/tests/execabort_watch_unit.o', db + ns)):
    command = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread',
               witness, *objects, '-o', str(pre / ('execabort-watch-' + variant)),
               '-ljemalloc', '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
    (pre / (variant + '-link.json')).write_text(json.dumps(command, indent=2) + '\n')
    subprocess.run(command, check=True)

runs = 0
with Path('docs/gt13split/execabort-witness.log').open('w') as log:
    for arm, directory in [('PRE', pre), ('POST', Path('build'))]:
        for variant in ['unit', 'db0-unit']:
            for mode in ['1s', '2s']:
                for atomic in ['0', '1']:
                    for control in ['armed', 'no-watch', 'no-error', 'no-arm']:
                        command = ['taskset', '-c', '112-119',
                                   str(directory / ('execabort-watch-' + variant)),
                                   mode, control, atomic]
                        result = subprocess.run(command, stdout=subprocess.PIPE,
                                                stderr=subprocess.STDOUT, text=True, timeout=15)
                        log.write(f'{arm} {variant} {mode} atomic={atomic} {control}: '
                                  f'exit={result.returncode}\n' + result.stdout)
                        log.flush()
                        expected = int(control == 'no-arm' or (arm == 'PRE' and control == 'armed'))
                        assert result.returncode == expected, (command, result.stdout)
                        if control == 'no-arm':
                            assert 'WATCH window never armed' in result.stdout
                        if arm == 'PRE' and control == 'armed':
                            assert 'later_set=blocked denied=1024' in result.stdout
                            assert 'waits_after=1025 deferred=1' in result.stdout
                        runs += 1
print(f'{runs} runs: PRE stalls; POST completes; no-watch/no-error pass; no-arm fails')
