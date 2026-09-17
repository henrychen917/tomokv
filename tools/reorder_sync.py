#!/usr/bin/env python3
"""Refresh/check R7's isolated loop copies against the current production envelopes.

Only method names and fresh-task drain calls change. Keeping the copies outside
the FIFO translation units preserves their compiler input and permits a byte audit.
This check never builds or runs an executable.
"""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EX = ('fused_baseline_pass', 'fused_pass_impl', 'fused_baseline_sweep',
      'fused_sweep_impl', 'run', 'sweep', 'drain_tasks_read_local_interleaved')
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


def envelopes():
    ex = (ROOT / 'src/core/ex_loop.h').read_text()
    io = (ROOT / 'src/core/io_loop.h').read_text()
    boot = (ROOT / 'src/core/genthread.cc').read_text()
    bodies, declarations = [], {}
    for owner, source, methods in (('ExLoopT<Fused>', ex, EX), ('IoLoop', io, IO)):
        names = {name: 'r7_' + name for name in methods}
        if owner.startswith('Ex'):
            names.update(drain_tasks='r7_drain_tasks',
                         drain_tasks_with_filler='r7_drain_tasks_with_filler',
                         exec_batch='r7_exec_batch')
        else:
            names.update({name: 'r7_' + name for name in EX if name.startswith('fused_')})
        decls = []
        for method in methods:
            body = rename(function(source, method), names)
            signature, rest = body.split('{', 1)
            decls.append(signature.rstrip() + ';')
            signature = re.sub(r' = (?:false|true|void|nullptr|0|kGenthreadExBatchOps)', '', signature)
            signature = signature.replace(' r7_' + method + '(', ' ' + owner + '::r7_' + method + '(')
            if owner.startswith('Ex'):
                signature = 'template <bool Fused>\n' + signature
            bodies.append(signature + '{' + rest)
        declarations[owner] = '\n'.join(decls)
    bodies.append(rename(function(boot, 'IoLoop::run_fused', False),
                         {'run_fused': 'run_fused_reordered', 'run_loop': 'r7_run_loop'}))
    bodies.append('template void ExLoopT<false>::r7_run();\n'
                  'template void ExLoopT<true>::r7_run();')
    bodies.append('namespace {\n' + function(boot, 'pin_fused_thread', False) + '\n}')
    bodies.append('static ' + rename(function(boot, 'run_fused_server', False),
                                   {'run_fused_server': 'run_fused_server_reordered',
                                    'run_fused': 'run_fused_reordered'}))
    return '\n\n'.join(bodies) + '\n', declarations


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    bodies, declarations = envelopes()
    update(ROOT / 'src/core/reorder.cc', bodies, args.write)
    for owner, filename in [('ExLoopT<Fused>', 'ex_loop.h'), ('IoLoop', 'io_loop.h')]:
        update(ROOT / 'src/core' / filename,
               ''.join('    ' + line + '\n' for line in declarations[owner].splitlines()), args.write)
    print('R7 production envelopes: current')
