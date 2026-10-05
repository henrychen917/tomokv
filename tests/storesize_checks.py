#!/usr/bin/env python3
"""Emit cold-walk instrumentation; never starts a server or a benchmark."""
import argparse
import subprocess
import sys
from pathlib import Path


def instrument(source, output):
    text = Path(source).read_text()
    anchor = 'namespace tomo {'
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + '\nuint64_t storesize_walk_slots = 0, storesize_walk_objects = 0;\n', 1)
    for name in ('uint64_t multidb_size(', 'void multidb_stats('):
        start = text.index(name)
        end = text.index('\n}', start)
        body = text[start:end]
        walk = 'shard.store().for_each([&](KvObj* object) {'
        assert body.count(walk) == 1, name
        body = body.replace(walk,
            'storesize_walk_slots += shard.store().capacity();\n    ' + walk +
            '\n        ++storesize_walk_objects;', 1)
        text = text[:start] + body + text[end:]
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(text)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'check':
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
        from storesize_artifacts import pad
        unit = Path(sys.argv[2]).resolve()
        subprocess.run([str(unit), '--db0-only'], check=True)
        control = unit.with_name(unit.name + '-pad')
        print(pad(unit, control), flush=True)
        subprocess.run([str(control), '--legacy'], check=True)
        rejected = subprocess.run([str(control), '--db0-only'], capture_output=True, text=True)
        assert rejected.returncode == 1 and 'FAIL storesize: monitor route' in rejected.stderr, rejected
        print('PASS negative control: restored census route fails the exact monitor-route assertion')
        sys.exit(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    args = parser.parse_args()
    instrument(args.source, args.output)
