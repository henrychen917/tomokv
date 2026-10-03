#!/usr/bin/env python3
"""Offline layout audit and kind-A PS1 control; never execute/attach to a server."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from lbstall_artifacts import Elf

LOCKS = {'Op': 336, 'Client': 1984, 'ThreadCtx': 1408, 'Shard': 1440,
         'FlatStore': 944, 'Rob<64>': 192, 'AtomicEntry': 144, 'Config': 624}


def layout(path):
    expressions = {}
    for ns in ('tomo', 'tomo_db0'):
        for name in (*LOCKS, 'AofManager', 'Server'):
            expressions[f'{ns}::{name}'] = f'sizeof({ns}::{name})'
        for field in ('aof_', 'snapshot_', 'flipctl_', 'shard_owner_'):
            expressions[f'{ns}::Server.{field}'] = f'(unsigned long)&(({ns}::Server*)0)->{field}'
    argv = ['gdb', '-nx', '-batch', str(path)]
    for expression in expressions.values(): argv += ['-ex', 'p ' + expression]
    output = subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT)
    values = re.findall(r'^\$\d+ = (\d+)$', output, re.M)
    assert len(values) == len(expressions), output
    result = dict(zip(expressions, map(int, values)))
    for ns in ('tomo', 'tomo_db0'):
        for name, size in LOCKS.items(): assert result[f'{ns}::{name}'] == size
    return result


def artifacts(pre, post, directory):
    before, after = Elf(pre), Elf(post)
    old_layout, new_layout = layout(pre), layout(post)
    assert old_layout == new_layout, 'locked/manager/server layout drift'
    patched = bytearray(after.data)
    functions = list(after.functions().values())
    demangled = subprocess.check_output(['c++filt'], text=True,
                                       input='\n'.join(s['name'] for s in functions) + '\n').splitlines()
    patches = []
    helpers = ('defer_completion', 'finish_completions', 'note_buffered')
    for symbol, name in zip(functions, demangled):
        if '[clone' in name or not any(f'::AofManager::{helper}(' in name for helper in helpers):
            continue
        section = after.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3]
        if patched[offset:offset+4] == b'\xf3\x0f\x1e\xfa': offset += 4
        assert symbol['size'] >= 7
        original = bytes(patched[offset:offset+3])
        patched[offset:offset+3] = b'\x31\xc0\xc3'  # false/zero/no-op; remainder is dead text
        patches.append(dict(function=name, offset=offset, original=original.hex(), replacement='31c0c3'))
    assert len(patches) == 6, patches  # three helpers in BOTH linked database variants
    cursor = 0
    for patch in sorted(patches, key=lambda p: p['offset']):
        at = patch['offset']
        assert patched[cursor:at] == after.data[cursor:at]
        cursor = at + 3
    assert patched[cursor:] == after.data[cursor:]
    pad = directory / 'PAD-A'
    pad.write_bytes(patched)
    pad.chmod(post.stat().st_mode)
    control = Elf(pad)
    assert after.sections == control.sections and after.symbols == control.symbols
    report = dict(kind='A: behaviour twin',
                  scope='PRE completion publication with POST text/heap layouts; shutdown fix remains active',
                  caveat='PAD retains candidate call envelopes; it is a layout control, not a speed verdict',
                  layout=new_layout, patches=patches, all_other_bytes_equal=True,
                  sections_and_symbols_equal=True, arms={})
    for label, path, elf in (('PRE', pre, before), ('POST', post, after), ('PAD-A', pad, control)):
        report['arms'][label] = dict(path=str(path.resolve()), sha256=hashlib.sha256(elf.data).hexdigest(),
                                    text_bytes=elf.sections[elf.names.index('.text')][5])
        for policy in ('off', 'no', 'always'):
            wrapper = directory / f'{label}-{policy}'
            options = '--appendonly no' if policy == 'off' else f'--appendonly yes --appendfsync {policy}'
            wrapper.write_text('#!/bin/bash\nset -e\nunset TOMO_AOF_ACK_WINDOW\nexec ' +
                               shlex.quote(str(path.resolve())) + ' "$@" --shards 16 ' +
                               options + ' --auto-aof-rewrite-percentage 0\n')
            wrapper.chmod(0o755)
    (directory / 'artifacts.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pre', type=Path)
    p.add_argument('post', type=Path)
    p.add_argument('directory', type=Path)
    a = p.parse_args()
    a.directory.mkdir(parents=True, exist_ok=True)
    artifacts(a.pre, a.post, a.directory)
