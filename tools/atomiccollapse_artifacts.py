#!/usr/bin/env python3
"""Raw ELF audit for atomic-collapse factoring. Never executes an audited artifact.

No opcode, displacement, relocation field, register, or instruction is normalized.
Debug information and the build-id are recorded but are not executable identity.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


class Elf:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        assert self.data[:6] == b'\x7fELF\x02\x01', path
        off = struct.unpack_from('<Q', self.data, 40)[0]
        size, count, names = struct.unpack_from('<HHH', self.data, 58)
        self.sections = [struct.unpack_from('<IIQQQQIIQQ', self.data, off + i * size)
                         for i in range(count)]
        strings = self.section(names)
        self.names = [self.string(strings, s[0]) for s in self.sections]
        self.tables = {}
        self.functions = []
        for i, s in enumerate(self.sections):
            if s[1] not in (2, 11):
                continue
            strings = self.section(s[6])
            table = []
            for at in range(s[4], s[4] + s[5], s[9]):
                n, info, other, sec, value, length = struct.unpack_from('<IBBHQQ', self.data, at)
                symbol = dict(name=self.string(strings, n), info=info, other=other,
                              section=self.names[sec] if sec < count else str(sec),
                              value=value, size=length)
                table.append(symbol)
                if s[1] == 2 and info & 15 == 2:
                    self.functions.append(symbol)
            self.tables[i] = table

    @staticmethod
    def string(data, start):
        return data[start:data.index(b'\0', start)].decode(errors='replace')

    def section(self, index):
        s = self.sections[index]
        return b'' if s[1] == 8 else self.data[s[4]:s[4] + s[5]]

    def executable(self):
        return {name: dict(size=s[5], address=s[3], alignment=s[8], flags=s[2],
                           sha256=digest(self.section(i)))
                for i, (name, s) in enumerate(zip(self.names, self.sections)) if s[2] & 4}

    def relocations(self):
        result = {}
        for i, s in enumerate(self.sections):
            if s[1] not in (4, 9):
                continue
            # Object relocations against EVERY executable section; all dynamic
            # relocations in the linked image, including GOT and PLT targets.
            if s[7] and not self.sections[s[7]][2] & 4:
                continue
            rows = []
            for at in range(s[4], s[4] + s[5], s[9]):
                offset, info = struct.unpack_from('<QQ', self.data, at)
                addend = struct.unpack_from('<q', self.data, at + 16)[0] if s[1] == 4 else None
                rows.append(dict(offset=offset, kind=info & 0xffffffff, addend=addend,
                                 target=self.tables[s[6]][info >> 32]))
            result[self.names[i]] = rows
        return result

    def allocated(self):
        return {name: dict(size=s[5], address=s[3], alignment=s[8], flags=s[2],
                           sha256=digest(self.section(i)))
                for i, (name, s) in enumerate(zip(self.names, self.sections))
                if s[2] & 2 and name != '.note.gnu.build-id'}


def normalize(reference, out):
    out.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(['git', 'show', reference + ':src/store/flatstore_atomic.inc']).decode()
    a = source.index('    bool atomic_collapse(')
    b = source.index('    bool atomic_collapse_read_local(', a)
    c = source.index('    void atomic_promote_all_for_shutdown()', b)
    original = [source[a:b].strip() + '\n', source[b:c].strip() + '\n']
    for name, body in zip(('unarmed', 'armed'), original):
        (out / ('original-' + name + '.cc')).write_text(body)
    (out / 'original.diff').write_text(''.join(difflib.unified_diff(
        *[v.splitlines(True) for v in original], fromfile='unarmed', tofile='armed')))
    left = original[0].replace('        if (__builtin_expect(read_local_enabled_, false))\n'
                              '            return atomic_collapse_read_local(floor, cleanup_cutoff);\n', '')
    right = original[1]
    for name in ('atomic_collapse', 'retire_detached_obj', 'atomic_free_entry', 'atomic_exchange_physical'):
        right = right.replace(name + '_read_local', name)
    # The armed loop has redundant braces around this single statement. This
    # exact spelling is the ONLY structural normalization, separately recorded.
    right = right.replace('for (KvObj* object : atomic_collapse_retire_) {\n'
                          '            retire_detached_obj(object);\n        }',
                          'for (KvObj* object : atomic_collapse_retire_) retire_detached_obj(object);')
    lexer = r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\w+|[^\s]'
    tokens = [[' '.join(t.split()) for t in re.findall(lexer, body, re.S)] for body in (left, right)]
    for name, body in zip(('unarmed', 'armed'), tokens):
        (out / ('normalized-' + name + '.tokens')).write_text('\n'.join(body) + '\n')
    diff = '\n'.join(difflib.unified_diff(*tokens, fromfile='normalized-unarmed', tofile='normalized-armed'))
    (out / 'normalized.diff').write_text(diff)
    assert tokens[0] == tokens[1], diff
    save(out / 'normalization.json', dict(reference=reference, tokens=len(tokens[0]), equal=True,
         unarmed_line=source[:a].count('\n') + 1, armed_line=source[:b].count('\n') + 1,
         shutdown_line=source[:c].count('\n') + 1,
         normalization='dispatch; three operation names; wrapper name; whitespace; single retire-loop braces'))


def snapshot(root, out, plan):
    out.mkdir(parents=True, exist_ok=True)
    objects = re.findall(r' -c \S+ -o build/(\S+\.o)', plan.read_text())
    assert objects and len(objects) == len(set(objects)), 'complete fresh make -n plan required'
    normal = {v for v in objects if not v.startswith('db0/')}
    assert {'db0/' + v for v in normal} == set(objects) - normal
    paths = sorted(objects) + ['tomokv']

    def capture(relative):
        path = root / relative
        elf = Elf(path)
        folder = out / relative
        folder.mkdir(parents=True, exist_ok=True)
        for command, name in ((['objdump', '-drwC'], 'objdump.txt.gz'),
                              (['readelf', '-W', '-h', '-l', '-S', '-r', '-s'], 'readelf.txt.gz')):
            with gzip.open(folder / name, 'wb') as dest:
                child = subprocess.Popen(command + [str(path)], stdout=subprocess.PIPE)
                shutil.copyfileobj(child.stdout, dest)
                assert child.wait() == 0, command
        for i, s in enumerate(elf.sections):
            if s[2] & 4:
                (folder / f'section-{i}.bin').write_bytes(elf.section(i))
        result = dict(path=relative, sha256=digest(elf.data), executable=elf.executable(),
                      relocations=elf.relocations(), functions=sorted(elf.functions, key=lambda s: s['name']))
        if relative == 'tomokv':
            result['allocated'] = elf.allocated()
        save(folder / 'sections.json', {i: n for i, n in enumerate(elf.names) if elf.sections[i][2] & 4})
        save(folder / 'elf.json', result)
        return result

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(capture, paths))
    # Both wrappers and namespaces must actually be present, never a vacuous audit.
    for namespace in ('_ZN4tomo9FlatStore', '_ZN8tomo_db09FlatStore'):
        for arm in ('15atomic_collapseE', '26atomic_collapse_read_localE'):
            assert any(any(s['name'].startswith(namespace + arm) for s in row['functions'])
                       for row in rows[:-1]), (namespace, arm)
    save(out / 'inventory.json', dict(objects=len(objects), rows=rows))
    (out / 'SHA256SUMS').write_text(''.join(r['sha256'] + '  ' + str(root / r['path']) + '\n' for r in rows))
    print(f'Captured {len(objects)} objects and final executable under {out}')


def compare(pre, post, output):
    paths = sorted(p.relative_to(pre) for p in pre.rglob('*.o') if p.is_file()) + [Path('tomokv')]
    assert paths[:-1] == sorted(p.relative_to(post) for p in post.rglob('*.o') if p.is_file()), 'object inventory changed'
    rows = []
    for relative in paths:
        a, b = Elf(pre / relative), Elf(post / relative)
        x, y = a.executable(), b.executable()
        sections = {name: x.get(name) == y.get(name) for name in sorted(x.keys() | y.keys())}
        row = dict(path=str(relative), executable=sections,
                   relocations_equal=a.relocations() == b.relocations(),
                   functions_equal=sorted(a.functions, key=str) == sorted(b.functions, key=str),
                   executable_bytes_equal=all(sections.values()))
        if relative == Path('tomokv'):
            row['allocated_equal'] = a.allocated() == b.allocated()
        rows.append(row)
    passed = all(r['executable_bytes_equal'] and r['relocations_equal'] and r['functions_equal']
                 and r.get('allocated_equal', True) for r in rows)
    save(output, dict(identical=passed, rows=rows))
    print(f"Raw executable bytes equal: {sum(r['executable_bytes_equal'] for r in rows)}/{len(rows)}; "
          f"complete identity: {passed}")
    return passed


def negative(pre, out):
    out.mkdir(parents=True, exist_ok=True)
    # A copied ELF with one executable byte flipped; this file is NEVER run.
    elf = Elf(pre / 'tomokv')
    section = elf.sections[elf.names.index('.text')]
    data = bytearray(elf.data)
    data[section[4]] ^= 1
    (out / 'tomokv').write_bytes(data)
    for source in pre.rglob('*.o'):
        if not source.is_file():
            continue
        target = out / source.relative_to(pre)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.hardlink_to(source)
    assert not compare(pre, out, out / 'negative.json'), 'one-byte corruption escaped checker'
    print('PASS: one executable byte mutation rejected; corrupted artifact never executed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('normalize', 'snapshot', 'compare', 'negative'))
    parser.add_argument('paths', nargs='+', type=Path)
    args = parser.parse_args()
    if args.action == 'normalize':
        normalize(str(args.paths[0]), args.paths[1])
    elif args.action == 'snapshot':
        snapshot(*args.paths)
    elif args.action == 'compare':
        raise SystemExit(0 if compare(*args.paths) else 1)
    else:
        negative(*args.paths)


if __name__ == '__main__':
    main()
