#!/usr/bin/env python3
"""Offline DWARF inventory of the eight locked types and IoLoop member offsets."""
import argparse
import json
from pathlib import Path
import subprocess

LOCKS = dict(Op=336, Client=1984, ThreadCtx=1408, Shard=1440,
             FlatStore=944, **{'Rob<64>': 192}, AtomicEntry=144, Config=624)


def inventory(binary):
    script = '''import gdb, json
result = {}
for ns in ('tomo', 'tomo_db0'):
 for name in %r:
  typename = ns + '::' + name
  t = gdb.lookup_type(typename)
  fields = {}
  for f in t.fields():
   if f.name and hasattr(f, 'bitpos'):
    fields[f.name] = f.bitpos
  result[typename] = dict(size=t.sizeof, fields_bitpos=fields)
print('CLIENTFIX_LAYOUT=' + json.dumps(result, sort_keys=True))
''' % (list(LOCKS) + ['IoLoop'],)
    command = ['taskset', '-c', '112-127', 'gdb', '-nx', '--batch', str(binary),
               '-ex', 'python exec(' + repr(script) + ')']
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith('CLIENTFIX_LAYOUT=')]
    assert len(lines) == 1, result.stdout + result.stderr
    return json.loads(lines[0].split('=', 1)[1])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    before, after = inventory(args.pre), inventory(args.post)
    for namespace in ('tomo', 'tomo_db0'):
        for name, size in LOCKS.items():
            assert before[namespace + '::' + name]['size'] == size
            assert after[namespace + '::' + name]['size'] == size
    args.output.write_text(json.dumps(dict(equal=before == after, pre=before, post=after),
                                          indent=2) + '\n')
    assert before == after, 'named member offsets changed'
    print('PASS: eight layout locks and IoLoop member offsets, both namespaces')
