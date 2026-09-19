#!/usr/bin/env python3
"""Refresh/check R7's isolated loop copies against the current production envelopes.

Only method names and fresh-task drain calls change. Keeping the copies outside
the FIFO translation units preserves their compiler input and permits a byte audit.
This check never builds or runs an executable.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EX = ('fused_baseline_pass', 'fused_pass_impl', 'fused_baseline_sweep',
      'fused_sweep_impl')
IO = ('run_loop', 'sweep', 'flush_ready')
BEGIN = '// BEGIN R7 GENERATED ENVELOPES\n'
END = '// END R7 GENERATED ENVELOPES\n'


def function(source, name, member=True):
    pattern = (r'^    (?:uint32_t|void) ' if member else r'^(?:int|void) ') + re.escape(name) + r'\('
    match = re.search(pattern, source, re.M)
    if not match:
        raise ValueError(f'missing source function {name}')
    start = match.start()
    if member:
        lines = source[:start].splitlines(keepends=True)
        for line in reversed(lines[-5:]):
            if not (line.startswith('              ') or line.startswith('    template <')):
                break
            start -= len(line)
            if line.startswith('    template <'):
                break
    opening = source.index('{', match.end())
    # Ignore braces in comments and string/character literals while finding the body.
    tokens = re.finditer(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]',
                         source[opening:])
    depth = 0
    for token in tokens:
        if token[0] == '{': depth += 1
        if token[0] == '}': depth -= 1
        if depth == 0:
            end = opening + token.end()
            break
    else:
        raise ValueError(f'unclosed source function {name}')
    result = source[start:end]
    if member:
        result = '\n'.join(line[4:] if line.startswith('    ') else line
                           for line in result.splitlines())
    return result


def rename(text, names):
    for before, after in names.items():
        text = re.sub(r'\b' + before + r'(?=\s*[<(])', after, text)
    return text


def update(path, generated, write):
    old = path.read_text()
    prefix, sep, tail = old.partition(BEGIN)
    if not sep: raise ValueError(f'missing begin marker in {path}')
    _, sep, suffix = tail.partition(END)
    if not sep: raise ValueError(f'missing end marker in {path}')
    new = prefix + BEGIN + generated + END + suffix
    if old != new:
        if not write: raise ValueError(f'stale R7 envelope: {path}; run tools/reorder_sync.py --write')
        path.write_text(new)


if __name__ == '__main__':
    # One generator owns the surviving shadow envelopes; retain this old command
    # as an alias, so it cannot resurrect the retired split scheduler copies.
    import runpy
    runpy.run_path(str(ROOT / 'tests/r7shadow_sync.py'), run_name='__main__')
