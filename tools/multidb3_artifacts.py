#!/usr/bin/env python3
"""Offline DB-0 code audit and kind-A boot control. Never runs an executable."""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path
from lbstall_artifacts import Elf, HOT

LAYOUT = ('Slice', 'Op', 'Client', 'ThreadCtx', 'Shard', 'FlatStore', 'Rob<64>',
          'AtomicEntry', 'Config', 'Server', 'SnapshotManager', 'Server.cfg_',
          'Server.placement_', 'Server.router_', 'Server.threads_', 'Server.aof_',
          'Server.snapshot_', 'Server.flipctl_', 'Server.shard_owner_',
          'Server.flip_stage_', 'Server.lb_stage_')


def layout(paths):
    rows = {}
    for path in paths:
        elf = Elf(path)
        symbol, = [s for s in elf.symbols if s['name'] == 'multidb_layout_values']
        values = struct.unpack('<' + 'Q' * len(LAYOUT), elf.body(symbol))
        rows[path] = dict(zip(LAYOUT, values))
    return rows


def canonical(value):
    if isinstance(value, str):
        return value.replace('8tomo_db0', '4tomo')
    if isinstance(value, (tuple, list)):
        return tuple(canonical(x) for x in value)
    return value


def audit(before, after):
    rows = []
    for old_path in sorted(Path(before).rglob('*.o')):
        new_path = Path(after) / old_path.relative_to(before)
        if not new_path.exists():
            continue
        old, new = Elf(old_path), Elf(new_path)
        old_functions = old.functions()
        names = list(new.functions())
        readable = subprocess.check_output(['c++filt'], input=('\n'.join(names) + '\n').encode()).decode().splitlines()
        for name, label in zip(names, readable):
            if not HOT.search(label) and not any(x in label for x in ('resp_parse', 'hash_key', 'push_arg')):
                continue
            original = old_functions.get(canonical(name))
            if not original:
                continue
            candidate = new.functions()[name]
            equal = canonical(old.canonical(original)) == canonical(new.canonical(candidate))
            rows.append(dict(object=str(old_path.relative_to(before)), function=label,
                             pre_bytes=original['size'], post_bytes=candidate['size'],
                             instructions_and_targets_equal=equal))
    assert rows, 'no shared code witnesses'
    return dict(normalization='C++ namespace tomo_db0 -> tomo only; all opcodes and relocation targets checked',
                matched=sum(r['instructions_and_targets_equal'] for r in rows), total=len(rows), rows=rows)


def primitives(before, after):
    old, new = Elf(before), Elf(after)
    rows = []
    for name, candidate in new.functions().items():
        if not name.startswith('_Z') or not any(part in name for part in ('multidb_probe_', 'resp_parse_t')):
            continue
        original = old.functions()[canonical(name)]
        rows.append(dict(function=name, pre_bytes=original['size'], post_bytes=candidate['size'],
                         instructions_and_targets_equal=
                         canonical(old.canonical(original)) == canonical(new.canonical(candidate))))
    assert sum('multidb_probe_' in r['function'] for r in rows) == 4, 'expected all four primitive witnesses'
    assert any('resp_parse_t' in r['function'] for r in rows), 'expected the actual parser body'
    return rows


def twin(source, output):
    elf = Elf(source)
    assert elf.kind != 1 and Path(source).resolve() != Path(output).resolve()
    symbols = [s for s in elf.functions().values() if s['name'] == '_Z19tomokv_multidb_bootj']
    assert len(symbols) == 1, 'expected one boot selector'
    symbol = symbols[0]
    section = elf.sections[symbol['sec']]
    at = section[4] + symbol['value'] - section[3]
    body = elf.body(symbol)
    if body.startswith(bytes.fromhex('f30f1efa')):
        at += 4; body = body[4:]  # keep the CET landing instruction intact
    assert body == bytes.fromhex('83ff010f97c0c3'), body.hex()  # cmp edi,1; seta al; ret
    data = bytearray(elf.data)
    data[at:at + 3] = bytes.fromhex('31c0c3')  # xor eax,eax; ret
    Path(output).write_bytes(data)
    Path(output).chmod(Path(source).stat().st_mode)
    pad = Elf(output)
    assert pad.sections == elf.sections and pad.symbols == elf.symbols
    assert data[:at] == elf.data[:at] and data[at + 3:] == elf.data[at + 3:]
    return dict(kind='A: behaviour twin', scope='DB-0 traffic only; never use PAD for multi-DB correctness',
                control='force the legacy single-keyspace runtime at boot, in the exact POST ELF layout',
                default_path='POST databases=1 already selects this runtime; POST/PAD use identical operation bodies',
                source=str(source), output=str(output), selector=symbol['name'], changed_bytes=3,
                source_sha256=hashlib.sha256(elf.data).hexdigest(),
                pad_sha256=hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('pad'); p.add_argument('source'); p.add_argument('output')
    p = sub.add_parser('audit'); p.add_argument('before'); p.add_argument('after')
    p = sub.add_parser('primitives'); p.add_argument('before'); p.add_argument('after')
    p = sub.add_parser('layout'); p.add_argument('objects', nargs='+')
    args = parser.parse_args()
    if args.action == 'pad':
        result = twin(args.source, args.output)
    elif args.action == 'layout':
        result = layout(args.objects)
    elif args.action == 'primitives':
        result = primitives(args.before, args.after)
    else:
        result = audit(args.before, args.after)
    print(json.dumps(result, indent=2))
