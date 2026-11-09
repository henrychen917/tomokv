#!/usr/bin/env python3
"""Compare every linked function with the gate's instruction/relocation normalizer."""
import argparse
import difflib
import gzip
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from reorder_noop import Binary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('before', type=Path)
    p.add_argument('after', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    old, new = (Binary(path, a.output, literal_pools=True) for path in (a.before, a.after))
    changes, hot = [], []
    # MGET/MSET use scatter entry points, not cmd_mget/cmd_mset symbols.
    main_commands = re.compile(r'::cmd_(?:get|set|incr|decr|mget|mset)(?:<|\(|_)|'
                               r'::cmd_xshard_only|prepare_captured_local_mget|'
                               r'::xshard_(?:prepare|execute|complete|retire|store_string|queue_commit|flush_commits)')
    for name in sorted(old.groups.keys() | new.groups.keys()):
        before = sorted(old.groups.get(name, []), key=lambda b: b['addr'])
        after = sorted(new.groups.get(name, []), key=lambda b: b['addr'])
        equal = [(b['ins'], b['encodings']) for b in before] == [(b['ins'], b['encodings']) for b in after]
        is_hot = bool(main_commands.search(name) or any(main_commands.search(alias)
                      for body in before + after for alias in body['aliases']))
        if is_hot:
            hot.append(dict(name=name, identical=equal))
        if equal:
            continue
        def lines(bodies):
            return [f'{i}: {ins} | {enc}\n' for i, body in enumerate(bodies)
                    for ins, enc in zip(body['ins'], body['encodings'])]
        changes.append(dict(name=name, main_command=is_hot,
                            before_sizes=[b['size'] for b in before],
                            after_sizes=[b['size'] for b in after],
                            diff=''.join(difflib.unified_diff(lines(before), lines(after),
                                                            fromfile='before', tofile='after'))))
    report = dict(before=str(a.before.resolve()), after=str(a.after.resolve()),
                  before_sha256=old.sha256, after_sha256=new.sha256,
                  groups_compared=len(old.groups.keys() | new.groups.keys()),
                  changed=[{k: v for k, v in row.items() if k != 'diff'} for row in changes],
                  main_commands=hot)
    (a.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    with gzip.open(a.output / 'diffs.json.gz', 'wt') as f:
        json.dump(changes, f, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'main_commands'}, indent=2))
    assert hot and all(row['identical'] for row in hot), 'main command changed'
    print(f'{len(hot)} main-command function groups instruction-identical')


if __name__ == '__main__':
    main()
