#!/usr/bin/env python3
"""Build native AOF/QSBR controls from an arm's production objects."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from exec1s_pad import recipe

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arm', choices=['pre', 'post'])
    parser.add_argument('--tag', required=True)
    parser.add_argument('--aof-normal', type=Path)
    parser.add_argument('--aof-db0', type=Path)
    args = parser.parse_args()
    assert os.sched_getaffinity(0) <= set(range(8))
    source = ROOT/'build/eoffix/pre-source' if args.arm == 'pre' else ROOT
    out = ROOT/'build/eoffix'/args.tag
    out.mkdir(exist_ok=True)
    env = dict(os.environ, CXX='g++ -gz=zlib', LC_ALL='C')
    original = recipe(source, source/'build')
    original[0:1] = ['g++', '-gz=zlib']
    first = next(i for i, value in enumerate(original) if value.endswith('.o'))
    records = []
    for namespace in ['normal', 'db0']:
        obj, binary = out/(namespace+'.o'), out/namespace
        compile = original[:first] + ['-I'+str(source), '-I'+str(ROOT)]
        if namespace == 'db0': compile += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        compile += ['-c', str(ROOT/'tests/eoffix_aof.cc'), '-o', str(obj)]
        link = [x for x in original if not x.endswith('/src/main.o')]
        link[first:first] = [str(obj)]
        replacements = {'src/persist/aof.o': args.aof_normal, 'db0/src/persist/aof.o': args.aof_db0}
        link = [str(replacements[str(Path(x).relative_to(source/'build'))].resolve())
                if x.endswith('.o') and str(Path(x).relative_to(source/'build')) in replacements and
                replacements[str(Path(x).relative_to(source/'build'))] else x
                for x in link if x != str(obj)]
        link[first:first] = [str(obj)]
        link[link.index('-o')+1] = str(binary)
        for cmd in [compile, link]: subprocess.run(cmd, env=env, check=True)
        records.append(dict(namespace=namespace, compile=compile, link=link,
                            sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
    (ROOT/'docs/eoffix'/(args.tag+'-build.json')).write_text(json.dumps(records,indent=2)+'\n')


if __name__ == '__main__':
    main()
