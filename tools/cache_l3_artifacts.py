#!/usr/bin/env python3
"""Build L3's kind-A control with matched function slots, without executing a server.

A representation change cannot be disabled by patching a policy predicate. Compile
the reference representation, and reserve the union of PRE/POST function sections
at identical addresses, each sized for the larger body. Missing/smaller bodies leave
NOP space. Unlike a tail-only pad, this controls internal function placement too.
The instruction offsets *inside* changed functions necessarily differ.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile

from lbstall_artifacts import Elf


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/reb-l3'


def capture(args, **kwargs):
    return subprocess.check_output(args, cwd=kwargs.pop('cwd', ROOT), **kwargs)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_value(name, cwd=ROOT):
    return capture(['make', '--no-print-directory', '-s',
                    f'--eval=l3-value: ; @echo $({name})', 'l3-value'], cwd=cwd).decode().strip()


def text_section(elf):
    return elf.sections[elf.names.index('.text')]


def geometry(elf):
    return {n: dict(address=s[3], size=s[5], alignment=s[8])
            for n, s in zip(elf.names, elf.sections) if s[2] & 4}


def function_addresses(elf):
    result = defaultdict(list)
    for s in elf.symbols:
        if s['info'] & 15 == 2 and s['sec'] != 0:
            result[s['name']].append(s['value'])
    return {n: sorted(v) for n, v in result.items()}


def verify_layout(post, pad):
    assert geometry(post) == geometry(pad), 'executable-section geometry differs'
    old, new = function_addresses(pad), function_addresses(post)
    common = old.keys() & new.keys()
    # A local helper may be inlined away in just one TU. Its PRE-only slot stays reserved,
    # even if a same-named local helper exists in another TU. Preserve duplicate occurrences
    # when comparing; require every occurrence in the smaller set at the same address.
    drift = {}
    extra_definitions = {}
    for name in common:
        a, b = Counter(old[name]), Counter(new[name])
        if (a - b) and (b - a):
            drift[name] = (old[name], new[name])
        elif a != b:
            extra_definitions[name] = dict(pre_only=list((a-b).elements()),
                                          post_only=list((b-a).elements()))
    assert not drift, f'function placement differs: {drift}'
    return dict(executable_sections=geometry(post), common_function_names=len(common),
                common_function_addresses_equal=True, extra_local_definitions=extra_definitions)


def linker_template(compiler):
    linker = capture(compiler + ['-print-prog-name=ld']).decode().strip()
    output = capture([linker, '-pie', '--verbose']).decode()
    script = output.split('=' * 50)[1]
    match = re.search(r'  \.text\s+:\s*\{(.*?)\n  \}', script, re.S)
    if not match:
        raise RuntimeError('unrecognized GNU ld PIE text script')
    return script, match


def slots_for(arms):
    slots = {}
    for arm, objects in arms.items():
        for relative, path in objects:
            elf = Elf(path)
            assert elf.kind == 1, f'expected relocatable object: {path}'
            for name, sec in zip(elf.names, elf.sections):
                if not sec[2] & 4 or not sec[5]:
                    continue
                assert name.startswith('.text'), f'unexpected executable input: {name}'
                # COMDAT definitions share a slot across TUs. Local functions with the same
                # mangled name do not: their object path is part of the placement identity.
                key = name if sec[2] & 0x200 else relative + ':' + name
                slot = slots.setdefault(key, dict(key=key, size=0, align=1, inputs={}))
                slot['size'] = max(slot['size'], sec[5])
                slot['align'] = max(slot['align'], sec[8])
                slot['inputs'].setdefault(arm, []).append((str(path), name))
    offset = 0
    for slot in slots.values():
        alignment = max(16, slot['align'])
        offset = (offset + alignment - 1) // alignment * alignment
        slot['offset'] = offset
        offset += slot['size']
    return list(slots.values()), (offset + 15) // 16 * 16


def write_script(path, compiler, slots, end, arm, total=None):
    template, match = linker_template(compiler)
    lines = ['  .text 0x20000 :', '  {', '    FILL(0x90909090);']
    for slot in slots:
        lines.append(f'    . = {slot["offset"]};')
        for filename, section in slot['inputs'].get(arm, []):
            assert '"' not in filename and '"' not in section
            lines.append(f'    "{filename}"("{section}")')
    lines.append(f'    . = {end};')
    # Startup/CRT and archive members retain the default linker selection and ordering.
    # They must end with identical addresses in the verification below.
    lines.append(match[1])
    if total is not None:
        lines.append(f'    . = {total};')
    lines.append('  }')
    path.write_text(template[:match.start()] + '\n'.join(lines) + template[match.end():])


def link(compiler, flags, libs, objects, binary, script=None):
    args = compiler + flags + [str(p) for _, p in objects]
    if script:
        args += [f'-Wl,-T,{script}', f'-Wl,-Map,{binary}.map']
    subprocess.run(args + ['-o', str(binary)] + libs, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--jobs', type=int, default=8)
    args = parser.parse_args()
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'use taskset -c 112-127'
    assert 1 <= args.jobs <= 8
    OUT.mkdir(parents=True, exist_ok=True)
    base = capture(['git', 'rev-parse', args.base]).decode().strip()
    pre = OUT / 'pre'
    archived = capture(['git', 'archive', base, 'Makefile', 'src', 'third_party'])
    with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
        for member in archive:
            if not member.isfile():
                continue
            dest = pre / member.name
            assert dest.resolve().is_relative_to(pre.resolve())
            content = archive.extractfile(member).read()
            if dest.exists():
                assert dest.read_bytes() == content, f'PRE source drift: {dest}'
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
    compiler = shlex.split(make_value('CXX'))
    flags = shlex.split(make_value('CXXFLAGS'))
    assert '-ffunction-sections' in flags
    libs = shlex.split(make_value('JELIBS') + ' ' + make_value('LDLIBS')) + ['-lm']
    objects = shlex.split(make_value('OBJ'))
    env = dict(os.environ, CXXFLAGS=shlex.join(flags), CXX=shlex.join(compiler))
    for key in ('MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES'):
        env.pop(key, None)
    with (OUT / 'pre-build.log').open('w') as log:
        subprocess.run(['make', f'-j{args.jobs}', 'all'], cwd=pre, env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    assert shlex.split(make_value('OBJ', pre)) == objects, 'reference source list changed'
    arms = {arm: [(p, folder / p) for p in objects]
            for arm, folder in (('post', ROOT), ('pad', pre))}
    # Always reconstruct the unpadded candidate: build/tomokv might already contain the
    # previous invocation's matched layout. Keep both natural arms for the placement check.
    natural_post, natural_pre = ROOT / 'build/tomokv-unpadded', ROOT / 'build/tomokv-pre'
    link(compiler, flags, libs, arms['post'], natural_post)
    shutil.copy2(pre / 'build/tomokv', natural_pre)
    # PRE alone uses sized array-delete for the ROB's Op[]. Retain that PLT import in
    # both controls via one unreachable, identical C++ function (also preserves CET notes).
    # No constructor, call site, runtime branch, or allocation is added to either arm.
    anchor = OUT / 'link-import.cc'
    anchor.write_text('#include <new>\n'
                      'extern "C" __attribute__((used,noinline))\n'
                      'void l3_unused_array_delete(void* p) { ::operator delete[](p, std::size_t(0)); }\n')
    anchor_object = OUT / 'link-import.o'
    subprocess.run(compiler + flags + ['-c', str(anchor), '-o', str(anchor_object)], check=True)
    for arm in arms:
        arms[arm].insert(0, ('link-import.o', anchor_object))
    object_hashes = {arm: {p: digest(path) for p, path in paths} for arm, paths in arms.items()}
    slots, end = slots_for(arms)
    natural = {name: text_section(Elf(path))[5]
               for name, path in (('pre', natural_pre), ('post', natural_post))}
    pending = {arm: OUT / f'{arm}-matched' for arm in arms}
    scripts = {arm: OUT / f'{arm}.ld' for arm in arms}
    for arm in arms:
        write_script(scripts[arm], compiler, slots, end, arm)
        link(compiler, flags, libs, arms[arm], pending[arm], scripts[arm])
    total = max(text_section(Elf(path))[5] for path in pending.values())
    for arm in arms:
        write_script(scripts[arm], compiler, slots, end, arm, total)
        link(compiler, flags, libs, arms[arm], pending[arm], scripts[arm])
    post, pad = Elf(pending['post']), Elf(pending['pad'])
    layout = verify_layout(post, pad)
    for arm, paths in arms.items():
        assert object_hashes[arm] == {p: digest(path) for p, path in paths}, 'object drift'
    outputs = {'post': ROOT / 'build/tomokv', 'pad': ROOT / 'build/tomokv-pad',
               'pre': natural_pre, 'unpadded_post': natural_post}
    for arm in arms:
        shutil.copy2(pending[arm], outputs[arm])
    receipt = dict(
        kind='A: reference behaviour with the same text extent and function slots as POST',
        base=base, head=capture(['git', 'rev-parse', 'HEAD']).decode().strip(),
        compiler=capture(compiler + ['--version']).decode().splitlines()[0],
        flags=flags, libs=libs, affinity=sorted(os.sched_getaffinity(0)), jobs=args.jobs,
        **layout, reserved_slots=len(slots),
        natural_text_bytes=natural, text_bytes=total,
        limitation='Changed functions have different instructions/internal offsets; '
                   'read-only data placement is not controlled. Compare PRE to PAD too.',
        objects=object_hashes, measured=False,
        binaries={name: dict(path=str(path), sha256=digest(path)) for name, path in outputs.items()},
        slots=slots)
    (OUT / 'layout-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    (OUT / 'SHA256SUMS').write_text(''.join(
        f'{digest(path)}  {path.relative_to(ROOT)}\n' for path in outputs.values()))
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('objects', 'slots')}, indent=2))


if __name__ == '__main__':
    main()
