#!/usr/bin/env python3
"""RL1 offline layout evidence. Does not start a server or a load generator.

PAD-A retargets each covered-fence branch to unconditionally bypass the store.
It retains POST's complete section/symbol tables and every other byte. Plans
are written before mutation; verification independently derives them again.
Run all commands with taskset -c 112-127.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def disassemble(path, symbol=None):
    cmd = ['objdump', '-dw']
    if symbol:
        cmd += ['--disassemble=' + symbol]
    return subprocess.check_output(cmd + [str(path)], text=True)


def instructions(text):
    rows = []
    owner = None
    for line in text.splitlines():
        head = re.fullmatch(r'([0-9a-f]+) <(.+)>:', line)
        if head:
            owner = head[2]
        match = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
        if match:
            rows.append((int(match[1], 16), bytes.fromhex(match[2]), match[3], owner))
    return rows


def tables(elf, out, label):
    functions = sorted((s['name'], s['value'], s['size'], elf.names[s['sec']])
                       for s in elf.symbols if s['info'] & 15 == 2 and
                       0 < s['sec'] < len(elf.sections))
    ftext = 'symbol\taddress\tsize\tsection\n' + ''.join(
        f'{n}\t{v:016x}\t{z}\t{s}\n' for n, v, z, s in functions)
    stext = 'section\taddress\toffset\tsize\talignment\tflags\n' + ''.join(
        f'{n}\t{s[3]:016x}\t{s[4]:x}\t{s[5]}\t{s[8]}\t{s[2]:x}\n'
        for n, s in zip(elf.names, elf.sections))
    out.mkdir(parents=True, exist_ok=True)
    (out / f'{label}-functions.tsv').write_text(ftext)
    (out / f'{label}-sections.tsv').write_text(stext)
    return dict(functions=len(functions), function_table_sha256=sha(ftext.encode()),
                section_table_sha256=sha(stext.encode()), binary_sha256=sha(elf.data),
                text_bytes=elf.sections[elf.names.index('.text')][5])


def post_plan(source):
    elf = Elf(source)
    # Aliased lambda ordinals denote the same physical helper. Require both
    # database namespaces and both Fair variants, exactly once per address.
    pattern = re.compile(r'_ZZNK?(4tomo|8tomo_db0)7ExLoopTILb1EE30drain_local_reads_bounded_implILb([01])EEEjjENKUljE[0-9]*_clEj')
    selected = {}
    for name, symbol in elf.functions().items():
        if pattern.fullmatch(name):
            selected.setdefault(symbol['value'], []).append(symbol)
    assert len(selected) == 4, ('PAD completion helper inventory', list(selected))
    variants = set()
    plans = []
    for address, aliases in sorted(selected.items()):
        symbol = sorted(aliases, key=lambda s: s['name'])[0]
        variants.add(pattern.fullmatch(symbol['name']).groups())
        body = elf.body(symbol)
        # mov 0x68(%rdx),%rax; bt %rax,%rcx; jae +8;
        # movq $-1,0x68(%rdx). The change is jae -> jmp, same target.
        sequence = bytes.fromhex('48 8b 42 68 48 0f a3 c1 73 08 48 c7 42 68 ff ff ff ff')
        assert body.count(sequence) == 1, ('PAD expected fence instructions', symbol['name'])
        start = body.index(sequence)
        rows = instructions(disassemble(source, symbol['name']))
        found = [(a, raw, asm) for a, raw, asm, _ in rows
                 if address + start <= a < address + start + len(sequence)]
        assert [raw for _, raw, _ in found] == [sequence[:4], sequence[4:8],
                                               sequence[8:10], sequence[10:]]
        section = elf.sections[symbol['sec']]
        plans.append(dict(symbol=symbol['name'], aliases=sorted(s['name'] for s in aliases),
                          address=address + start + 8,
                          offset=section[4] + address + start + 8 - section[3],
                          before='7308', after='eb08',
                          target=address + start + len(sequence),
                          purpose='PRE: bypass chunk-completion fence clear unconditionally',
                          sequence_address=address + start, sequence=sequence.hex(),
                          disassembly=found_as_json(found)))
    assert variants == {(ns, b) for ns in ('4tomo', '8tomo_db0') for b in ('0', '1')}
    return dict(kind='A: behaviour twin', source_sha256=sha(elf.data), patches=plans)


def found_as_json(found):
    return [dict(address=a, bytes=raw.hex(), instruction=asm) for a, raw, asm in found]


def verify(source, output, plan):
    assert plan == post_plan(source), 'PAD plan does not match independent inventory'
    before, after = Elf(source), Elf(output)
    assert before.sections == after.sections, 'PAD section table moved'
    assert before.symbols == after.symbols, 'PAD symbol table moved'
    restored = bytearray(after.data)
    for patch in plan['patches']:
        at = patch['offset']
        old, new = bytes.fromhex(patch['before']), bytes.fromhex(patch['after'])
        assert restored[at:at + len(new)] == new, 'PAD planned retarget missing'
        assert patch['address'] + 2 + struct.unpack('<b', new[1:])[0] == patch['target']
        restored[at:at + len(new)] = old
    assert bytes(restored) == before.data, 'PAD unplanned byte change'


def moved_symbol(data, elf, name):
    changed = bytearray(data)
    symtab = elf.sections[elf.names.index('.symtab')]
    index = next(i for i, s in enumerate(elf.symbols) if s['name'] == name)
    offset = symtab[4] + index * symtab[9] + 8
    value = struct.unpack_from('<Q', changed, offset)[0]
    struct.pack_into('<Q', changed, offset, value + 1)
    return changed


def pad(source, output):
    assert source.resolve() != output.resolve(), 'patch a separate copy'
    output.parent.mkdir(parents=True, exist_ok=True)
    plan = post_plan(source)
    save(output.parent / 'planned-retargets.json', plan)
    before = Elf(source)
    changed = bytearray(before.data)
    for patch in plan['patches']:
        at = patch['offset']
        changed[at:at + 2] = bytes.fromhex(patch['after'])
    output.write_bytes(changed)
    output.chmod(0o755)
    verify(source, output, plan)
    a = tables(before, output.parent, 'POST')
    b = tables(Elf(output), output.parent, 'PAD-A')
    assert a['function_table_sha256'] == b['function_table_sha256']
    assert a['section_table_sha256'] == b['section_table_sha256']
    controls = {}
    first = plan['patches'][0]
    missing = bytearray(changed)
    missing[first['offset']] = 0x73
    one_byte = bytearray(changed)
    one_byte[before.sections[before.names.index('.text')][4]] ^= 1
    for name, data, expected in (
        ('missing-retarget', missing, 'PAD planned retarget missing'),
        ('moved-symbol', moved_symbol(changed, before, first['symbol']), 'PAD symbol table moved'),
        ('one-byte', one_byte, 'PAD unplanned byte change')):
        path = output.parent / f'{name}.NEVER-RUN'
        path.write_bytes(data)
        path.chmod(0o600)
        try:
            verify(source, path, plan)
        except AssertionError as error:
            assert str(error) == expected, (name, str(error))
            controls[name] = dict(rejected=True, assertion=str(error), sha256=sha(data))
        else:
            raise AssertionError(f'PAD accepted {name}')
    save(output.parent / 'negative-controls.json', controls)
    save(output.parent / 'proof.json', dict(kind=plan['kind'], post=a, pad=b,
         exact_function_and_section_tables=True, all_other_bytes_identical=True,
         planned_retargets=len(plan['patches']), changed_bytes=sum(x != y for x, y in zip(before.data, changed)),
         controls=controls))
    print(f'PASS PAD-A: {len(plan["patches"])} planned retargets; exact function/section tables; all 3 controls rejected')


def audit(pre, post, out):
    sys.path.insert(0, str(ROOT / 'tests'))
    import reorder_noop as auditlib
    out.mkdir(parents=True, exist_ok=True)
    auditlib.self_test()
    before = auditlib.Binary(pre, out, literal_pools=True)
    after = auditlib.Binary(post, out, literal_pools=True)
    auditlib.category = lambda name: 'io' if re.search(
        r'IoLoop::(?:r7_)?(?:run_loop|flush_ready|parse_and_dispatch|pipeline_pass|ifid_pipe_parse)|'
        r'::cmd_get(?:<|\()', name) else None
    rows = auditlib.compare(before, after, out)
    a, b = Elf(pre), Elf(post)
    old, new = a.functions(), b.functions()
    names = sorted(set(old) | set(new))
    readable = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    changed = []
    selected = []
    for name, demangled in zip(names, readable):
        x, y = old.get(name), new.get(name)
        if not x or not y or x['size'] != y['size']:
            changed.append(dict(symbol=name, name=demangled, pre=x, post=y))
        if not (x and y) or not auditlib.category(demangled) or 'lambda' in demangled:
            continue
        def describe(path, symbol):
            code = instructions(disassemble(path, name))
            heads = {}
            calls = []
            for at, raw, asm, _ in code:
                branch = re.fullmatch(r'(j[a-z]+)\s+([0-9a-f]+) <.*>', asm)
                if branch and symbol['value'] <= int(branch[2], 16) < at:
                    target = int(branch[2], 16)
                    heads.setdefault(target, []).append(at)
                call = re.fullmatch(r'call\s+[0-9a-f]+ <([^>]+)>', asm)
                if call:
                    calls.append(call[1])
            return dict(address=symbol['value'], size=symbol['size'],
                        mod64=symbol['value'] % 64, calls=calls,
                        backward_branch_targets=[dict(address=t, offset=t-symbol['value'],
                            mod16=t%16, mod32=t%32, mod64=t%64, sources=src)
                            for t, src in sorted(heads.items())])
        selected.append(dict(symbol=name, name=demangled,
                             pre=describe(pre,x), post=describe(post,y)))
    save(out / 'audit.json', dict(pre=tables(a,out,'PRE'), post=tables(b,out,'POST'),
         instruction_comparisons=rows, size_changes=changed, hot_functions=selected,
         loop_head_caveat='Static backward-branch targets, not sampled execution counts.'))
    print(f'IO/GET normalized instruction identity: {sum(r["equal"] for r in rows)}/{len(rows)}; '
          f'{len(changed)} symbol size/inventory changes; see {out}/audit.json')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    s = sub.add_parser('pad')
    s.add_argument('source', type=Path); s.add_argument('output', type=Path)
    s = sub.add_parser('verify')
    s.add_argument('source', type=Path); s.add_argument('output', type=Path)
    s.add_argument('plan', type=Path)
    s = sub.add_parser('audit')
    s.add_argument('pre', type=Path); s.add_argument('post', type=Path); s.add_argument('out', type=Path)
    args = p.parse_args()
    if args.action == 'pad':
        pad(args.source,args.output)
    elif args.action == 'verify':
        verify(args.source,args.output,json.loads(args.plan.read_text()))
    else:
        audit(args.pre,args.post,args.out)
