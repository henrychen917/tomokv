#!/usr/bin/env python3
"""Offline map structural audit and size-matched type-A control. Never starts a server."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
from lbstall_artifacts import Elf


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index('.text')][5]


def disassemble(path, name):
    result = subprocess.check_output(['objdump', '-drw', '--disassemble=' + name, str(path)], text=True)
    match = re.search(rf'<{name}>:\n(.*?)(?:\n\n|\Z)', result, re.S)
    assert match, f'missing {name} in {path}'
    return match[1]


def no_rmw_or_store(body):
    assert not re.search(r'\block\b|\b(?:xchg|cmpxchg|xadd)\b', body), 'shared reader RMW'
    assert not re.search(r'\b(?:mov[a-z]*|add[a-z]*|sub[a-z]*|inc[a-z]*|dec[a-z]*)\s+[^\n]*,\s*[^\n]*\([^\n]*\)\s*$',
                         body, re.M), 'per-read memory store'
    assert len(re.findall(r'0x28\(%rdi\)', body)) == 1, 'one pointer snapshot at original offset'


def no_db0_work(body):
    instructions = []
    for line in body.splitlines():
        match = re.match(r'\s*[0-9a-f]+:\s+(?:[0-9a-f]{2}\s+)+\s*([a-z][a-z0-9]*)', line)
        if match:
            instructions.append(match[1])
    assert instructions == ['endbr64', 'ret'], f'db0 scope performed work: {instructions}'


def layout(path):
    elf = Elf(path)
    symbol, = [s for s in elf.symbols if s['name'] == 'multidb_layout_values']
    body = elf.body(symbol)
    return list(struct.unpack('<' + 'Q' * (len(body) // 8), body))


def audit(args):
    evidence = Path(args.evidence)
    pre = disassemble(evidence / 'pre-probe.o', 'mdbqsbr_read')
    post = disassemble(evidence / 'post-probe.o', 'mdbqsbr_read')
    db0 = disassemble(evidence / 'db0-probe.o', 'mdbqsbr_scope')
    negative = disassemble(evidence / 'db0-negative-probe.o', 'mdbqsbr_scope')
    for name, body in [('pre-read', pre), ('post-read', post), ('db0-scope', db0), ('db0-negative', negative)]:
        (evidence / (name + '.asm')).write_text(body)
    no_rmw_or_store(post)
    no_db0_work(db0)
    controls = {}
    for name, fn, body in [('PRE reader', no_rmw_or_store, pre), ('DB0 work enabled', no_db0_work, negative)]:
        try:
            fn(body)
        except AssertionError as exc:
            controls[name] = f'EXPECTED FAIL: {exc}'
        else:
            raise AssertionError(f'{name} negative control passed')
    layouts = {}
    for variant in ['', '-db0']:
        before = layout(evidence / f'pre{variant}-layout.o')
        after = layout(evidence / f'post{variant}-layout.o')
        assert before == after, f'{variant} hot layout moved: {before} -> {after}'
        layouts[variant or 'multi'] = after
    arms = {str(path): {'sha256': digest(path), 'text_bytes': text_size(path)}
            for path in args.arms}
    receipt = dict(read='one acquire pointer snapshot; no shared RMW or memory store',
                   db0='scope is endbr64; ret; static assertions lock all required sizes',
                   controls=controls, layouts=layouts, arms=arms)
    (evidence / 'structural.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


def pad(args):
    base, target, output = map(Path, (args.base, args.target, args.output))
    delta = text_size(target) - text_size(base)
    assert base.resolve() != output.resolve()
    if delta >= 0:
        assembly = output.with_suffix('.S')
        obj = output.with_suffix('.o')
        assembly.write_text(f'.section .text.mdbqsbr_size_pad,"ax",@progbits\n'
                            f'.balign 1\n.fill {delta},1,0x90\n'
                            '.section .note.GNU-stack,"",@progbits\n')
        subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
        links = [shlex.split(line) for line in Path(args.link_log).read_text().splitlines()
                 if ' -o ' + str(base) + ' ' in line]
        assert links, 'missing control link command'
        command = links[-1]
        command[command.index('-o') + 1] = str(output)
        command.append(str(obj))
        subprocess.run(command, check=True)
        assert text_size(output) == text_size(target), 'padding did not match .text size'
    else:
        # Removing executable code is not an honest padding control.
        shutil.copy2(base, output)
    result = dict(kind='A: behaviour twin', base=str(base), output=str(output),
                  construction='TOMO_MDBQSBR_PAD restores PRE shared-word add/sub SC RMWs, '
                               'SC pointer publication and writer-only global-zero reclamation; '
                               'candidate object layout and coarse ClientWorkScope coverage retained',
                  unexecuted_text_padding=max(delta, 0),
                  text_size_matched=text_size(output) == text_size(target),
                  member_layout='same 120-byte DatabaseMap, counter offset 32, pointer offset 40',
                  limitations='Aggregate .text size only: individual function offsets/inlining differ. '
                              'Extra candidate scope stores and cold ownership sidecar remain. '
                              'This is not an exact instruction-address layout twin; treat attribution as limited.',
                  text_bytes=text_size(output), sha256=digest(output))
    output.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def arms(args):
    # The checked-in ABBA CLI has no arbitrary server-argument option. exec-only
    # wrappers fix the DB count equally on both arms, with no resident wrapper.
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    reference = json.loads(Path('tests/gate_measurements.json').read_text())['reference_binary']['path']
    binaries = {name: Path('build/tomokv-mdbqsbr-' + name).resolve() for name in ('pre', 'post', 'pad')}
    binaries['reference'] = Path(reference).resolve()
    manifest = {}
    for count in (1, 16):
        for name, binary in binaries.items():
            path = output / f'db{count}-{name}'
            path.write_text('#!/bin/sh\nexec ' + shlex.quote(str(binary)) +
                            f' --databases {count} "$@"\n')
            path.chmod(0o755)
            manifest[str(path)] = dict(databases=count, binary=str(binary),
                                      binary_sha256=digest(binary), wrapper_sha256=digest(path))
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    a = sub.add_parser('audit')
    a.add_argument('evidence'); a.add_argument('arms', nargs='+'); a.set_defaults(fn=audit)
    p = sub.add_parser('pad')
    p.add_argument('base'); p.add_argument('target'); p.add_argument('link_log'); p.add_argument('output')
    p.set_defaults(fn=pad)
    w = sub.add_parser('arms')
    w.add_argument('output'); w.set_defaults(fn=arms)
    args = parser.parse_args(); args.fn(args)
