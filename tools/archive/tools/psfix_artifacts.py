#!/usr/bin/env python3
"""Offline PS5/PS7 function-byte and layout audit; does not execute either binary."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import textwrap

import lbstall_artifacts as audit

# Same extension as docs/gt13split/audit_bodies.py, for TLS in the full inventory.
source = textwrap.dedent(inspect.getsource(audit.Elf.canonical))
assert source.count('24: 8,') == 1
scope = vars(audit).copy()
exec(source.replace('24: 8,', '23: 4, 24: 8,'), scope)
audit.Elf.canonical = scope['canonical']


def layouts(binary):
    types = ['Op', 'Client', 'ThreadCtx', 'Shard', 'FlatStore', 'Rob<64>',
             'AtomicEntry', 'Config', 'AofManager', 'SnapshotManager', 'Server']
    script = ('import gdb,json; out={}; ' +
              'exec(' + repr('\n'.join([
                  'for ns in ("tomo", "tomo_db0"):',
                  ' for name in ' + repr(types) + ':',
                  '  t=gdb.lookup_type(ns+"::"+name)',
                  '  out[ns+"::"+name]={"size": t.sizeof, "fields": {f.name:f.bitpos for f in t.fields() if f.name and hasattr(f,"bitpos")}}',
              ])) + '); print(json.dumps(out,sort_keys=True))')
    raw = subprocess.check_output(['gdb', '-nx', '-batch', str(binary), '-ex', 'python ' + script], text=True)
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows, changed, inventory = [], [], []
    total = 0
    for path in sorted(args.pre.rglob('*.o')):
        relative = path.relative_to(args.pre)
        after_path = args.post / relative
        before, after = audit.Elf(path), audit.Elf(after_path)
        old, new = before.functions(), after.functions()
        names = sorted(old.keys() | new.keys())
        labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
        for name, label in zip(names, labels):
            if name not in old or name not in new:
                inventory.append(dict(object=str(relative), name=label,
                                      status='added' if name in new else 'removed'))
                continue
            total += 1
            raw_equal = before.body(old[name]) == after.body(new[name])
            equal = before.canonical(old[name]) == after.canonical(new[name])
            row = dict(object=str(relative), name=label, symbol=name,
                       pre_size=old[name]['size'], post_size=new[name]['size'],
                       raw_equal=raw_equal, relocation_equal=equal)
            if not equal:
                changed.append(row)
            if '::cmd_' in label:
                rows.append(row)
        print(relative, len(old), 'PRE functions,', len(new), 'POST functions', flush=True)
    old_layout, new_layout = layouts(args.pre / 'tomokv'), layouts(args.post / 'tomokv')
    for name, layout in old_layout.items():
        assert layout['size'] == new_layout[name]['size'], (name, 'size changed')
        for field, offset in layout['fields'].items():
            assert new_layout[name]['fields'][field] == offset, (name, field, 'offset changed')
    hot_ok = audit.compare(args.pre, args.post, args.output / 'hot-bodies.json')
    ordinary = [r for r in rows if not any('::' + cold + '(' in r['name']
                                          for cold in ('cmd_config', 'cmd_info'))]
    report = dict(functions_compared=total, command_bodies=rows, changed_bodies=changed,
                  inventory_changes=inventory, pre_layout=old_layout, post_layout=new_layout,
                  existing_layout_equal=True, ordinary_command_bodies=len(ordinary),
                  ordinary_commands_equal=all(r['relocation_equal'] for r in ordinary),
                  stock_hot_bodies_equal=hot_ok, arms={})
    for name, root in (('PRE', args.pre), ('POST', args.post)):
        elf = audit.Elf(root / 'tomokv')
        report['arms'][name] = dict(sha256=hashlib.sha256(elf.data).hexdigest(),
                                  text_bytes=elf.sections[elf.names.index('.text')][5])
    (args.output / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print('AUDIT:', total, 'function pairs;', len(ordinary), 'ordinary command bodies;',
          len(changed), 'changed bodies;', len(inventory), 'inventory changes')
    for row in changed:
        print('CHANGED', row['object'], row['pre_size'], row['post_size'], row['name'])
    assert report['ordinary_commands_equal'], 'ordinary command body changed'
    assert hot_ok, 'stock hot-body audit failed'


if __name__ == '__main__':
    main()
