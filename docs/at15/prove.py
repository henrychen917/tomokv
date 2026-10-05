#!/usr/bin/env python3
"""Same witness objects linked to frozen PRE production objects; no servers or rings."""
import json
from pathlib import Path
import subprocess
pre = Path('build/at15-pre')
ns = [str(p) for p in sorted((pre / 'src').rglob('*.o')) if p.name != 'main.o']
db = [str(p) for p in sorted((pre / 'db0/src').rglob('*.o')) if p.name != 'main.o']
for variant, witness, objects in (
        ('unit', 'build/tests/at15_unit.o', ns),
        ('db0-unit', 'build/db0/tests/at15_unit.o', db + ns)):
    command = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread',
               witness, *objects, '-o', str(pre / ('at15-' + variant)),
               '-ljemalloc', '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
    (pre / (variant + '-link.json')).write_text(json.dumps(command, indent=2) + '\n')
    subprocess.run(command, check=True)
count = 0
with Path('docs/at15/pre-post-witness.log').open('w') as log:
    for arm, directory in [('PRE', pre), ('POST', Path('build'))]:
        for variant in ('unit', 'db0-unit'):
            for mode in ('1s', '2s'):
                for case in ('info', 'sleep', 'controls', 'config'):
                    command = ['taskset', '-c', '112-127', str(directory / ('at15-' + variant)), mode, case]
                    result = subprocess.run(command, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, timeout=15)
                    log.write(f'{arm} {variant} {mode} {case} exit={result.returncode}\n' + result.stdout)
                    log.flush()
                    expected = int(arm == 'PRE' and case != 'controls')
                    assert result.returncode == expected, (command, result.stdout)
                    if expected:
                        message = {'info': 'INFO must be one bulk/verbatim element inside EXEC',
                                   'sleep': 'DEBUG SLEEP 0 EXEC element', 'config': 'queued reply'}[case]
                        assert message in result.stdout, result.stdout
                    count += 1
print(f'{count} runs: PRE fails INFO/SLEEP/CONFIG; POST passes; controls pass both arms')
