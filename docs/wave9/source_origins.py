#!/usr/bin/env python3
"""Resolve every residual group's first POST instruction to its source location."""
import json
import subprocess
import identity

root = identity.ROOT
doc = root / 'docs/wave9/identity'
rows = json.loads((doc / 'changed-bodies.json').read_text())
binary = root / 'build/tomokv'
inventory = identity.inventory(binary)['groups']
names = [r['name'] for r in rows if not r['matches']]
addresses = [inventory[n][0]['address'] if inventory.get(n) else '0' for n in names]
lines = subprocess.check_output(['addr2line', '-e', str(binary), *addresses], text=True).splitlines()
assert len(lines) == len(names)
(doc / 'residual-source-lines.json').write_text(json.dumps(dict(zip(names, lines)), indent=2) + '\n')
