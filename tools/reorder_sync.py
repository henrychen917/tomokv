#!/usr/bin/env python3
"""Shared envelope helpers and compatibility entry for tests/r7shadow_sync.py.

There is one generator for the surviving fused shadow call graph. This check
never builds or runs an executable.
"""
from pathlib import Path
import re
import source_tokens as cpp

ROOT = Path(__file__).resolve().parents[1]
EX = ('fused_baseline_pass', 'fused_pass_impl', 'fused_baseline_sweep',
      'fused_sweep_impl', 'sweep')
BEGIN = '// BEGIN R7 GENERATED ENVELOPES\n'
END = '// END R7 GENERATED ENVELOPES\n'


def function(source, name, member=True):
    if str(source).count('TOMO_TOOL_FUNCTION ' + name + ' ') != 1:
        raise ValueError('missing or duplicate source function marker ' + name)
    return cpp.function(cpp.Source(source), name).strip()


def rename(text, names):
    aliases = {new: old for old, new in cpp.bindings(str(text)).items()}
    aliases.update(getattr(text, 'aliases', {}))
    text = cpp.rename(text, aliases)
    text = re.sub(r'/\*\s*TOMO_TOOL_(?:BIND|FUNCTION)\s+[^*]+\*/', '', text)
    return cpp.rename(text, names)


def update(path, generated, write):
    old = path.read_text()
    if old.count(BEGIN.strip()) != 1 or old.count(END.strip()) != 1:
        raise ValueError(f'missing or duplicate generated envelope marker in {path}')
    prefix, _, tail = old.partition(BEGIN.strip())
    current, _, suffix = tail.partition(END.strip())
    if cpp.tokens(cpp.Source(current)) != cpp.tokens(cpp.Source(generated)):
        if not write:
            raise ValueError(f'stale R7 envelope: {path}; run tools/reorder_sync.py --write')
        path.write_text(prefix + BEGIN + generated + END.rstrip() + suffix)

if __name__ == '__main__':
    # One generator owns the surviving shadow envelopes; retain this old command
    # as an alias, so it cannot resurrect the retired split scheduler copies.
    import runpy
    runpy.run_path(str(ROOT / 'tests/r7shadow_sync.py'), run_name='__main__')
