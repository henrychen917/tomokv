#!/usr/bin/env python3
"""Offline PRE/POST function-byte inventory. No listeners or workloads are started."""
import argparse
import gzip
import inspect
import json
from pathlib import Path
import re
import subprocess
import textwrap
import lbstall_artifacts as audit

# Match gt13split's extension for TLS offsets; preserve target identities and all opcodes.
source = textwrap.dedent(inspect.getsource(audit.Elf.canonical))
assert source.count('24: 8,') == 1
scope = vars(audit).copy()
exec(source.replace('24: 8,', '23: 4, 24: 8,'), scope)
audit.Elf.canonical = scope['canonical']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(args.pre.rglob('*.o')):
        rel = path.relative_to(args.pre)
        other = args.post / rel
        assert other.exists(), other
        before, after = audit.Elf(path), audit.Elf(other)
        old, new = before.functions(), after.functions()
        names = sorted(old.keys() | new.keys())
        labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
        for symbol, name in zip(names, labels):
            a, b = old.get(symbol), new.get(symbol)
            equal = bool(a and b and before.canonical(a) == after.canonical(b))
            rows.append(dict(object=str(rel), symbol=symbol, name=name, equal=equal,
                             raw_equal=bool(a and b and before.body(a) == after.body(b)),
                             pre_size=a['size'] if a else 0, post_size=b['size'] if b else 0))
        print(str(rel), len(names), 'bodies', flush=True)
    with gzip.open(args.output / 'bodies.json.gz', 'wt') as f:
        json.dump(rows, f, indent=2)
    changed = [r for r in rows if not r['equal']]
    (args.output / 'changed-bodies.json').write_text(json.dumps(changed, indent=2) + '\n')
    handlers = [r for r in rows if re.search(r'::cmd_\w+(?:<|\()', r['name'])]
    hot = [r for r in rows if audit.HOT.search(r['name'])]
    report = dict(total=len(rows), equal=sum(r['equal'] for r in rows), changed=len(changed),
                  handlers=len(handlers), handlers_equal=sum(r['equal'] for r in handlers),
                  hot=len(hot), hot_equal=sum(r['equal'] for r in hot),
                  changed_handlers=[r for r in handlers if not r['equal']],
                  changed_hot=[r for r in hot if not r['equal']])
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if not isinstance(v,list)}))


if __name__ == '__main__':
    main()
