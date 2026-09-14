#!/usr/bin/env python3
"""Audit the measured O1 PAD-A constraints and build a kind-B text-size control.

The measured POST deletes code, including reachable PRE functions larger than their
POST slots. Padding cannot produce the requested PRE-at-POST-layout binary. Fail
that check explicitly; never publish a candidate-behaviour binary as PAD-A.

The optional inverse control reuses the candidate's exact objects and appends only
unreferenced trap bytes to .text. Relocation-aware byte comparison verifies the
entire original .text, including gaps, rather than sampling a few hot functions.
It controls total text size and the following section's placement, not placement
of individual functions within .text. No server or workload is ever executed.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(*args):
    return subprocess.check_output(args, text=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Elf:
    """Only the little-endian ELF64/x86-64 tables this verifier consumes."""

    def __init__(self, path):
        self.path = path
        self.data = path.read_bytes()
        require(self.data[:7] == b'\x7fELF\x02\x01\x01', 'expected ELF64 little endian')
        header = struct.unpack_from('<16sHHIQQQIHHHHHH', self.data)
        require(header[2] == 62, 'expected x86-64')
        self.entry = header[4]
        self.sections = []
        for index in range(header[12]):
            fields = struct.unpack_from('<IIQQQQIIQQ', self.data, header[6] + index * header[11])
            self.sections.append(dict(zip(
                ('name_offset', 'type', 'flags', 'addr', 'offset', 'size', 'link', 'info',
                 'align', 'entsize'), fields)))
        names = self.contents(self.sections[header[13]])
        for section in self.sections:
            section['name'] = self.string(names, section['name_offset'])
        self.by_name = {s['name']: s for s in self.sections}
        self.symbol_tables = {}
        for index, section in enumerate(self.sections):
            if section['type'] not in (2, 11):
                continue
            names = self.contents(self.sections[section['link']])
            symbols = []
            for offset in range(section['offset'], section['offset'] + section['size'], 24):
                name, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', self.data, offset)
                symbols.append(dict(name=self.string(names, name), type=info & 15, info=info, other=other,
                                    section=shndx, value=value, size=size))
            self.symbol_tables[index] = symbols
        self.symbols = next(self.symbol_tables[i] for i, s in enumerate(self.sections)
                            if s['name'] == '.symtab')

    @staticmethod
    def string(data, offset):
        return data[offset:data.index(0, offset)].decode()

    def contents(self, section):
        if section['type'] == 8:  # SHT_NOBITS
            return b''
        return self.data[section['offset']:section['offset'] + section['size']]

    def text_functions(self):
        return [s for s in self.symbols if s['type'] == 2 and
                s['section'] < len(self.sections) and
                self.sections[s['section']]['name'] == '.text' and s['size']]

    def text_relocations(self):
        # Do not guess a relocation's width: unsupported types stop verification.
        widths = {2: 4, 4: 4, 9: 4, 23: 4, 41: 4, 42: 4}
        result = []
        text = self.by_name['.text']
        for section in self.sections:
            if section['type'] != 4 or self.sections[section['info']]['name'] != '.text':
                continue
            symbols = self.symbol_tables[section['link']]
            for offset in range(section['offset'], section['offset'] + section['size'], 24):
                address, info, addend = struct.unpack_from('<QQq', self.data, offset)
                kind = info & 0xffffffff
                require(kind in widths, f'unsupported .text relocation {kind}')
                symbol = symbols[info >> 32]
                shndx = symbol['section']
                target = self.sections[shndx] if 0 < shndx < len(self.sections) else None
                identity = (symbol['name'], target['name'] if target else shndx,
                            symbol['value'] - target['addr'] if target and symbol['type'] != 6
                            else symbol['value'])
                result.append((address - text['addr'], kind, widths[kind], identity, addend))
        require(result, 'link with --emit-relocs before verifying')
        return sorted(result)


def audit(pre, post, out):
    pre_funcs, post_funcs = pre.text_functions(), post.text_functions()
    # Duplicate local symbol spellings are not safe correspondence keys.
    pre_counts, post_counts = Counter(s['name'] for s in pre_funcs), Counter(s['name'] for s in post_funcs)
    by_pre = {s['name']: s for s in pre_funcs if pre_counts[s['name']] == 1}
    by_post = {s['name']: s for s in post_funcs if post_counts[s['name']] == 1}
    common = sorted(by_pre.keys() & by_post.keys(), key=lambda name: by_post[name]['value'])
    collisions = []
    for name, following in zip(common, common[1:]):
        a, b, n = by_pre[name], by_post[name], by_post[following]
        if b['value'] < n['value'] < b['value'] + a['size']:
            collisions.append(dict(symbol=name, following=following,
                pre_address=a['value'], pre_bytes=a['size'], post_address=b['value'],
                post_bytes=b['size'], next_post_address=n['value'],
                overlap_bytes=b['value'] + a['size'] - n['value']))
    collisions.sort(key=lambda row: row['overlap_bytes'], reverse=True)
    shrink = pre.by_name['.text']['size'] - post.by_name['.text']['size']
    require(collisions and shrink > 0, 'measured O1 impossibility witness no longer applies')
    result = dict(requested_kind='A', status='INFEASIBLE_WITH_UNCHANGED_BODIES_AND_PADDING_ONLY',
                  pre_sha256=sha(pre.path), post_sha256=sha(post.path),
                  pre_text_bytes=pre.by_name['.text']['size'],
                  post_text_bytes=post.by_name['.text']['size'], shrink_bytes=shrink,
                  collisions=collisions, binary_created=False)
    (out / 'PAD-A-infeasible.json').write_text(json.dumps(result, indent=2) + '\n')
    witness = collisions[0]
    proof = [f'PRE SHA-256: {result["pre_sha256"]}', f'POST SHA-256: {result["post_sha256"]}',
             'Exact PRE bodies at POST addresses collide; padding cannot shorten a body.',
             json.dumps(witness, indent=2)]
    for elf in (pre, post):
        proof.extend([run('objdump', '-h', str(elf.path)),
                      run('objdump', '-d', '-w', '--disassemble=' + witness['symbol'], str(elf.path)),
                      run('objdump', '-d', '-w', '--disassemble=' + witness['following'], str(elf.path))])
    # Keep the callers too: the oversized body is part of the real owner loop.
    text = run('objdump', '-d', '-w', '--no-show-raw-insn', str(pre.path))
    caller, calls = '', []
    for line in text.splitlines():
        if re.match(r'^[0-9a-f]+ <.*>:$', line):
            caller = line
        if '<' + witness['symbol'] + '>' in line and not line.endswith('>:'):
            calls.append(caller + '\n' + line)
    require(calls, 'oversized PRE body has no recorded direct callers')
    proof.append('PRE direct callers:\n' + '\n'.join(calls))
    (out / 'PAD-A-infeasible.objdump').write_text('\n\n'.join(proof) + '\n')
    return result


def runtime_equal(original, relink):
    require(original.entry == relink.entry, 'entry point moved during reference relink')
    def dynamic_symbols(elf):
        # --emit-relocs adds section headers, so st_shndx numbers change even
        # though each dynamic symbol still names exactly the same section.
        index = next(i for i, s in enumerate(elf.sections) if s['name'] == '.dynsym')
        return [(s['name'], s['info'], s['other'], s['value'], s['size'],
                 elf.sections[s['section']]['name'] if 0 < s['section'] < len(elf.sections)
                 else s['section']) for s in elf.symbol_tables[index]]
    def allocated(elf):
        return {s['name']: (s['addr'], s['size'], s['flags'],
                           dynamic_symbols(elf) if s['name'] == '.dynsym' else elf.contents(s))
                for s in elf.sections if s['flags'] & 2 and s['size'] and
                s['name'] != '.note.gnu.build-id'}
    require(allocated(original) == allocated(relink),
            'reference relink differs from measured candidate in an allocated section')


def verify_inverse(reference, padded, target_size):
    ref_text, pad_text = reference.by_name['.text'], padded.by_name['.text']
    require(ref_text['addr'] == pad_text['addr'], '.text address moved')
    require(pad_text['size'] == target_size, 'PAD-B text size does not equal PRE')
    require(reference.entry == padded.entry, 'entry point moved')
    functions = lambda elf: sorted((s['name'], s['value'], s['size']) for s in elf.text_functions())
    require(functions(reference) == functions(padded), 'candidate function bodies moved or changed size')
    relocations = reference.text_relocations()
    require(relocations == padded.text_relocations(), '.text relocation target/addend changed')
    a = bytearray(reference.contents(ref_text))
    full = padded.contents(pad_text)
    b = bytearray(full[:len(a)])
    for offset, kind, width, identity, addend in relocations:
        require(0 <= offset <= len(a) - width, 'relocation outside original .text')
        if kind in (9, 41, 42):  # These measured objects retain the GOT indirection.
            section = '.got'
        elif kind == 23:  # TPOFF32 is relative to the unchanged TLS block, not its VMA.
            section = None
            for name in ('.tdata', '.tbss'):
                require(reference.by_name[name]['size'] == padded.by_name[name]['size'],
                        'TLS block size changed')
        else:  # PC32 / PLT32: code/PLT addresses stay fixed; data section VMAs move.
            section = identity[1] if isinstance(identity[1], str) else None
        expected_delta = (padded.by_name[section]['addr'] - reference.by_name[section]['addr']
                          if section else 0)
        actual_delta = (int.from_bytes(b[offset:offset + width], 'little') -
                        int.from_bytes(a[offset:offset + width], 'little'))
        require((actual_delta - expected_delta) % (1 << (8 * width)) == 0,
                'relocation instruction bytes have the wrong target displacement')
        a[offset:offset + width] = bytes(width)
        b[offset:offset + width] = bytes(width)
    require(a == b, 'non-relocation instruction/text bytes changed')
    require(full[len(a):] == b'\xcc' * (target_size - len(a)), 'padding is not all trap bytes')
    begin, end = ref_text['addr'] + ref_text['size'], pad_text['addr'] + pad_text['size']
    require(not any(begin <= s['value'] < end for s in padded.symbols),
            'symbol points into padding')
    return dict(kind='B', scope='total .text size; intra-.text function placement remains POST',
                text_bytes=target_size, pad_bytes=target_size - len(a),
                text_functions_verified=len(functions(reference)),
                relocation_fields_verified=len(relocations),
                normalized_original_text_sha256=hashlib.sha256(a).hexdigest(),
                padding_start=begin, padding_end=end)


def build_inverse(directory, pre, candidate_name, manifest, out):
    arm = manifest['arms'][candidate_name]
    binary = directory / Path(arm.get('binary', arm.get('path', ''))).name
    require(sha(binary) == arm['sha256'], f'digest mismatch: {binary}')
    original = Elf(binary)
    size = pre.by_name['.text']['size']
    delta = size - original.by_name['.text']['size']
    require(delta > 0, 'an inverse padding control cannot shrink .text')
    suffix = 'PAD-B' if binary.name == 'tomokv-POST' else binary.name.removeprefix('tomokv-') + '-PAD-B'
    target = directory / ('tomokv-' + suffix)
    reference = out / (suffix + '-reference-relocs')
    script_reference = out / (suffix + '-script-reference')
    script = out / (suffix + '.ld')
    # Ubuntu's g++ driver supplies PIE, NOW and RELRO. Validate the unmodified
    # script too: omitting NOW, for example, silently changes GOT placement.
    default_script = run('ld', '-pie', '-z', 'now', '-z', 'relro', '--verbose').split('=' * 50)[1].strip() + '\n'
    default_path = out / (suffix + '-default.ld')
    default_path.write_text(default_script)
    anchor = '    *(.gnu.warning)\n'
    require(default_script.count(anchor) == 1, 'default ld .text script changed')
    script.write_text(default_script.replace(anchor, anchor +
        '    /* Unreferenced padding; no function or instruction is replaced. */\n'
        f'    FILL(0xcccccccc);\n    . += {delta};\n'))
    flags = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread']
    objects = arm['objects']
    require(all(Path(p).is_file() for p in objects), 'missing measured-arm object')
    libraries = ['-ljemalloc', '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
    rules = ['.DELETE_ON_ERROR:', '.PHONY: all', f'all: {reference} {script_reference} {target}']
    for path, linker_script in ((reference, None), (script_reference, default_path), (target, script)):
        extra = ['-Wl,-T,' + str(linker_script)] if linker_script else []
        command = flags + objects + ['-o', str(path)] + libraries + ['-Wl,--emit-relocs'] + extra
        rules += [str(path) + ': ' + ' '.join(objects) + (' ' + str(linker_script) if extra else ''),
                  '\t' + shlex.join(command)]
    makefile = out / (suffix + '.mk')
    makefile.write_text('\n'.join(rules) + '\n')
    with (out / (suffix + '-build.log')).open('w') as log:
        subprocess.run(['make', '-j8', '-f', str(makefile)], check=True,
                       stdout=log, stderr=subprocess.STDOUT)
    ref, pad = Elf(reference), Elf(target)
    runtime_equal(original, ref)
    runtime_equal(original, Elf(script_reference))
    result = verify_inverse(ref, pad, size)
    # Corrupt instructions, fixups and padding independently. A blanket mask of
    # relocation bytes would incorrectly accept the second negative control.
    negative_controls = {}
    for label, offset, expected in (
        ('instruction', 0, 'non-relocation instruction/text bytes changed'),
        ('relocation', ref.text_relocations()[0][0],
         'relocation instruction bytes have the wrong target displacement'),
        ('padding', original.by_name['.text']['size'], 'padding is not all trap bytes')):
        bad = Elf(target)
        data = bytearray(bad.data)
        data[bad.by_name['.text']['offset'] + offset] ^= 1
        bad.data = bytes(data)
        try:
            verify_inverse(ref, bad, size)
        except ValueError as error:
            require(str(error) == expected, str(error))
        else:
            raise ValueError('negative control accepted corrupted ' + label)
        negative_controls[label] = 'rejected'
    result.update(binary=str(target), sha256=sha(target), behaviour_reference=str(binary),
                  behaviour_reference_sha256=sha(binary), reference_relink_runtime_equal=True,
                  default_script_runtime_equal=True, negative_controls=negative_controls, measured=False,
                  objects=[dict(path=p, sha256=sha(Path(p))) for p in objects])
    (out / (suffix + '-proof.json')).write_text(json.dumps(result, indent=2) + '\n')
    # Full disassembly is a receipt. The automated proof above covers every byte of
    # the original text, not just functions printed with convenient symbol names.
    for path, label in ((reference, 'reference'), (target, 'padded')):
        with (out / (suffix + '-' + label + '.objdump')).open('w') as log:
            subprocess.run(['objdump', '-drw', '-j', '.text', str(path)], check=True, stdout=log)
    print(f'Built {target.name}: {result["sha256"]}; {result["text_functions_verified"]} bodies verified', flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('build/overlap-O1'))
    parser.add_argument('--build-inverse', action='store_true')
    args = parser.parse_args()
    require(set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'run under taskset -c 112-127')
    directory = args.directory.resolve()
    out = directory / 'pad-proof'
    out.mkdir(exist_ok=True)
    pre, post = Elf(directory / 'tomokv-PRE'), Elf(directory / 'tomokv-POST')
    manifest = json.loads((directory / 'builds.json').read_text())
    require(sha(pre.path) == manifest['arms']['PRE']['sha256'], 'PRE digest mismatch')
    require(sha(post.path) == manifest['arms']['06-full-bundle']['sha256'], 'POST digest mismatch')
    result = dict(affinity=sorted(os.sched_getaffinity(0)), jobs=8, pad_a=audit(pre, post, out))
    print(f'PAD-A infeasible: .text shrank {result["pad_a"]["shrink_bytes"]} bytes; '
          f'{len(result["pad_a"]["collisions"])} overlapping PRE bodies at POST addresses.', flush=True)
    if args.build_inverse:
        require(run('g++', '--version').splitlines()[0] == manifest['compiler'], 'compiler changed')
        result['inverse_controls'] = [build_inverse(directory, pre, '06-full-bundle', manifest, out)]
        continuation = json.loads((directory / 'continuation-builds.json').read_text())
        result['inverse_controls'].append(build_inverse(directory, pre, 'POST-t01', continuation, out))
    (out / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
