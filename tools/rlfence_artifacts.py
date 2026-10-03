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
import tarfile
import io

from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
FROZEN_POST = '7dc81148e2f19af536d7fc267b541bd7f1f95668'


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


def identity(reference, candidate, out):
    """Literal comparison, including every defined function and duplicate name.

    A newer mainline can legitimately differ from frozen ALT. Record those
    differences instead of treating normalized instructions as byte identity.
    Use the separate audit command to explain changed IO instructions.
    """
    before, after = Elf(reference), Elf(candidate)
    a, b = tables(before, out, 'REFERENCE'), tables(after, out, 'CANDIDATE')

    def inventory(elf):
        groups = {}
        for symbol in elf.symbols:
            if symbol['info'] & 15 == 2 and 0 < symbol['sec'] < len(elf.sections):
                groups.setdefault(symbol['name'], []).append(symbol)
        return {(name, ordinal): symbol for name, symbols in groups.items()
                for ordinal, symbol in enumerate(sorted(symbols, key=lambda s:
                    (s['value'], s['size'], elf.names[s['sec']])))}

    def describe(elf, symbol):
        if symbol is None:
            return None
        return dict(address=symbol['value'], size=symbol['size'],
                    section=elf.names[symbol['sec']], body_sha256=sha(elf.body(symbol)))

    old, new = inventory(before), inventory(after)
    differences = []
    for name, ordinal in sorted(old.keys() | new.keys()):
        x, y = old.get((name, ordinal)), new.get((name, ordinal))
        left, right = describe(before, x), describe(after, y)
        if left != right:
            differences.append(dict(symbol=name, occurrence=ordinal, reference=left,
                candidate=right, literal_bytes_equal=bool(x is not None and y is not None and
                    before.body(x) == after.body(y))))
    save(out / 'differing-functions.json', differences)

    executable = []
    for name in sorted({n for elf in (before, after) for n, s in
                        zip(elf.names, elf.sections) if s[2] & 4}):
        def section(elf):
            if name not in elf.names:
                return None
            index = elf.names.index(name); s = elf.sections[index]
            return dict(address=s[3], size=s[5], alignment=s[8],
                        sha256=sha(elf.section_data(index)))
        left, right = section(before), section(after)
        executable.append(dict(section=name, reference=left, candidate=right, equal=left == right))

    hot = []
    for name in (
        '_ZN8tomo_db06IoLoop8run_loopILb0ELb0ELb0ELb1ELh0ELb0EEEvv',
        '_ZN8tomo_db06IoLoop11flush_readyILb0ELb0ELb1ELb0ELb1ELb0EEEjv',
        '_ZN8tomo_db06IoLoop18parse_and_dispatchILb0ELj32ELb0ELb0EEENS0_14DispatchResultEPNS_6ClientE',
    ):
        def loops(elf, path, inv):
            symbol = inv[(name, 0)]
            targets = set()
            for at, _, asm, _ in instructions(disassemble(path, name)):
                match = re.fullmatch(r'j[a-z]+\s+([0-9a-f]+) <.*>', asm)
                if match and symbol['value'] <= int(match[1], 16) < at:
                    targets.add(int(match[1], 16))
            return dict(**describe(elf, symbol), backward_branch_targets=[
                dict(address=t, offset=t-symbol['value'], mod16=t%16, mod64=t%64)
                for t in sorted(targets)])
        hot.append(dict(symbol=name, reference=loops(before, reference, old),
                        candidate=loops(after, candidate, new)))
    exact = a['function_table_sha256'] == b['function_table_sha256'] and all(
        row['equal'] for row in executable)
    save(out / 'identity.json', dict(reference=a, candidate=b,
        exact_function_table_and_executable_sections=exact,
        differing_functions=len(differences), differences='differing-functions.json',
        executable_sections=executable, hot_functions=hot,
        caveat='Literal bytes; no displacement masking. Duplicate names paired by address order. '
               'Static backward branches are not a profile. DWARF/build ID excluded from executable identity.'))
    print(f'Executable/address identity: {exact}; {len(differences)} differing function entries; see {out}')


def post_plan(source):
    elf = Elf(source)
    if '.rlfence' in elf.names:
        return island_plan(source, elf)
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


def island_plan(source, elf):
    """Cover the entire ALT island section, including its return edges.

    This also accepts serverless unit ELFs, whose islands use other registers
    and ROB placements. Every emitted island must have the same six operations;
    never find/patch arbitrary byte patterns outside instruction boundaries.
    """
    section = elf.sections[elf.names.index('.rlfence')]
    text = subprocess.check_output(['objdump', '-dw', '-j', '.rlfence', str(source)], text=True)
    rows = instructions(text)
    assert rows and len(rows) % 6 == 0, 'ALT complete island instruction inventory'
    assert rows[0][0] == section[3] and rows[-1][0] + len(rows[-1][1]) == section[3] + section[5]
    for one, two in zip(rows, rows[1:]):
        assert one[0] + len(one[1]) == two[0], 'ALT unaccounted island bytes'
    plans = []
    funcs = [s for s in elf.symbols if s['info'] & 15 == 2 and s['size']]
    for i in range(0, len(rows), 6):
        load, bt, branch, store, retire, back = rows[i:i + 6]
        match = re.fullmatch(r'mov\s+(.+),%rsi', load[2])
        assert match, ('ALT fence load', load)
        operand = match[1]
        match = re.fullmatch(r'bt\s+%rsi,(%[a-z0-9]+)', bt[2])
        assert match, ('ALT slot membership', bt)
        bits_reg = match[1]
        assert re.fullmatch(r'movq\s+\$0xffffffffffffffff,' + re.escape(operand), store[2]), ('ALT fence store', store)
        assert re.fullmatch(r'andn\s+%[a-z0-9]+,' + re.escape(bits_reg) + ',' + re.escape(bits_reg), retire[2]), ('ALT retire', retire)
        assert branch[1][0] == 0x73 and len(branch[1]) == 2
        assert branch[0] + 2 + struct.unpack('<b', branch[1][1:])[0] == retire[0], 'ALT skip target'
        assert len(back[1]) == 5 and back[1][0] == 0xe9, 'ALT return edge'
        continuation = back[0] + 5 + struct.unpack('<i', back[1][1:])[0]
        entry = continuation - 5
        callers = [s for s in funcs if s['value'] <= entry < s['value'] + s['size']]
        assert callers, 'ALT unowned entry'
        caller = sorted(callers, key=lambda s: s['name'])[0]
        sec = elf.sections[caller['sec']]
        offset = sec[4] + entry - sec[3]
        raw = elf.data[offset:offset + 5]
        assert raw[0] == 0xe9 and entry + 5 + struct.unpack('<i', raw[1:])[0] == load[0], 'ALT island entry/return pairing'
        plans.append(dict(symbol=caller['name'], aliases=sorted(s['name'] for s in callers),
                          address=branch[0], offset=section[4] + branch[0] - section[3],
                          before=branch[1].hex(), after=(b'\xeb' + branch[1][1:]).hex(),
                          target=retire[0], entry=entry, continuation=continuation,
                          sequence_address=load[0],
                          purpose='PRE: bypass fence store; still retire pending bits',
                          disassembly=found_as_json([(a, raw, asm) for a, raw, asm, _ in rows[i:i + 6]])))
    if source.name == 'tomokv':
        assert len(plans) == 4 and all('drain_local_reads_bounded_impl' in p['symbol'] for p in plans), 'ALT server island inventory'
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
    missing[first['offset']] = bytes.fromhex(first['before'])[0]
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


def prepare_alt(source):
    assert source.resolve().is_relative_to(ROOT / 'build'), 'keep the source overlay in this worktree/build'
    assert not source.exists(), 'refusing to replace an existing source overlay'
    archive = subprocess.check_output(['git', 'archive', FROZEN_POST, 'src', 'third_party',
                                      'Makefile', 'tests/rlfence_unit.cc',
                                      'tests/read_local_write_ring_unit.cc'], cwd=ROOT)
    source.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(source, filter='data')
    patch = ROOT / 'docs/rlfence2/alt.patch'
    subprocess.run(['patch', '--batch', '-p1', '-d', str(source)],
                   input=patch.read_bytes(), check=True)
    save(source / 'source-receipt.json', dict(commit=FROZEN_POST, archive_sha256=sha(archive),
         patch=str(patch.relative_to(ROOT)), patch_sha256=sha(patch.read_bytes()),
         files={p: sha((source / p).read_bytes()) for p in ('Makefile', 'src/net/rob.h', 'src/core/ex_loop.h')}))
    print(f'Prepared {source}; build with taskset -c 112-127 make -j16 -C {source} BUILD_ROOT=ABSOLUTE_OUTPUT all build/rlfence-unit build/read-local-write-ring-unit')


def h05_proof(pre, alt, audit_file, out):
    before, after = Elf(pre), Elf(alt)
    report = json.loads(audit_file.read_text())
    assert report['pre']['binary_sha256'] == sha(before.data)
    assert report['post']['binary_sha256'] == sha(after.data)
    wanted = {
        '_ZN8tomo_db06IoLoop8run_loopILb0ELb0ELb0ELb1ELh0ELb0EEEvv': 0x90,
        '_ZN8tomo_db06IoLoop11flush_readyILb0ELb0ELb1ELb0ELb1ELb0EEEjv': 0x70,
        '_ZN8tomo_db06IoLoop18parse_and_dispatchILb0ELj32ELb0ELb0EEENS0_14DispatchResultEPNS_6ClientE': 0x1b0,
    }
    old, new = before.functions(), after.functions()
    rows = []
    for name, loop in wanted.items():
        a, b = old[name], new[name]
        assert (a['value'], a['size']) == (b['value'], b['size']), ('h05 layout moved', name)
        comparison = [r for r in report['instruction_comparisons']
                      if r['pre_address'] == hex(a['value']) and r['post_address'] == hex(b['value'])]
        assert len(comparison) == 1 and comparison[0]['equal'], ('h05 instructions changed', name)
        assert before.body(a) == after.body(b), ('h05 literal instruction bytes changed', name)
        rows.append(dict(symbol=name, address=hex(a['value']), size=a['size'],
                         loop_head=hex(a['value'] + loop), loop_mod64=(a['value'] + loop) % 64,
                         raw_bytes_equal=before.body(a) == after.body(b),
                         normalized_instructions_equal=True))
    commands = [r for r in report['instruction_comparisons']
                if 'tomo_db0::' in r['name'] and '::cmd_get<' in r['name']]
    assert commands and all(r['equal'] and r['pre_address'] == r['post_address'] for r in commands)
    # GCC folds <false,false> into the exported cmd_get_tls body. The other
    # three template bodies retain their anonymous-namespace names.
    clean = [s for n, s in old.items() if n.startswith('_ZN8tomo_db0') and '11cmd_get_tlsE' in n]
    assert len(clean) == 1, 'clean GET handler inventory'
    a = clean[0]; b = new[a['name']]
    assert (a['value'], a['size']) == (b['value'], b['size']) and before.body(a) == after.body(b), 'clean GET handler changed'
    commands.append(dict(symbol=a['name'], address=hex(a['value']), size=a['size'], raw_bytes_equal=True))
    save(out, dict(scope='Default database, TCP/uring, no TLS/Unix, fused FIFO h05 loop/flush/GET parser and GET handlers',
         pre_sha256=sha(before.data), alt_sha256=sha(after.data), hot_functions=rows,
         get_handler_comparisons=commands, whole_binary_layout_equal=False,
         caveat='External call displacements are resolved by target identity. Other TLS/epoll/R7 bodies can differ; see full audit.'))
    print('PASS h05: exact PRE function addresses/sizes/loop heads and normalized instructions; GET handlers retained')


def closure(source, out, source_ref=FROZEN_POST):
    """Prove both source completion sites call each physical patched helper.

    A retained out-of-line helper alone would not rule out a second, inlined
    copy of the fence clear. Account for all two sites times four instantiations.
    """
    source_commit = subprocess.check_output(['git', 'rev-parse', source_ref], text=True, cwd=ROOT).strip()
    source_text = subprocess.check_output(['git', 'show', source_commit + ':src/core/ex_loop.h'], text=True, cwd=ROOT)
    assert len(re.findall(r'^\s*complete_local_prefix\(', source_text, re.M)) == 2
    uses = subprocess.check_output(['git', 'grep', '-n', 'complete_pending_read_local_mask',
                                   source_commit, '--', 'src'], text=True, cwd=ROOT).splitlines()
    assert len(uses) == 2 and sum('src/core/ex_loop.h:' in s for s in uses) == 1
    elf = Elf(source); funcs = elf.functions()
    pattern = re.compile(r'_ZN(4tomo|8tomo_db0)7ExLoopTILb1EE30drain_local_reads_bounded_implILb([01])EEEjj')
    parents = {n for n in funcs if pattern.fullmatch(n)}
    assert len(parents) == 4
    rows = []
    for parent in sorted(parents):
        ns, fair = pattern.fullmatch(parent).groups()
        helper = f'_ZZN{ns}7ExLoopTILb1EE30drain_local_reads_bounded_implILb{fair}EEEjjENKUljE2_clEj'
        calls = [a for a, raw, _, _ in instructions(disassemble(source, parent))
                 if len(raw) == 5 and raw[0] == 0xe8 and
                 a + 5 + struct.unpack('<i', raw[1:])[0] == funcs[helper]['value']]
        assert len(calls) == 2, ('completion site not covered by patched helper', parent, calls)
        rows.append(dict(parent=parent, helper=helper, address=funcs[helper]['value'], calls=calls))
    save(out, dict(binary_sha256=sha(elf.data), source_commit=source_commit,
         ex_loop_sha256=sha(source_text.encode()), source_mask_uses=uses,
         source_completion_calls=2, physical_helpers=4, covered_calls=8, rows=rows))
    print('PASS closure: both completion sites x four instantiations call the patched helpers')


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
    s = sub.add_parser('identity')
    s.add_argument('reference', type=Path); s.add_argument('candidate', type=Path); s.add_argument('out', type=Path)
    s = sub.add_parser('prepare-alt')
    s.add_argument('source', type=Path)
    s = sub.add_parser('h05-proof')
    s.add_argument('pre', type=Path); s.add_argument('alt', type=Path)
    s.add_argument('audit', type=Path); s.add_argument('out', type=Path)
    s = sub.add_parser('closure')
    s.add_argument('source', type=Path); s.add_argument('out', type=Path)
    s.add_argument('--source-ref', default=FROZEN_POST)
    args = p.parse_args()
    if args.action == 'pad':
        pad(args.source,args.output)
    elif args.action == 'verify':
        verify(args.source,args.output,json.loads(args.plan.read_text()))
    elif args.action == 'audit':
        audit(args.pre,args.post,args.out)
    elif args.action == 'identity':
        identity(args.reference,args.candidate,args.out)
    elif args.action == 'prepare-alt':
        prepare_alt(args.source)
    elif args.action == 'h05-proof':
        h05_proof(args.pre,args.alt,args.audit,args.out)
    else:
        closure(args.source,args.out,args.source_ref)
