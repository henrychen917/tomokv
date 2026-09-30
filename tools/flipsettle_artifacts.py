#!/usr/bin/env python3
"""Exact ELF proof for cleanup-flipsettle. Offline only; never executes an input ELF."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import tarfile

from lbstall_artifacts import Elf


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def symbol(elf, sym):
    return dict(name=sym['name'], section=elf.names[sym['sec']]
                if sym['sec'] < len(elf.names) else sym['sec'],
                value=sym['value'], size=sym['size'], info=sym['info'])


def inventory(path, out=None):
    elf = Elf(path)
    sections = []
    relocations = []
    for i, (name, sec) in enumerate(zip(elf.names, elf.sections)):
        # ALL executable sections, including .text, .text.*, init/fini and PLT.
        # For ET_DYN also compare all loaded data (constants, GOT, unwind, dynamic relocations).
        if sec[2] & 4 or (elf.kind != 1 and sec[2] & 2 and name != '.note.gnu.build-id'):
            data = b'' if sec[1] == 8 else elf.section_data(i)
            row = dict(name=name, type=sec[1], flags=sec[2], address=sec[3],
                       size=sec[5], alignment=sec[8], sha256=digest(data))
            if elf.kind != 1:
                row['file_offset'] = sec[4]
            sections.append(row)
            if out:
                (out / f'section-{i:04d}.bin').write_bytes(data)
        if i in elf.relocs and (sec[2] & 6 or elf.kind != 1):
            for offset, kind, target, addend in elf.relocs[i]:
                relocations.append(dict(section=name, offset=offset, kind=kind,
                                        target=symbol(elf, target), addend=addend))
        if out and sec[1] in (4, 9) and (elf.kind != 1 or elf.sections[sec[7]][2] & 6):
            (out / f'relocations-{i:04d}.bin').write_bytes(elf.section_data(i))
    functions = sorted((symbol(elf, s) for s in elf.symbols
                        if s['sec'] < len(elf.names) and elf.sections[s['sec']][2] & 4),
                       key=lambda s: (str(s['section']), s['value'], s['name'], s['info']))
    result = dict(sha256=digest(elf.data), size=len(elf.data), kind=elf.kind,
                  sections=sections, relocations=relocations, executable_symbols=functions)
    if out:
        write_json(out / 'inventory.json', result)
        for name, args in [('readelf.txt', ['readelf', '-hSWl']),
                           ('objdump.txt', ['objdump', '-drwC']),
                           ('symbols.txt', ['nm', '-anS'])]:
            with (out / name).open('wb') as f:
                subprocess.run(args + [str(path)], stdout=f, stderr=subprocess.STDOUT, check=True)
    return result


def snapshot(arm):
    paths = [Path('tomokv')] + sorted(p.relative_to(arm) for p in arm.glob('src/**/*.o'))
    paths += sorted(p.relative_to(arm) for p in arm.glob('db0/src/**/*.o'))
    assert paths[1:] and any(str(p).startswith('db0/') for p in paths), 'both namespaces required'
    files = {}
    for p in paths:
        out = arm / 'proof' / p
        out.mkdir(parents=True, exist_ok=True)
        files[str(p)] = inventory(arm / p, out)
    write_json(arm / 'inventory.json', files)
    (arm / 'SHA256SUMS').write_text(''.join(f"{v['sha256']}  {arm / p}\n" for p, v in files.items()))
    print(f'{arm}: {len(files) - 1} objects, linked ELF, raw dumps and hashes retained')


def compare_file(a, b):
    left, right = inventory(a), inventory(b)
    failures = [key for key in ('kind', 'sections', 'relocations', 'executable_symbols')
                if left[key] != right[key]]
    # Hashes are receipts, not a substitute for the required actual byte comparison.
    ea, eb = Elf(a), Elf(b)
    names_a = [s['name'] for s in left['sections']]
    names_b = [s['name'] for s in right['sections']]
    if names_a == names_b:
        for name in names_a:
            ia, ib = ea.names.index(name), eb.names.index(name)
            if ea.sections[ia][1] != 8 and ea.section_data(ia) != eb.section_data(ib):
                failures.append(f'bytes:{name}')
    return dict(equal=not failures, failures=failures, pre_sha256=left['sha256'],
                post_sha256=right['sha256'], sections=len(left['sections']),
                executable_sections=sum(bool(s[2] & 4) for s in ea.sections),
                executable_bytes=sum(s[5] for s in ea.sections if s[2] & 4),
                text_bytes=sum(s[5] for n, s in zip(ea.names, ea.sections)
                               if n == '.text' or n.startswith('.text.')),
                relocations=len(left['relocations']), executable_symbols=len(left['executable_symbols']))


def compare(pre, post, output):
    before = json.loads((pre / 'inventory.json').read_text())
    after = json.loads((post / 'inventory.json').read_text())
    assert before.keys() == after.keys(), 'object inventory changed'
    rows = {p: compare_file(pre / p, post / p) for p in before}
    result = dict(equal=all(r['equal'] for r in rows.values()), files=rows)
    write_json(output, result)
    print(f"Exact ELF checks: {sum(r['equal'] for r in rows.values())}/{len(rows)}")
    for path, row in rows.items():
        if not row['equal']:
            print(path, ', '.join(row['failures']))
    return result['equal']


def corrupt_control(path, out):
    out.mkdir(parents=True, exist_ok=True)
    elf = Elf(path)
    index = elf.names.index('.text')
    section = elf.sections[index]
    assert section[2] & 4 and section[5]
    broken = out / 'one-executable-byte-changed.DO-NOT-RUN'
    shutil.copyfile(path, broken)
    broken.chmod(0o600)
    with broken.open('r+b') as f:
        f.seek(section[4])
        f.write(bytes([elf.data[section[4]] ^ 1]))
    result = compare_file(path, broken)
    assert not result['equal'] and 'bytes:.text' in result['failures'], result
    write_json(out / 'negative-control.json', result)
    print('One executable byte changed: checker rejected; corrupted artifact never executed')


def pad(pre, post, archive, out):
    """Kind A: PRE instructions, two loop-alignment directives removed, POST function layout.

    This is a build artifact, never a production compiler policy. The assembler re-encodes the
    now-shorter branch and relocations. No instructions, stores or conditions are handwritten.
    """
    out.mkdir(parents=True, exist_ok=True)
    source = out.parent / 'PAD-source'
    source.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(source, members=(m for m in tar.getmembers()
                       if m.name.startswith(('src/', 'third_party/')) or m.name == 'Makefile'),
                       filter='data')
    commands = [shlex.split(line) for line in (pre / 'build.log').read_text().splitlines()
                if line.startswith('g++ ')]
    proofs = []
    for tree in ('src', 'db0'):
        shutil.copytree(pre / tree, out / tree, dirs_exist_ok=True)
    with (out / 'build.log').open('w') as log:
        def run(cmd, cwd=None):
            log.write(shlex.join(cmd) + '\n'); log.flush()
            subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=True)
        for name, obj, ns in [('normal', 'src/core/flipctl.o', '_ZN4tomo'),
                              ('db0', 'db0/src/core/flipctl.o', '_ZN8tomo_db0')]:
            command, = [c for c in commands if c[-1] == 'build/' + obj]
            command = command.copy()
            command[command.index('-c')] = '-S'
            command[-1] = name + '.s'
            run(command, source)
            run(['g++', '-c', name + '.s', '-o', name + '-roundtrip.o'], source)
            roundtrip = compare_file(pre / obj, source / (name + '-roundtrip.o'))
            assert roundtrip['equal'], ('unmodified PRE assembly did not round-trip', roundtrip)
            original = (source / (name + '.s')).read_text()
            fn = ns + '14FlipController6settleERNS_6ServerEjm'
            start = original.index(fn + ':')
            end = original.index('.size\t' + fn, start)
            body = original[start:end]
            alignment = '\t.p2align 4\n\t.p2align 3\n'
            assert body.count(alignment) == 2, 'review the compiler output before rebuilding PAD'
            changed = body.replace(alignment, '', 1)
            candidate = original[:start] + changed + original[end:]
            (source / (name + '-PAD.s')).write_text(candidate)
            run(['g++', '-c', name + '-PAD.s', '-o', name + '-PAD.o'], source)
            shutil.copyfile(source / (name + '-PAD.o'), out / obj)
            proofs.append(dict(namespace=name, unmodified_assembly_roundtrip=roundtrip,
                               pre_assembly_sha256=digest(original.encode()),
                               pad_assembly_sha256=digest(candidate.encode()),
                               change='remove first .p2align 4 / .p2align 3 pair inside settle; nothing else'))
        command, = [c for c in commands if 'build/tomokv' in c]
        command = [str((out / c.removeprefix('build/')).resolve()) if c.startswith('build/') else c
                   for c in command]
        run(command)
    a, b = Elf(out / 'tomokv'), Elf(post / 'tomokv')
    def functions(elf):
        return {s['name']: (s['value'], s['size'], elf.names[s['sec']]) for s in elf.symbols
                if s['info'] & 15 == 2 and 0 < s['sec'] < len(elf.names) and elf.sections[s['sec']][2] & 4}
    fa, fb = functions(a), functions(b)
    assert fa == fb, 'PAD must match EVERY linked function address and size, not just text size'
    regions = [fa[ns + '14FlipController6settleERNS_6ServerEjm'] for ns in ('_ZN4tomo', '_ZN8tomo_db0')]
    changed_bytes = 0
    for i, sec in enumerate(a.sections):
        if not sec[2] & 4: continue
        j = b.names.index(a.names[i])
        assert sec[2:6] == b.sections[j][2:6] and sec[8] == b.sections[j][8]
        for offset, (left, right) in enumerate(zip(a.section_data(i), b.section_data(j))):
            if left == right: continue
            address = sec[3] + offset
            assert any(start <= address < start + size for start, size, _ in regions), hex(address)
            changed_bytes += 1
    receipt = dict(kind='A: PRE behaviour with POST text size and function layout',
                   pre_sha256=digest((pre / 'tomokv').read_bytes()),
                   post_sha256=digest(b.data), pad_sha256=digest(a.data),
                   linked_function_addresses_and_sizes_equal=True, function_count=len(fa),
                   executable_section_layouts_equal=True,
                   executable_differences_confined_to_two_settle_bodies=True,
                   changed_executable_bytes=changed_bytes, assembly_proofs=proofs)
    write_json(out / 'layout.json', receipt)
    print(f'Kind-A PAD: {len(fa)} function addresses/sizes match POST; only two settle bodies differ')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('snapshot'); s.add_argument('arm', type=Path)
    c = sub.add_parser('compare')
    for name in ('pre', 'post', 'output'): c.add_argument(name, type=Path)
    n = sub.add_parser('negative-control')
    n.add_argument('elf', type=Path); n.add_argument('output', type=Path)
    a = sub.add_parser('pad')
    for name in ('pre', 'post', 'archive', 'output'): a.add_argument(name, type=Path)
    args = p.parse_args()
    if args.command == 'snapshot': snapshot(args.arm)
    elif args.command == 'negative-control': corrupt_control(args.elf, args.output)
    elif args.command == 'pad': pad(args.pre, args.post, args.archive, args.output)
    elif not compare(args.pre, args.post, args.output): raise SystemExit(1)


if __name__ == '__main__':
    main()
