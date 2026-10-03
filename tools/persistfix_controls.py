#!/usr/bin/env python3
"""Emit isolated PS1/PS2/PS14 clause deletions; never build or run a server."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_body(source, signature, replacement):
    start = source.index(signature)
    opening = source.index('{', start)
    # These production bodies have balanced braces in comments and strings too.
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[:opening] + '{\n' + replacement + '\n}' + source[end:]


def emit(name, output):
    source = (ROOT / 'src/persist/aof.cc').read_text()
    if name == 'old-ack':
        source = replace_body(source, 'bool AofManager::defer_completion(',
                              '    (void)producer; (void)op; (void)client; return false;')
    elif name == 'old-close':
        source = replace_body(source, '    while (!producers_stopped())', '')
        # replace_body retains the while condition; remove the now empty loop.
        source = source.replace('    while (!producers_stopped()) {\n\n}',
                                '    // Negative control: writer closes before producer stop.')
    elif name == 'no-refusal':
        old = 'const uint64_t refused = ++chunk_in_[producer].refused;'
        assert source.count(old) == 1
        source = source.replace(old, 'const uint64_t refused = 1;')
    else:
        raise ValueError(name)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=('old-ack', 'old-close', 'no-refusal'))
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    emit(args.name, args.output)
