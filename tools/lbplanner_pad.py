#!/usr/bin/env python3
"""Build an offline PAD-A: PRE LB hosting/gates/search on POST's exact layout.

No ELF is executed here. The only changes are direct-call displacements and
the recorded cached-load instructions. Metadata is emitted in the same COMDAT
group as its gate, so the inventory contains exactly the surviving inline sites.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from lbstall_artifacts import Elf
from rlfence_artifacts import instructions, disassemble, tables, moved_symbol

ROOT = Path(__file__).resolve().parents[1]
BASE = 'cd02ecbab1502775f1c170e806971d1f7bbc3ee9'


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def body(text, name):
    match = re.search(r'\b' + re.escape(name) + r'\([^)]*\)\s*(?:const\s*)?\{', text)
    assert match, ('missing body', name)
    start = match.end() - 1
    depth = 0
    for token in re.finditer(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', text[start:]):
        if token[0] == '{': depth += 1
        elif token[0] == '}': depth -= 1
        if depth == 0:
            return text[start:start + token.end()]
    raise AssertionError(('unclosed body', name))


def normalized(text):
    return re.sub(r'\s+', ' ', text).strip()


def source_proof():
    def pre(path):
        return subprocess.check_output(['git', 'show', BASE + ':' + path], cwd=ROOT, text=True)
    old_server, old_io = pre('src/core/server.h'), pre('src/core/io_loop.h')
    server = (ROOT / 'src/core/server.h').read_text()
    planner = (ROOT / 'src/core/lbplanner.cc').read_text()
    proofs = []
    for name, old, new, old_name in [
        ('lb_controller_tick_pad', old_server, planner, 'lb_controller_tick'),
        ('lb_control_actuate_pad', old_io, planner, 'lb_control_pass'),
        ('lb_cron_writer_pad', old_server, server, 'lb_cron_writer'),
        ('lb_should_pause_pad', old_server, server, 'lb_should_pause'),
        ('lb_client_move_pad', old_server, server, 'lb_client_move'),
    ]:
        a = normalized(body(old, old_name))
        b = normalized(body(new, name).replace('lb_client_move_pad()', 'lb_client_move()'))
        assert a == b, ('PAD PRE body changed', name)
        proofs.append(dict(function=name, sha256=hashlib.sha256(a.encode()).hexdigest()))
    start = old_io.index('                if (__builtin_expect(lb_controller_armed &&')
    end = old_io.index('                did += lb_wake_all_pass();', start)
    cron = old_io[start:end].replace('lb_controller_armed &&', 'lb_controller_armed_ &&')
    cron = cron.replace('lb_controller_beat_ms_', 'lb_pause_id_')
    cron = cron.replace('lb_cron_writer(', 'lb_cron_writer_pad(').replace('lb_controller_tick(', 'lb_controller_tick_pad(')
    wrapper = body(planner, 'lb_control_pass_pad')
    assert normalized(body(planner, 'lb_pass_begin_pad')) == '{}', 'PAD pass start must preserve PRE cron bytes'
    assert normalized(cron) in normalized(wrapper), 'PAD PRE cron changed'
    assert wrapper.index('lb_control_actuate_pad()') < wrapper.index('cached_now_ms_'), 'PAD tail ordering'
    # Every boot used this same monitor body on PRE. Compare the complete block.
    monitor = body(planner, 'monitor_controllers_pad')[1:-1]
    fused_guard = 'if (cfg_.thread_mode == ThreadMode::Fused) return; // PRE fused boots joined workers directly.'
    assert fused_guard in monitor, 'PAD PRE fused monitor bypass missing'
    monitor = monitor.replace(fused_guard, '')
    for path in ('src/main.cc', 'src/core/genthread.cc', 'src/core/rl2s.cc', 'src/core/reorder.cc'):
        old = pre(path)
        if path.endswith(('genthread.cc', 'reorder.cc')):
            assert 'flipctl_tick(' not in old and 'srv.databases().join_workers(srv, pool);' in old
            continue
        start = old.index('if (srv.flipctl_enabled()) {')
        end = old.index('\n    }', start) + len('\n    }')
        block = old[start:end].replace('srv.databases().monitor(srv)', 'databases().monitor(*this)').replace('srv.', '')
        assert normalized(block) == normalized(monitor), ('PAD PRE monitor changed', path)
    return dict(base=BASE, exact_pre_bodies=proofs, cron_and_all_four_monitors_equal=True,
                repeated_move_cap='Frozen PRE loop condition is retained literally, including both atomic reads.')


def plan(source):
    elf = Elf(source)
    functions = elf.functions()
    code = instructions(disassemble(source))
    by_address = {at: (raw, asm, owner) for at, raw, asm, owner in code}
    patches = []
    targets = {}
    for name in functions:
        if re.fullmatch(r'_ZN(4tomo|8tomo_db0)6IoLoop13lb_pass_beginEv', name):
            targets[name] = (name.replace('13lb_pass_begin', '17lb_pass_begin_pad'), 'io-begin')
        elif re.fullmatch(r'_ZN(4tomo|8tomo_db0)6IoLoop15lb_control_passEv', name):
            targets[name] = (name.replace('15lb_control_pass', '19lb_control_pass_pad'), 'io-tail')
        elif re.fullmatch(r'_ZN(4tomo|8tomo_db0)6Server19monitor_controllersEv', name):
            targets[name] = (name.replace('19monitor_controllers', '23monitor_controllers_pad'), 'monitor')
    assert len(targets) in (3, 6), ('PAD complete namespace targets', targets)
    assert all(new in functions for new, _ in targets.values()), 'PAD retained PRE entry missing'

    def offset(address, length):
        matches = [s for s in elf.sections if s[2] & 4 and s[3] <= address and address + length <= s[3] + s[5]]
        assert len(matches) == 1, ('PAD executable extent', address)
        return matches[0][4] + address - matches[0][3]

    def record(address, raw, replacement, target, category, owner, asm):
        at = offset(address, len(raw))
        assert elf.data[at:at + len(raw)] == raw and len(raw) == len(replacement)
        patches.append(dict(address=address, offset=at, before=raw.hex(), after=replacement.hex(),
                            target=target, category=category, symbol=owner, disassembly=asm))

    call_counts = Counter()
    for address, raw, asm, owner in code:
        edge = re.fullmatch(r'(call|jmp)\s+([0-9a-f]+) <([^>]+)>', asm)
        if not edge or edge[3] not in targets:
            # The entry addresses must never escape through an indirect function pointer.
            for target in targets:
                assert '<' + target + '>' not in asm, ('PAD unhandled entry reference', asm)
            continue
        old = edge[3]
        new, category = targets[old]
        assert raw[0] in (0xe8, 0xe9) and len(raw) == 5 and int(edge[2], 16) == functions[old]['value']
        target = functions[new]['value']
        record(address, raw, raw[:1] + struct.pack('<i', target - address - 5), target, category, owner, asm)
        call_counts[old] += 1
    assert set(call_counts) == set(targets), ('PAD unused entry or missing calls', dict(call_counts))

    gate_sections = [i for i, name in enumerate(elf.names) if name == '.lbplanner_gates']
    assert gate_sections, 'PAD gate metadata missing'
    gate_owners = Counter()
    for index in gate_sections:
        section = elf.sections[index]
        assert not section[2] & 2, 'PAD metadata must not allocate runtime memory'
        metadata = elf.section_data(index)
        assert len(metadata) % 24 == 0, 'PAD incomplete gate record'
        for begin, end, target in struct.iter_unpack('<QQQ', metadata):
            assert begin in by_address and target in by_address, ('PAD discarded or stale metadata', begin, target)
            raw, asm, owner = by_address[begin]
            assert end == begin + len(raw) and 5 <= len(raw) <= 8, ('PAD cached load extent', begin, raw.hex())
            assert re.fullmatch(r'mov\s+-?0x[0-9a-f]+\(%[a-z0-9]+\),%[a-z0-9]+', asm), ('PAD gate load', asm)
            assert owner and ('parse_and_dispatch' in owner or 'LbPlannerTest' in owner or owner == 'lbplanner_parse_gate'), ('PAD unknown gate owner', owner)
            replacement = b'\xe9' + struct.pack('<i', target - begin - 5) + b'\x90' * (len(raw) - 5)
            record(begin, raw, replacement, target, 'parse-gate', owner, asm)
            gate_owners[owner] += 1
    assert gate_owners, 'PAD no gate sites'
    assert len({p['address'] for p in patches}) == len(patches), 'PAD duplicate retarget'
    # Independently enumerate actual parser and IO-loop definitions. A missing
    # metadata record or inlined tail must fail even if every listed patch works.
    parsers = [s for s in elf.symbols if s['info'] & 15 == 2 and s['size'] and re.match(
        r'_ZN(4tomo|8tomo_db0)6IoLoop(?:18parse_and_dispatch|21r7_parse_and_dispatch)I', s['name'])
        and '.cold' not in s['name']]
    loops = [s for s in elf.symbols if s['info'] & 15 == 2 and s['size'] and re.match(
        r'_ZN(4tomo|8tomo_db0)6IoLoop(?:8run_loop|11r7_run_loop)I', s['name'])
        and '.cold' not in s['name']]
    coverage = {}
    for category, definitions in [('parse-gate', parsers), ('io-begin', loops), ('io-tail', loops)]:
        sites = [p['address'] for p in patches if p['category'] == category]
        for definition in definitions:
            count = sum(definition['value'] <= at < definition['value'] + definition['size'] for at in sites)
            assert count == 1, ('PAD incomplete body coverage', category, definition['name'], count)
        coverage[category] = sorted(s['name'] for s in definitions)
    if source.name == 'tomokv' or source.name.startswith('tomokv-'):
        assert len(targets) == 6 and len(gate_owners) >= 16, 'PAD production namespace/parser breadth'
        for ns in ('4tomo', '8tomo_db0'):
            assert any(ns in owner and 'r7_' in owner for owner in gate_owners), 'PAD missing R7 namespace'
            assert call_counts[f'_ZN{ns}6Server19monitor_controllersEv'] == 4, 'PAD four boot hosts per namespace'
    return dict(kind='A: PRE behaviour with POST text layout', source_sha256=hashlib.sha256(elf.data).hexdigest(),
                source_proof=source_proof(), calls=dict(call_counts), gate_owners=dict(gate_owners),
                exhaustive_body_coverage=coverage,
                patches=sorted(patches, key=lambda p: p['address']))


def verify(source, output, expected, independent=True):
    if independent:
        assert expected == plan(source), 'PAD plan differs from independent inventory'
    before, after = Elf(source), Elf(output)
    assert before.sections == after.sections, 'PAD section table moved'
    assert before.symbols == after.symbols, 'PAD symbol table moved'
    restored = bytearray(after.data)
    for patch in expected['patches']:
        at = patch['offset']
        old, new = bytes.fromhex(patch['before']), bytes.fromhex(patch['after'])
        assert restored[at:at + len(new)] == new, 'PAD planned retarget missing'
        assert patch['address'] + 5 + struct.unpack_from('<i', new, 1)[0] == patch['target'], 'PAD wrong target'
        restored[at:at + len(old)] = old
    assert bytes(restored) == before.data, 'PAD unplanned byte change'


def make_pad(source, output, receipt):
    assert source.resolve() != output.resolve(), 'PAD must be a separate copy'
    receipt.mkdir(parents=True, exist_ok=True)
    expected = plan(source)
    save(receipt / 'planned-retargets.json', expected)
    before = Elf(source)
    changed = bytearray(before.data)
    for patch in expected['patches']:
        at = patch['offset']
        changed[at:at + len(bytes.fromhex(patch['after']))] = bytes.fromhex(patch['after'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(changed)
    output.chmod(0o755)
    verify(source, output, expected)
    a, b = tables(before, receipt, 'POST'), tables(Elf(output), receipt, 'PAD-A')
    assert a['function_table_sha256'] == b['function_table_sha256']
    assert a['section_table_sha256'] == b['section_table_sha256']
    controls = []
    broken_path = output.parent / (output.name + '.NEVER-RUN')
    for category in ('io-begin', 'io-tail', 'monitor', 'parse-gate'):
        first = next(p for p in expected['patches'] if p['category'] == category)
        broken = bytearray(changed)
        at = first['offset']
        old = bytes.fromhex(first['before'])
        broken[at:at + len(old)] = old
        controls.append(('missing-' + category, broken, 'PAD planned retarget missing'))
    first = expected['patches'][0]
    controls.append(('moved-symbol', moved_symbol(changed, before, first['symbol']), 'PAD symbol table moved'))
    broken = bytearray(changed)
    covered = {i for p in expected['patches'] for i in range(p['offset'], p['offset'] + len(bytes.fromhex(p['after'])))}
    at = before.sections[before.names.index('.text')][4]
    while at in covered: at += 1
    broken[at] ^= 1
    controls.append(('unrelated-byte', broken, 'PAD unplanned byte change'))
    outcomes = {}
    for name, broken, message in controls:
        broken_path.write_bytes(broken)
        broken_path.chmod(0o600)
        try:
            verify(source, broken_path, expected, independent=False)
        except AssertionError as error:
            assert str(error) == message, (name, str(error))
            outcomes[name] = dict(rejected=True, assertion=message)
        else:
            raise AssertionError(('PAD accepted negative', name))
    broken_path.unlink()
    save(receipt / 'negative-controls.json', outcomes)
    save(receipt / 'closure-proof.json', expected['source_proof'])
    save(receipt / 'proof.json', dict(kind=expected['kind'], post=a, pad=b,
         exact_function_and_section_tables=True, all_other_bytes_identical=True,
         patches_by_kind=dict(Counter(p['category'] for p in expected['patches'])),
         changed_bytes=sum(x != y for x, y in zip(before.data, changed)), controls=outcomes))
    for path in receipt.glob('*.tsv'):
        with gzip.GzipFile(filename=str(path) + '.gz', mode='wb', mtime=0) as stream:
            stream.write(path.read_bytes())
        path.unlink()
    print('PASS PAD-A: exact function/section tables; PRE source closure;', len(expected['patches']), 'retargets; six negative controls')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('receipt', type=Path)
    args = parser.parse_args()
    make_pad(args.source, args.output, args.receipt)
