#!/usr/bin/env python3
"""Build literal-budget test arms from PRE objects; never starts a server."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
base = root / 'build/deadswitch/pre'
source = subprocess.check_output(['git', 'show',
    'deadswitch-before-20261009:src/persist/aof.cc'], cwd=root, text=True)
needle = 'constexpr uint32_t kWriterFramesPerPass = 16;'
assert source.count(needle) == 1
for budget in (1, 4096):
    arm = root / f'build/deadswitch/aof-{budget}'
    assert not arm.exists(), f'refuse to overwrite {arm}'
    subprocess.run(['cp', '-a', '--reflink=auto', str(base), str(arm)], check=True)
    copied = root / f'build/deadswitch/aof-source-{budget}/aof.cc'
    copied.parent.mkdir(parents=True, exist_ok=True)
    copied.write_text(source.replace(needle, f'constexpr uint32_t kWriterFramesPerPass = {budget};'))
    commands = []
    with (arm.parent / f'aof-{budget}-build.log').open('w') as log:
        for ns in ('', 'db0/'):
            target = str((arm / f'{ns}src/persist/aof.o').relative_to(root))
            plan = subprocess.check_output(['make', '-n', '-B',
                f'BUILD_ROOT={arm.relative_to(root)}', target], cwd=root, text=True)
            command = next(shlex.split(line) for line in plan.splitlines()
                           if ' -c src/persist/aof.cc ' in line)
            command[command.index('src/persist/aof.cc')] = str(copied.relative_to(root))
            command += ['-iquote', 'src/persist']
            commands.append(command)
            subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
        plan = subprocess.check_output(['make', '-n', f'BUILD_ROOT={arm.relative_to(root)}',
                                        'all'], cwd=root, text=True)
        command = next(shlex.split(line) for line in plan.splitlines()
                       if f' -o {arm.relative_to(root)}/tomokv ' in line)
        commands.append(command)
        subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    (root / f'docs/deadswitch/02-aof-{budget}-commands.json').write_text(
        json.dumps(commands, indent=2) + '\n')
    print(f'Built {arm.relative_to(root)}/tomokv', flush=True)
