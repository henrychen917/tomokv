#!/usr/bin/env python3
"""Offline ST2 artifacts. Builds serverless fixtures; never starts a server."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from lbstall_artifacts import Elf


def pad(source, output):
    before = Elf(source)
    assert before.kind != 1 and Path(source).resolve() != Path(output).resolve()
    matches = [s for s in before.functions().values()
               if s['name'].startswith('_ZN') and 'storesize_published_route' in s['name']]
    assert len(matches) == 2, 'both independent database images must be controlled'
    data = bytearray(before.data)
    changed = []
    for symbol in matches:
        body = before.body(symbol)
        prefix = 4 if body.startswith(bytes.fromhex('f30f1efa')) else 0
        assert body[prefix:] == bytes.fromhex('b801000000c3'), body.hex()
        section = before.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3] + prefix + 1
        data[offset] = 0  # mov eax,1 -> mov eax,0; instruction/text sizes unchanged
        changed.append(offset)
    Path(output).write_bytes(data)
    Path(output).chmod(Path(source).stat().st_mode)
    after = Elf(output)
    assert before.sections == after.sections and before.symbols == after.symbols
    assert [i for i, (a, b) in enumerate(zip(before.data, data)) if a != b] == sorted(changed)
    return dict(kind='A: behaviour twin',
                behavior='PRE monitoring census routes; POST text sizes, symbol addresses and counter-maintenance code',
                changed_bytes=len(changed), source=str(source), output=str(output),
                source_sha256=hashlib.sha256(before.data).hexdigest(),
                sha256=hashlib.sha256(data).hexdigest())


def pre_unit(root):
    root = Path(root)
    source = root / 'source'
    assert (source / 'src/cmd/multidb.cc').exists(), 'archive frozen PRE sources first'
    output = root / 'instrumented'
    output.mkdir(exist_ok=True)
    subprocess.run(['python3', 'tests/storesize_checks.py', str(source / 'src/cmd/multidb.cc'),
                    str(output / 'multidb.cc')], check=True)
    flags = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
             '-DTOMO_JEMALLOC', '-I' + str(source), '-I' + str(source / 'src/cmd')]
    objects = []
    # Sequential: keep build output deterministic and do not compete with the
    # candidate make for the same object paths.
    for variant in ('multi', 'db0'):
        extra = [] if variant == 'multi' else ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        for name, path in [('unit', 'tests/storesize_unit.cc'), ('multidb', output / 'multidb.cc')]:
            obj = output / f'{variant}-{name}.o'
            subprocess.run(flags + extra + ['-c', str(path), '-o', str(obj)], check=True)
            objects.append(obj)
    for directory in (root / 'src', root / 'db0/src'):
        objects += [p for p in sorted(directory.rglob('*.o'))
                    if p.relative_to(directory).as_posix() not in ('main.o', 'cmd/xshard.o')
                    and p.name != 'multidb.o']
    subprocess.run(['g++', '-pthread', *map(str, objects), '-o', str(root / 'unit'),
                    '-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    pre = sub.add_parser('pre-unit')
    pre.add_argument('root')
    twin = sub.add_parser('pad')
    twin.add_argument('source'); twin.add_argument('output')
    args = parser.parse_args()
    if args.action == 'pre-unit':
        pre_unit(args.root)
    else:
        print(json.dumps(pad(args.source, args.output), indent=2))
