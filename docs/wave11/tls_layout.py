#!/usr/bin/env python3
"""Record ELF TLS coordinates without changing the strict body comparison."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(64, 96)))


def read(path):
    sections = subprocess.check_output(['readelf', '-lW', str(path)], text=True)
    fields = next(s.split() for s in sections.splitlines() if s.lstrip().startswith('TLS '))
    extent, alignment = int(fields[5], 16), int(fields[-1], 16)
    aligned = (extent + alignment - 1) // alignment * alignment
    symbols = {}
    for line in subprocess.check_output(['readelf', '-sW', str(path)], text=True).splitlines():
        f = line.split()
        if len(f) == 8 and f[3] == 'TLS':
            symbols[f[7]] = dict(offset=int(f[1], 16), size=int(f[2]),
                                 tp_offset=int(f[1], 16) - aligned)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                extent=extent, alignment=alignment, aligned=aligned, symbols=symbols)


if __name__ == '__main__':
    arms = {a: read(ROOT / 'build/wave11' / ('tomokv-' + a)) for a in ('PRE', 'POST', 'PAD-A')}
    assert arms['POST']['extent'] == arms['PAD-A']['extent']
    assert arms['POST']['alignment'] == arms['PAD-A']['alignment']
    differences = []
    for name, symbol in arms['POST']['symbols'].items():
        other = arms['PAD-A']['symbols'].get(name)
        if other != symbol:
            differences.append(dict(name=name, post=symbol, pad=other))
    result = dict(arms=arms, post_pad_differences=differences)
    (ROOT / 'docs/wave11/tls-layout.json').write_text(json.dumps(result, indent=2) + '\n')
    print('POST/PAD-A TLS extent', arms['POST']['extent'], 'symbol differences', len(differences))
