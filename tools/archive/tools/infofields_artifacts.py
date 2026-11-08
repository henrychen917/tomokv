#!/usr/bin/env python3
"""SV6/SV7/SV9 offline byte, instruction, link and layout proof; never runs an ELF."""
import argparse
import copy
from bisect import bisect_left
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

# Reuse the existing canonicalizer, including named data/code relocation targets.
# infofields_budget also bounds merged constants by their ELF entry size.
from infofields_budget import audit
from cmdmeta_audit import functions as linked_functions

ORDINARY = re.compile(r'::cmd_\w+(?:<|\()|::command_\w+\(|parse_and_dispatch|resp_parse|'
                      r'parse_len_crlf|resp_length|resp_count|resp_bulk_prefix|resp_inline|'
                      r'FlatStore::|ThreadCtx::note_command|IoLoop::.*(?:pass|dispatch)|'
                      r'ExLoopT<.*(?:pass|execute|run)|WbEngine::(?:pump|serve|prepare)|'
                      + audit.HOT.pattern)
COLD = re.compile(r'::\(anonymous namespace\)::cmd_(?:info|config)\(|'
                  r'::command_(?:bind_server|config_resetstat)\(|'
                  r'::IoLoop::climon_monitor_feed\(|::command_metadata_skip_monitor\(|'
                  r'::Server::monitor_controllers\(|::snapshot_last_bgsave_ok\(|::record_bgsave_failure\(|'
                  r'::SnapshotManager::(?:init|abort_file|complete_file_success|start|on_io_complete|writer_pass)\(')
WIDTH = {1: 8, 2: 4, 4: 4, 9: 4, 10: 4, 11: 4, 23: 4, 24: 8, 41: 4, 42: 4,
         'direct': 4, 'code-address': 4}


def write(path, value):
    data = (json.dumps(value, indent=2) + '\n').encode()
    path.write_bytes(gzip.compress(data, mtime=0) if path.suffix == '.gz' else data)


def labels(names):
    return subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()


def instruction_addresses(elf):
    result, section = defaultdict(list), None
    by_name = {name: i for i, name in enumerate(elf.names)}
    text = subprocess.check_output(['objdump', '-dw', str(elf.path)], text=True)
    for line in text.splitlines():
        if line.startswith('Disassembly of section '):
            section = by_name[line[len('Disassembly of section '):-1]]
        else:
            m = re.match(r'\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} )+\s*\S', line)
            if m:
                result[section].append(int(m[1], 16))
    return result


def instruction_count(index, symbol):
    if not symbol:
        return 0
    positions = index[symbol['sec']]
    return bisect_left(positions, symbol['value'] + symbol['size']) - bisect_left(positions, symbol['value'])


def layouts(binary):
    names = ['Op', 'Client', 'ThreadCtx', 'Shard', 'FlatStore', 'Rob<64>', 'AtomicEntry', 'Config']
    program = '\n'.join([
        'import gdb,json', 'out={}',
        'for ns in ("tomo", "tomo_db0"):',
        ' for name in ' + repr(names) + ':',
        '  t=gdb.lookup_type(ns+"::"+name)',
        '  out[ns+"::"+name]={"size":t.sizeof,"fields":{f.name:f.bitpos for f in t.fields() if f.name and hasattr(f,"bitpos")}}',
        'print(json.dumps(out,sort_keys=True))'])
    output = subprocess.check_output(['gdb', '-nx', '-batch', '-iex', 'set debuginfod enabled off',
                                      str(binary), '-ex', 'python exec(' + repr(program) + ')'], text=True)
    return json.loads(output)


def cold_reason(relative, name):
    if relative.endswith('cmd/info_stats.o'):
        return 'cold boot identity, monitor-only collection, INFO formatting/reads, RESETSTAT, and their helpers'
    if 'SnapshotManager::' in name or 'snapshot_last_bgsave_ok' in name or 'record_bgsave_failure' in name:
        return 'cold snapshot success/abort status publication (including inlined callees)'
    if 'monitor_controllers' in name:
        return 'existing main/monitor timer: 100 ms sampler and wake deadline, including controllers-off boot'
    if 'climon_monitor_feed' in name or 'command_metadata_skip_monitor' in name:
        return 'MONITOR-armed generated admin/skip_monitor exclusion'
    if COLD.search(name):
        return 'cold INFO/CONFIG RESETSTAT or pre-worker boot initialization'
    return None


def byte_controls(post, out):
    obj = audit.Elf(post / "src/cmd/t_server.o")
    symbol = next(s for name, s in obj.functions().items()
                  if "11cmd_command" in name and ".cold" not in name)
    baseline = obj.canonical(symbol)
    section = obj.sections[symbol["sec"]]
    code_at = section[4] + symbol["value"]
    constant = next(t for at, kind, t, addend in obj.relocs[symbol["sec"]]
                    if symbol["value"] <= at < symbol["value"] + symbol["size"] and
                    obj.names[t["sec"]] == ".rodata.cst4")
    const_section = obj.sections[constant["sec"]]
    constant_at = const_section[4] + constant["value"]
    assert const_section[9] == 4 and constant["value"] + 8 <= const_section[5]
    rows = []
    for label, at, equal in (("opcode mutation", code_at, False),
                             ("referenced constant mutation", constant_at, False),
                             ("unreferenced neighboring constant", constant_at + 4, True)):
        changed = copy.copy(obj)
        data = bytearray(obj.data)
        data[at] ^= 1
        changed.data = bytes(data)
        observed = changed.canonical(symbol) == baseline
        assert observed == equal, (label, observed, equal)
        rows.append(dict(control=label, accepted=observed, expected_equal=equal))
    out.mkdir(parents=True, exist_ok=True)
    write(out / "byte-controls.json", rows)
    print(json.dumps(rows, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pre', type=Path)
    p.add_argument('post', type=Path)
    p.add_argument('out', type=Path)
    p.add_argument('--controls-only', action='store_true')
    args = p.parse_args()
    if args.controls_only:
        byte_controls(args.post, args.out)
        return
    args.out.mkdir(parents=True, exist_ok=True)
    rows, changes, object_rows = [], [], []
    provenance = defaultdict(list)
    for before in sorted(args.pre.rglob('*.o')):
        relative = str(before.relative_to(args.pre))
        after = args.post / relative
        assert after.exists(), after
        a, b = audit.Elf(before), audit.Elf(after)
        old, new = a.functions(), b.functions()
        ai, bi = instruction_addresses(a), instruction_addresses(b)
        names = sorted(old.keys() | new.keys())
        delta = 0
        for name, label in zip(names, labels(names)):
            x, y = old.get(name), new.get(name)
            ca, cb = a.canonical(x) if x else None, b.canonical(y) if y else None
            equal = x is not None and y is not None and ca == cb
            ordinary = bool(ORDINARY.search(label)) and not COLD.search(label)
            row = dict(object=relative, symbol=name, name=label, ordinary=ordinary,
                       pre_size=x['size'] if x else 0, post_size=y['size'] if y else 0,
                       pre_instructions=instruction_count(ai, x), post_instructions=instruction_count(bi, y),
                       raw_equal=bool(x and y and a.body(x) == b.body(y)), equal=equal)
            rows.append(row)
            if not equal:
                delta += 1
                row['reason'] = cold_reason(relative, label)
                changes.append(row)
            elif ordinary:
                offsets = set()
                for at, kind, target in ca[1]:
                    offsets.update(range(at, at + WIDTH[kind]))
                provenance[(name, x['size'])].append((relative, ca[0], offsets, ca[1]))
        object_rows.append(dict(object=relative, functions=len(names), changed=delta))
    ordinary = [row for row in rows if row['ordinary']]
    write(args.out / 'bodies.json.gz', rows)
    write(args.out / 'changed-bodies.json', changes)
    write(args.out / 'objects.json', object_rows)

    a, b = audit.Elf(args.pre / 'tomokv'), audit.Elf(args.post / 'tomokv')
    old, new = linked_functions(a), linked_functions(b)
    keys = sorted(old.keys() | new.keys())
    link_rows = []
    for key, label in zip(keys, labels([key[0] for key in keys])):
        if not ORDINARY.search(label) or COLD.search(label):
            continue
        x, y = old.get(key), new.get(key)
        if not x or not y or x['size'] == 0:
            continue
        aa, bb = a.body(x), b.body(y)
        matches = []
        relaxations = []
        for source, code, offsets, targets in provenance[(key[0], len(aa))]:
            left, right = bytearray(aa), bytearray(bb)
            if len(left) != len(right):
                continue
            expected = bytearray(code)
            relaxed = []
            for at, kind, _ in targets:
                # R_X86_64_REX_GOTPCRELX permits the linker to resolve MOV via
                # GOT into LEA of a local address. Validate that exact transform
                # on BOTH linked arms; never mask arbitrary opcode differences.
                if kind == 42 and at >= 3 and expected[at - 3] & 0xf0 == 0x40 and \
                        expected[at - 2] == 0x8b and expected[at - 1] & 0xc7 == 5 and \
                        left[at - 2] == right[at - 2] == 0x8d:
                    expected[at - 2] = 0x8d
                    relaxed.append(at - 2)
            for offset in offsets:
                left[offset] = right[offset] = 0
            if bytes(left) == bytes(right) == bytes(expected):
                matches.append(source)
                relaxations.extend(relaxed)
        link_rows.append(dict(symbol=key[0], occurrence=key[1], name=label,
                              pre_size=len(aa), post_size=len(bb), raw_equal=aa == bb,
                              object_matches=matches, validated_got_relaxations=sorted(set(relaxations)),
                              proven=bool(matches)))
    write(args.out / 'linked-ordinary.json.gz', link_rows)
    pre_layout, post_layout = layouts(args.pre / 'tomokv'), layouts(args.post / 'tomokv')
    write(args.out / 'layouts.json', dict(PRE=pre_layout, POST=post_layout))
    summary = dict(objects=len(object_rows), functions=len(rows), changed=len(changes),
                   ordinary=len(ordinary), ordinary_equal=sum(r['equal'] for r in ordinary),
                   ordinary_raw_equal=sum(r['raw_equal'] for r in ordinary),
                   ordinary_instruction_counts_equal=sum(r['pre_instructions'] == r['post_instructions'] for r in ordinary),
                   ordinary_instructions_pre=sum(r['pre_instructions'] for r in ordinary),
                   ordinary_instructions_post=sum(r['post_instructions'] for r in ordinary),
                   linked_ordinary=len(link_rows), linked_proven=sum(r['proven'] for r in link_rows),
                   linked_raw_equal=sum(r['raw_equal'] for r in link_rows),
                   layouts_equal=pre_layout == post_layout,
                   unexplained=[r for r in changes if r['reason'] is None])
    for name, elf in [('PRE', a), ('POST', b)]:
        summary[name] = dict(sha256=hashlib.sha256(elf.data).hexdigest(),
                             text_bytes=len(elf.section_data(elf.names.index('.text'))))
    write(args.out / 'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'unexplained'}, indent=2))
    for row in summary['unexplained']:
        print('UNEXPLAINED', row['object'], row['name'])
    assert ordinary and all(r['equal'] for r in ordinary), 'ordinary body changed'
    assert all(r['pre_instructions'] == r['post_instructions'] for r in ordinary), 'instruction count changed'
    assert link_rows and all(r['proven'] for r in link_rows), 'linked ordinary body not proven'
    assert pre_layout == post_layout, 'locked size/member layout changed'
    assert not summary['unexplained'], 'unexplained emitted code change'


if __name__ == '__main__':
    main()
