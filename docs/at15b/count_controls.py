#!/usr/bin/env python3
"""Break each INFO count source independently in throwaway serverless binaries."""
from pathlib import Path
import shlex
import subprocess

directory = Path('build/at15b-count-controls')
directory.mkdir(exist_ok=True)
line = next(line for line in Path('build/at15b-witness-build.log').read_text().splitlines()
            if ' -o build/at15-unit ' in line)
link = shlex.split(line)
with Path('docs/at15b/count-controls.log').open('w') as log:
    for name, source, witness in (
        ('transaction-zero', 'multi_admin', 'subexpiry counts hashes once and observes private field TTL transitions'),
        ('ordinary-zero', 'multidb', 'ordinary INFO exact subexpiry census'),
    ):
        text = Path('src/cmd/' + source + '.cc').read_text()
        old = 'row.subexpiry += slot && *slot && !(*slot)->empty();'
        assert text.count(old) == 1
        path = directory / (name + '.cc')
        path.write_text(text.replace(old, '(void)slot; // negative control: count always stays zero'))
        obj, binary = path.with_suffix('.o'), path.with_suffix('')
        compile_command = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra',
                           '-march=native', '-pthread', '-DTOMO_JEMALLOC', '-I.', '-Isrc/cmd',
                           '-c', str(path), '-o', str(obj)]
        subprocess.run(compile_command, check=True)
        command = link.copy()
        command[command.index('build/src/cmd/' + source + '.o')] = str(obj)
        command[command.index('-o') + 1] = str(binary)
        subprocess.run(command, check=True)
        result = subprocess.run([str(binary), '2s', 'subexpiry'], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        log.write('$ ' + shlex.join(compile_command) + '\n$ ' + shlex.join(command) + '\n')
        log.write(f'{name}: exit={result.returncode}\n' + result.stdout + '\n')
        log.flush()
        assert result.returncode == 1 and witness in result.stdout, (name, result.stdout)
        print(f'PASS control {name}: rejected by {witness}', flush=True)
