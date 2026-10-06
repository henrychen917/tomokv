#!/usr/bin/env python3
"""Relink the two distinct at15b production trees from their frozen objects.

All files written under this lane. Frozen objects are valid only while the
source/Makefile/third_party tree checks below match their recorded revision.
These are serverless candidate builds, not copies of a candidate executable.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def identity(revision):
    return [git('rev-parse', revision + ':' + name) for name in ('src', 'Makefile', 'third_party')]


assert Path('build/at15b-pre/revision').read_text().strip() == git('rev-parse', '61a9ab20f')
assert identity('HEAD') == identity('76568a8fc')
line = next(line for line in Path('build/at15b-build.log').read_text().splitlines()
            if ' -o build/tomokv ' in line)
receipts = []
for revision, root in [('61a9ab20f', 'build/at15b-pre'), ('76568a8fc', 'build')]:
    out = Path('build/at15c/bisect-' + revision)
    out.mkdir(parents=True, exist_ok=True)
    command = shlex.split(line)
    if root != 'build':
        command = [word.replace('build/db0/', root + '/db0/').replace(
            'build/src/', root + '/src/') for word in command]
    command[command.index('-o') + 1] = str(out / 'tomokv')
    with (out / 'build.log').open('w') as log:
        subprocess.run(['taskset', '-c', '112-127', *command], check=True,
                       stdout=log, stderr=subprocess.STDOUT)
    inputs = {word: hashlib.sha256(Path(word).read_bytes()).hexdigest()
              for word in command if word.endswith('.o')}
    receipt = dict(revision=git('rev-parse', revision), identity=identity(revision),
                   object_source=root, input_sha256=inputs, command=command,
                   sha256=hashlib.sha256((out / 'tomokv').read_bytes()).hexdigest())
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    receipts.append(receipt)
    print(revision, receipt['sha256'], flush=True)
Path('docs/at15c/bisect-builds.json').write_text(json.dumps(receipts, indent=2) + '\n')

# The intermediate commit names a helper absent from that revision. Compile its
# exact source in a private copy so the bisect's skip is an observed build result.
out = Path('build/at15c/bisect-bb5b461ee')
out.mkdir(parents=True, exist_ok=True)
source = out / 'multi_admin.cc'
source.write_text(git('show', 'bb5b461ee:src/cmd/multi_admin.cc') + '\n')
command = ['taskset', '-c', '112-127', 'g++', '-std=c++20', '-O2', '-g',
           '-Wall', '-Wextra', '-march=native', '-pthread', '-DTOMO_JEMALLOC',
           '-Isrc/cmd', '-I.', '-c', str(source), '-o', str(out / 'multi_admin.o')]
with (out / 'build.log').open('w') as log:
    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
assert result.returncode != 0, 'intermediate commit unexpectedly compiles; build it fully'
diagnostic = (out / 'build.log').read_text()
assert 'hash_ttls_of' in diagnostic and 'was not declared' in diagnostic, diagnostic
Path('docs/at15c/bisect-bb5b461ee-build.log').write_text(
    '$ ' + ' '.join(command) + '\n' + diagnostic + f'\nexit={result.returncode}\n')
print('bb5b461ee SKIP: hash_ttls_of was not declared', flush=True)
