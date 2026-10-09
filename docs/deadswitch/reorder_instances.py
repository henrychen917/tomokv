#!/usr/bin/env python3
"""Fail if any production reorder queue instantiates a non-production quantum."""
import argparse
import json
from pathlib import Path
import re
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('objects', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
pattern = re.compile(r'(tomo(?:_db0)?)::r7::(ExReorderQueues|ShadowReorderQueues)<(\d+)ul>')
rows, seen = [], set()
objects = sorted(a.objects.rglob('*.o'))
assert objects, 'empty object inventory'
for obj in objects:
    evidence = {}
    for command in (['nm', '-aC'], ['objdump', '-tC']):
        lines = subprocess.check_output(command + [str(obj)], text=True).splitlines()
        evidence[command[0]] = [line for line in lines if pattern.search(line)]
        for line in evidence[command[0]]:
            seen.update(pattern.findall(line))
    if any(evidence.values()):
        rows.append(dict(object=str(obj.relative_to(a.objects)), **evidence))
result = dict(objects_scanned=len(objects), instantiations=sorted(seen), evidence=rows)
a.output.write_text(json.dumps(result, indent=2) + '\n')
expected = {(ns, queue, '32') for ns in ('tomo', 'tomo_db0')
            for queue in ('ExReorderQueues', 'ShadowReorderQueues')}
assert seen == expected, (seen, expected)
print(f'PASS: {len(objects)} objects, both queue types in both namespaces, BatchOps=32 only')
