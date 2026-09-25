#!/usr/bin/env python3
"""Build-only source mirrors and audited fixed-width kind-A ELF patch; never starts a server."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]


def replace(root, path, old, new, count=1):
    file = root / path
    text = file.read_text()
    assert text.count(old) == count, (path, old, text.count(old), count)
    file.write_text(text.replace(old, new))


def mirror(output, kind):
    output = Path(output).resolve()
    assert output.is_relative_to(ROOT / 'build') and not output.exists(), 'new build/ mirror only'
    output.mkdir(parents=True)
    for name in ('src', 'tests', 'third_party'):
        shutil.copytree(ROOT / name, output / name)
    shutil.copy2(ROOT / 'Makefile', output / 'Makefile')
    atomic = 'src/store/flatstore_atomic.inc'
    cache = 'src/store/kv_block_cache.h'
    store = 'src/store/flatstore.h'
    queue = 'src/core/read_local.h'
    if kind == 'cap':
        replace(output, atomic, 'obj_bytes_ ? KvBlockCache::kMaxBytes : 0', 'obj_bytes_')
    elif kind == 'never-drain':
        replace(output, queue, 'uint32_t drain_ready() {', 'uint32_t drain_ready() { return 0;')
    elif kind == 'eager':
        replace(output, queue, 'if (ring_.full()) force_oldest_grace();',
                'reclaim(reclaim_owner, payload, auxiliary); return;\n        if (ring_.full()) force_oldest_grace();')
    elif kind == 'borrowed':
        # Target ONLY this feature's borrow guard, never the independent atomic-pool guard.
        replace(output, atomic,
                'if (encoding == Enc::Raw && outstanding_borrows_ && is_borrowed(object->str_data()))\n            return false;\n        // Retirement',
                'if (false) return false;\n        // Retirement')
    elif kind == 'no-class':
        replace(output, cache, ' || class_nodes[cls] == kMaxNodesPerClass', '')
    elif kind == 'no-bytes':
        replace(output, cache, 'if (allocation > limit - (bytes < limit ? bytes : limit)) return false;',
                'if (ceiling == 0) return false; (void)limit;')
    elif kind == 'never-release':
        replace(output, cache, 'void release_all() {', 'void release_all() { return;')
    elif kind == 'gauge':
        replace(output, store, 'obj_bytes_ -= bytes;\n        read_local_store_state_armed()',
                'obj_bytes_ -= bytes - 1;\n        read_local_store_state_armed()')
    elif kind == 'stale-sink':
        replace(output, 'src/core/server.h',
                'void adopt_read_local_retire_sink(Shard& shard, uint32_t destination) {',
                'void adopt_read_local_retire_sink(Shard& shard, uint32_t destination) { return;')
    elif kind == 'witness':
        replace(output, cache, '#pragma once', '#pragma once\n#include "../../tests/at_recycle_witness.h"')
        replace(output, cache, 'struct KvBlockCache {',
                'struct KvBlockCache {\n    ::at_recycle::Counters witness;')
        replace(output, cache, 'void* take(size_t allocation) {',
                'void* take(size_t allocation) {\n        ++witness.takes;')
        replace(output, cache, 'if (cls >= kClasses) return nullptr;',
                'if (cls >= kClasses) { ++witness.misses; return nullptr; }')
        replace(output, cache, 'if (!block) return nullptr;',
                'if (!block) { ++witness.misses; return nullptr; }\n        ++witness.hits;')
        replace(output, cache, 'if (!eligible(allocation)) return false;',
                'if (!eligible(allocation)) { ++witness.undersize; return false; }')
        replace(output, cache, 'if (cls >= kClasses || class_nodes[cls] == kMaxNodesPerClass) return false;',
                'if (cls >= kClasses) { ++witness.outside_classes; return false; }\n'
                '        if (class_nodes[cls] == kMaxNodesPerClass) { ++witness.class_full; return false; }')
        replace(output, cache, 'if (allocation > limit - (bytes < limit ? bytes : limit)) return false;',
                'if (allocation > limit - (bytes < limit ? bytes : limit)) {\n'
                '            if (!ceiling) ++witness.empty; else ++witness.bytes_full; return false; }\n'
                '        ++witness.admitted;')
        replace(output, cache, 'void release_all() {',
                'void release_all() {\n        witness.dump(*this, "release-or-joined-shutdown");')
        # Record mutually exclusive shape rejections in the cache-eligible reclaim path only.
        text = (output / atomic).read_text()
        start = text.index('bool read_local_cache_put(')
        end = text.index('// Armed write path.', start)
        body = text[start:end]
        for old, new in (
            ('if (static_cast<Type>(object->type) != Type::String) return false;',
             'if (static_cast<Type>(object->type) != Type::String) { ++cache->witness.collection; return false; }'),
            ('if (encoding != Enc::Raw && encoding != Enc::Int) return false;',
             'if (encoding != Enc::Raw && encoding != Enc::Int) { ++cache->witness.encoding; return false; }'),
            ('is_borrowed(object->str_data()))\n            return false;',
             'is_borrowed(object->str_data())) { ++cache->witness.borrowed; return false; }')):
            assert body.count(old) == 1
            body = body.replace(old, new)
        (output / atomic).write_text(text[:start] + body + text[end:])
        replace(output, store, 'memory = alloc_raw(allocation);',
                '++read_local_store_state_armed().retire_sink.block_cache->witness.fresh;\n'
                '                memory = alloc_raw(allocation);\n'
                '                if (!memory) ++read_local_store_state_armed().retire_sink.block_cache->witness.fresh_failed;', 4)
        replace(output, queue, 'uint32_t drain_ready() {',
                'uint32_t drain_ready() {\n        block_cache_.witness.observe(block_cache_);')
        with (output / 'Makefile').open('a') as f:
            f.write('\nLDLIBS += ' + str(ROOT / 'build/at-recycle-witness-alloc.o') +
                    ' -Wl,--wrap=mallocx -Wl,--wrap=sdallocx\n')
    else:
        raise ValueError(kind)
    changes = []
    for file in sorted((output / 'src').rglob('*')):
        if file.is_file() and file.read_bytes() != (ROOT / file.relative_to(output)).read_bytes():
            changes.append(str(file.relative_to(output)))
    (output / 'MIRROR.json').write_text(json.dumps({'kind': kind, 'changed_sources': changes}, indent=2) + '\n')


def twin(source, output):
    source, output = Path(source), Path(output)
    assert source.resolve() != output.resolve()
    elf = Elf(source)
    # RAX holds obj_bytes_. RCX is dead here (subsequently overwritten by class arithmetic).
    # POST: neg rax; sbb rax,rax; and eax,786432 (11 bytes).
    # PAD-A: mov ecx,786432; cmp rax,rcx; cmova eax,ecx (11 bytes): min(obj_bytes_, bound).
    select = bytes.fromhex('48f7d8 4819c0 2500000c00')
    baseline = bytes.fromhex('b900000c00 4839c8 0f47c1')
    # GCC inferred a constant limit in the succeeding subtraction. Preserve the computed PRE
    # limit instead. Redundant operand-size prefixes plus REX.W encode ONE 64-bit subtraction
    # in the same 8 bytes. No executed NOP, loop, extra branch, stack slot or memory load.
    subtract = bytes.fromhex('b800000c00 4829f0')
    variable = bytes.fromhex('6666666666 4829f0')
    patched = bytearray(elf.data)
    patches = []
    for sym in elf.functions().values():
        body = elf.body(sym)
        if select not in body:
            continue
        assert 'reclaim' in sym['name'], sym['name']
        assert body.count(select) == body.count(subtract) == 1
        # Verify the cached byte register and compare before the constant subtraction as well.
        at = body.index(subtract)
        assert bytes.fromhex('498bb640020000 4839c6') in body[max(0, at - 20):at]
        sec = elf.sections[sym['sec']]
        file_base = sec[4] + sym['value'] - sec[3]
        for old, new in ((select, baseline), (subtract, variable)):
            off = file_base + body.index(old)
            assert len(old) == len(new)
            patched[off:off + len(old)] = new
            patches.append(dict(symbol=sym['name'], address=sym['value'] + body.index(old),
                                offset=off, old=old.hex(), new=new.hex()))
    assert len(patches) in (4, 8, 12), ('unexpected callback copies', len(patches))
    text_sec = elf.sections[elf.names.index('.text')]
    assert elf.section_data(elf.names.index('.text')).count(select) == len(patches) // 2
    output.write_bytes(patched); output.chmod(source.stat().st_mode)
    control = Elf(output)
    assert elf.sections == control.sections and elf.symbols == control.symbols
    checked = bytearray(patched)
    for p in patches:
        checked[p['offset']:p['offset'] + len(bytes.fromhex(p['old']))] = bytes.fromhex(p['old'])
    assert checked == elf.data
    return dict(kind='A: PRE admission behavior in exact POST text layout; fixed-width arithmetic selection',
                post=str(source), pad=str(output), text_bytes=text_sec[5], patches=patches,
                post_sha256=hashlib.sha256(elf.data).hexdigest(), pad_sha256=hashlib.sha256(patched).hexdigest(),
                all_other_bytes_equal=True, all_symbols_sections_and_branches_preserved=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    m = sub.add_parser('mirror'); m.add_argument('kind'); m.add_argument('output')
    t = sub.add_parser('twin'); t.add_argument('source'); t.add_argument('output'); t.add_argument('--receipt', required=True)
    a = p.parse_args()
    if a.action == 'mirror':
        mirror(a.output, a.kind)
    else:
        receipt = twin(a.source, a.output)
        Path(a.receipt).write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))
