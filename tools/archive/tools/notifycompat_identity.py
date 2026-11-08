#!/usr/bin/env python3
"""Per-commit GET/SET/MGET/MSET object-code diagnostic (no runtime workload)."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from ccfix_audit import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    rows = []
    pattern = re.compile(r'::cmd_(?:get|set)<false|::(?:xshard_(?:execute|prepare|complete|plain_prepare|'
                         r'plain_finish)|prepare_local_read|prepare_captured_local_mget)')
    for namespace in ('src', 'db0/src'):
        for file in ('t_string', 'xshard'):
            rel = Path(namespace) / 'cmd' / (file + '.o')
            pre, post = [audit.Elf(root / rel) for root in (Path('build/notifycompat-pre'), Path('build'))]
            old, new = pre.functions(), post.functions()
            symbols = sorted(old.keys() | new.keys())
            names = subprocess.check_output(['c++filt'], input='\n'.join(symbols), text=True).splitlines()
            for symbol, name in zip(symbols, names):
                if not pattern.search(name):
                    continue
                a, b = old.get(symbol), new.get(symbol)
                rows.append(dict(object=str(rel), name=name,
                                 equal=bool(a and b and pre.canonical(a) == post.canonical(b)),
                                 pre_size=a['size'] if a else 0, post_size=b['size'] if b else 0))
    args.output.write_text(json.dumps(rows, indent=2) + '\n')
    changed = [row for row in rows if not row['equal']]
    print(json.dumps(dict(bodies=len(rows), identical=len(rows)-len(changed), changed=changed), indent=2))
    assert rows and not changed, 'hot-body drift: listed for repair/merit, never a throughput verdict'


if __name__ == '__main__':
    main()
