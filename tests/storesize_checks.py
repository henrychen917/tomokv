#!/usr/bin/env python3
"""Emit cold-walk instrumentation; never starts a server or a benchmark."""
import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    args = parser.parse_args()
    instrument(args.source, args.output)
