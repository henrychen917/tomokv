#!/usr/bin/env python3
"""Offline ST2 artifacts. Builds serverless fixtures; never starts a server."""
import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from lbstall_artifacts import Elf


def pad(source, output):
    before = Elf(source)
    assert before.kind != 1 and Path(source).resolve() != Path(output).resolve()
    matches = [s for s in before.functions().values()
               if s['name'].startswith('_ZN') and 'storesize_published_route' in s['name']]
    assert len(matches) == 2, 'both independent database images must be controlled'
    data = bytearray(before.data)
    changed = []
    for symbol in matches:
        body = before.body(symbol)
        prefix = 4 if body.startswith(bytes.fromhex('f30f1efa')) else 0
        assert body[prefix:] == bytes.fromhex('b801000000c3'), body.hex()
        section = before.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3] + prefix + 1
        data[offset] = 0  # mov eax,1 -> mov eax,0; instruction/text sizes unchanged
        changed.append(offset)
    Path(output).write_bytes(data)
    Path(output).chmod(Path(source).stat().st_mode)
    after = Elf(output)
    assert before.sections == after.sections and before.symbols == after.symbols
    assert [i for i, (a, b) in enumerate(zip(before.data, data)) if a != b] == sorted(changed)
    return dict(kind='A: behaviour twin',
                behavior='PRE monitoring census routes; POST text sizes, symbol addresses and counter-maintenance code',
                changed_bytes=len(changed), source=str(source), output=str(output),
                source_sha256=hashlib.sha256(before.data).hexdigest(),
                sha256=hashlib.sha256(data).hexdigest())


def pre_unit(root):
    root = Path(root)
    source = root / 'source'
    assert (source / 'src/cmd/multidb.cc').exists(), 'archive frozen PRE sources first'
    output = root / 'instrumented'
    output.mkdir(exist_ok=True)
    subprocess.run(['python3', 'tests/storesize_checks.py', str(source / 'src/cmd/multidb.cc'),
                    str(output / 'multidb.cc')], check=True)
    flags = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
             '-DTOMO_JEMALLOC', '-I' + str(source), '-I' + str(source / 'src/cmd')]
    objects = []
    # Sequential: keep build output deterministic and do not compete with the
    # candidate make for the same object paths.
    for variant in ('multi', 'db0'):
        extra = [] if variant == 'multi' else ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        for name, path in [('unit', 'tests/storesize_unit.cc'), ('multidb', output / 'multidb.cc')]:
            obj = output / f'{variant}-{name}.o'
            subprocess.run(flags + extra + ['-c', str(path), '-o', str(obj)], check=True)
            objects.append(obj)
    for directory in (root / 'src', root / 'db0/src'):
        objects += [p for p in sorted(directory.rglob('*.o'))
                    if p.relative_to(directory).as_posix() not in ('main.o', 'cmd/xshard.o')
                    and p.name != 'multidb.o']
    subprocess.run(['g++', '-pthread', *map(str, objects), '-o', str(root / 'unit'),
                    '-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm'], check=True)


def handlers(before, after, output):
    """Supplement the requested hot-body audit with every emitted cmd_* body."""
    selected = re.compile(r'cmd_[a-z]|command_config_routes_all_shards|Shard::publish_size')
    rows = []
    for path in sorted(Path(before).rglob('*.o')):
        post = Path(after) / path.relative_to(before)
        a, b = Elf(path), Elf(post)
        old, new = a.functions(), b.functions()
        names = list(old)
        readable = subprocess.check_output(['c++filt'], input=('\n'.join(names) + '\n').encode()).decode().splitlines()
        for name, title in zip(names, readable):
            if not selected.search(title):
                continue
            symbol = new.get(name)
            rows.append(dict(object=str(path.relative_to(before)), name=title,
                             symbol=name,
                             pre_size=old[name]['size'], post_size=symbol['size'] if symbol else 0,
                             raw_equal=bool(symbol) and a.body(old[name]) == b.body(symbol),
                             relocation_equal=bool(symbol) and a.canonical(old[name]) == b.canonical(symbol)))
    assert rows
    Path(output).write_text(json.dumps(rows, indent=2) + '\n')
    print('Handler/publication bodies:', len(rows),
          'raw equal:', sum(row['raw_equal'] for row in rows),
          'unchanged:', sum(row['relocation_equal'] for row in rows))
    for row in rows:
        if not row['relocation_equal']:
            print('DIFF', row['object'], row['pre_size'], row['post_size'], row['name'])


def differences(before, after, audits, output):
    """Keep literal bytes and resolved call/constant deltas for every failed row.

    This supplements the original comparisons; it does not normalize anything
    further or decide that an unexplained difference is an accepted exception.
    """
    selected = {}
    for audit in audits:
        for row in json.loads(Path(audit).read_text()):
            if not row['raw_equal'] or not row['relocation_equal']:
                selected[row['object'], row['symbol']] = row
    rows = []
    objects = {}
    for (obj, name), row in sorted(selected.items()):
        if obj not in objects:
            objects[obj] = Elf(Path(before) / obj), Elf(Path(after) / obj)
        a, b = objects[obj]
        old, new = a.functions()[name], b.functions().get(name)
        pre, post = a.body(old), b.body(new) if new else b''
        ac = a.canonical(old)
        bc = b.canonical(new) if new else (b'', [])
        at = Counter(repr(target) for _, _, target in ac[1])
        bt = Counter(repr(target) for _, _, target in bc[1])
        receipt = dict(**row,
                         pre_sha256=hashlib.sha256(pre).hexdigest(),
                         post_sha256=hashlib.sha256(post).hexdigest() if new else None,
                         pre_bytes=pre.hex(), post_bytes=post.hex(),
                         pre_only_targets=list((at - bt).elements()),
                         post_only_targets=list((bt - at).elements()),
                         classification=('missing body' if not new else
                                         'address encoding only' if row['relocation_equal'] else
                                         'instruction or resolved-target difference'))
        # A moved publisher is still a failed comparison at its original
        # object, but preserve its actual replacement bytes as a separate fact.
        if not new and 'Shard12publish_size' in name:
            moved = Elf(Path(after) / 'cmd/storesize.o')
            target = moved.functions().get(name)
            if target:
                receipt['moved_definition'] = dict(
                    object='cmd/storesize.o', size=target['size'],
                    bytes=moved.body(target).hex(),
                    sha256=hashlib.sha256(moved.body(target)).hexdigest())
        rows.append(receipt)
    Path(output).write_text(json.dumps(rows, indent=2) + '\n')
    print('Literal byte receipts:', len(rows), 'in', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    pre = sub.add_parser('pre-unit')
    pre.add_argument('root')
    audit = sub.add_parser('handlers')
    audit.add_argument('before'); audit.add_argument('after'); audit.add_argument('output')
    diff = sub.add_parser('differences')
    diff.add_argument('before'); diff.add_argument('after'); diff.add_argument('output')
    diff.add_argument('audits', nargs='+')
    twin = sub.add_parser('pad')
    twin.add_argument('source'); twin.add_argument('output')
    args = parser.parse_args()
    if args.action == 'pre-unit':
        pre_unit(args.root)
    elif args.action == 'handlers':
        handlers(args.before, args.after, args.output)
    elif args.action == 'differences':
        differences(args.before, args.after, args.audits, args.output)
    else:
        print(json.dumps(pad(args.source, args.output), indent=2))
