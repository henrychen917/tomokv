#!/usr/bin/env python3
"""Compare type sizes and every named field offset between two linked binaries (gdb, offline).
usage: layouts.py <pre-binary> <post-binary> <out.json>"""
import json, subprocess, sys

TYPES = ['Op', 'Client', 'ThreadCtx', 'Shard', 'FlatStore', 'Rob<64>', 'AtomicEntry', 'Config',
         'AofManager', 'SnapshotManager', 'Server', 'IoLoop', 'ExLoopT<true>', 'ExLoopT<false>',
         'LoopSignals', 'WbEngine']
LOCKS = {'Op': 336, 'Client': 1984, 'ThreadCtx': 1408, 'Shard': 1440, 'FlatStore': 944,
         'Rob<64>': 192, 'AtomicEntry': 144, 'Config': 624}


def layouts(binary):
    script = ('import gdb,json; out={}; ' + 'exec(' + repr('\n'.join([
        'for ns in ("tomo", "tomo_db0"):',
        ' for name in ' + repr(TYPES) + ':',
        '  try:',
        '   t=gdb.lookup_type(ns+"::"+name).strip_typedefs()',
        '  except Exception as e:',
        '   out[ns+"::"+name]={"error": str(e)}; continue',
        '  out[ns+"::"+name]={"size": t.sizeof, "fields": {f.name: f.bitpos//8 for f in t.fields() if f.name and hasattr(f,"bitpos") and not f.is_base_class}}',
    ])) + '); print(json.dumps(out,sort_keys=True))')
    raw = subprocess.check_output(['gdb', '-nx', '-batch', binary, '-ex', 'python ' + script], text=True)
    return json.loads(raw.strip().splitlines()[-1])


def main():
    pre, post = layouts(sys.argv[1]), layouts(sys.argv[2])
    report = {'locks': {}, 'types': {}}
    ok = True
    for key in sorted(pre):
        a, b = pre[key], post.get(key, {})
        if 'error' in a or 'error' in b:
            report['types'][key] = dict(error=a.get('error') or b.get('error'))
            continue
        moved = {f: [o, b['fields'].get(f)] for f, o in a['fields'].items() if b['fields'].get(f) != o}
        # A reserved tail array may start later when a lane consumes its leading bytes
        # (authfix: Config::requirepass_size); every named member must stay put.
        reserved = {f: v for f, v in moved.items() if 'reserved' in f and v[1] is not None and v[1] > v[0]}
        moved = {f: v for f, v in moved.items() if f not in reserved}
        added = {f: o for f, o in b['fields'].items() if f not in a['fields']}
        report['types'][key] = dict(pre_size=a['size'], post_size=b['size'], moved_or_removed=moved, added=added, reserved_tail_shrunk=reserved)
        name = key.split('::', 1)[1]
        if name in LOCKS:
            good = a['size'] == b['size'] == LOCKS[name] and not moved
            report['locks'][key] = dict(expected=LOCKS[name], pre=a['size'], post=b['size'], offsets_unchanged=not moved, ok=good)
            ok &= good
    report['all_locks_ok'] = ok
    open(sys.argv[3], 'w').write(json.dumps(report, indent=1) + '\n')
    for k, v in report['types'].items():
        if 'error' in v:
            print(f'{k:32} ERROR {v["error"][:80]}')
            continue
        print(f"{k:32} {v['pre_size']:6} -> {v['post_size']:6}  moved/removed={len(v['moved_or_removed'])} added={list(v['added'])}")
    print('all eight locks equal and offsets unchanged:', ok)


if __name__ == '__main__':
    main()
