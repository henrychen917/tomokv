#!/usr/bin/env python3
"""Offline read-path audit and kind-A behaviour twin; never executes a server."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import reorder_noop as audit
from lbstall_artifacts import Elf


def receipt(path):
    elf = Elf(path)
    return dict(path=str(path), sha256=audit.digest(path),
                text_bytes=elf.sections[elf.names.index('.text')][5])


def category(name):
    if any(part in name for part in (
            '::read_local_prefetch(', '::read_local_prefetch_capture(',
            '::read_local_capture_in(', '::read_local_validate(',
            '::prepare_local_read(', '::drain_local_reads_bounded_impl<')):
        return 'point read'
    if '::parse_and_dispatch<' in name or '::fused_pass_impl<' in name:
        return 'dispatch and schedule'
    if '::cmd_get(' in name or '::cmd_get<' in name:
        return 'GET handler'
    return None


def compare(pre, post, out):
    out.mkdir(parents=True, exist_ok=True)
    audit.self_test()  # includes added-instruction, register, branch and offset controls
    before = audit.Binary(pre, out, literal_pools=True)
    after = audit.Binary(post, out, literal_pools=True)
    audit.category = category
    rows = audit.compare(before, after, out)
    for namespace in ('tomo::', 'tomo_db0::'):
        for part in ('read_local_prefetch_capture(', 'drain_local_reads_bounded_impl<',
                     'parse_and_dispatch<', 'cmd_get<'):
            assert any(namespace in r['name'] and part in r['name'] for r in rows), (namespace, part)
    result = dict(pre=receipt(pre), post=receipt(post), rows=rows,
                  identical=all(r['equal'] for r in rows))
    (out / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    for row in rows:
        if not row['equal']:
            print('DIFF', row['diff'], row['pre_size'], row['post_size'], row['name'])
    print(f"Read-path bodies identical: {sum(r['equal'] for r in rows)}/{len(rows)}")
    assert result['identical'], 'read path changed: inspect the complete diffs before claiming NULL'


def pad(pre, post, output):
    assert output.resolve() != post.resolve(), 'patch a separate artifact'
    before, after = receipt(pre), receipt(post)
    elf = Elf(post)
    patched = bytearray(elf.data)
    patches = []
    for symbol in elf.functions().values():
        if 'local_mget_topology_demote' not in symbol['name']:
            continue
        section = elf.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3]
        body = elf.body(symbol)
        if body.startswith(bytes.fromhex('f3 0f 1e fa')):
            offset += 4
            body = body[4:]
        assert body == bytes.fromhex('b8 01 00 00 00 c3'), 'expected fixed true policy; ret'
        patched[offset + 1] = 0
        patches.append(dict(symbol=symbol['name'], offset=offset + 1))
    expected = 2 if any(n.startswith('_ZN8tomo_db0') for n in elf.functions()) else 1
    assert len(patches) == expected, 'every linked database runtime needs the control'
    assert sum(a != b for a, b in zip(elf.data, patched)) == expected
    output.write_bytes(patched)
    output.chmod(post.stat().st_mode)
    twin = Elf(output)
    assert elf.sections == twin.sections and elf.symbols == twin.symbols
    result = dict(kind='A: behaviour twin, PRE MGET retry with POST text size and layout',
                  pre=before, post=after, pad=receipt(output), patches=patches,
                  all_other_bytes_identical=True)
    output.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def cache(pre, post, out):
    out.mkdir(parents=True, exist_ok=True)
    source = out / 'cache_codegen.cc'
    source.write_text('''#include "src/core/thread.h"
extern "C" void* cache_take(tomo::KvBlockCache* c, size_t n) { return c->take(n); }
extern "C" bool cache_put(tomo::KvBlockCache* c, void* p, size_t n, size_t limit) {
    return c->put(p, n, limit);
}
extern "C" void cache_release(tomo::KvBlockCache* c) { c->release_all(); }
extern "C" size_t cache_info(const tomo::ThreadCtx* t) {
#ifdef NEGATIVE_CONTROL
    std::atomic_thread_fence(std::memory_order_seq_cst);
#endif
    return t->read_local_block_cache_bytes();
}
''')
    paths = {}
    for name, root, flags in (('pre', pre, []), ('post', post, []),
                              ('negative', post, ['-DNEGATIVE_CONTROL'])):
        paths[name] = out / (name + '.o')
        subprocess.run(['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread',
                        '-DTOMO_JEMALLOC', '-I', str(root.resolve()), *flags,
                        '-c', str(source), '-o', str(paths[name])], check=True)
    a, b, negative = (Elf(paths[name]) for name in ('pre', 'post', 'negative'))
    functions = ['cache_take', 'cache_put', 'cache_release', 'cache_info']
    rows = []
    for name in functions:
        before = a.canonical(a.functions()[name])
        after = b.canonical(b.functions()[name])
        rows.append(dict(name=name, identical=before == after,
                         pre_bytes=len(before[0]), post_bytes=len(after[0])))
    assert b.canonical(b.functions()['cache_info']) != negative.canonical(
        negative.functions()['cache_info']), 'added-fence negative control must be detected'
    result = dict(rows=rows, added_fence_control_detected=True)
    (out / 'cache.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    assert all(r['identical'] for r in rows), 'telemetry machine code changed; report the real cost'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('compare', 'pad', 'cache'))
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.action == 'compare':
        compare(args.pre, args.post, args.output)
    elif args.action == 'pad':
        pad(args.pre, args.post, args.output)
    else:
        cache(args.pre, args.post, args.output)
