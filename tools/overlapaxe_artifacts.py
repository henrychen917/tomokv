#!/usr/bin/env python3
"""Overlap retirement receipts; only the explicit smoke action starts servers.

The PAD-A construction follows deadfused_artifacts.py: restore PRE's cold INFO
rows at POST's exact function/section layout. The null recipes exercise only
PRE overlap=0, whose data-plane behavior is already retained in POST. This is
an observable-default behavior twin, not an independent instruction treatment.
"""
import argparse
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

from lbstall_artifacts import Elf, HOT
from rlfence_artifacts import disassemble, instructions, moved_symbol, save, tables

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'build/overlapaxe'
DOCS = ROOT / 'docs/overlapaxe'
PRE = '6b50f447fcc5be467e9314d7c602b688755957b9'
INFO_ROWS = b'overlap:0\r\noverlap_enabled:0\r\n'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pad_plan(path):
    elf = Elf(path)
    raw = elf.data
    ro_index = elf.names.index('.rodata')
    ro = elf.sections[ro_index]
    data = elf.section_data(ro_index)
    marker = b'thread_mode:%s\r\nshards:%u\r\n'
    assert data.count(marker) == 1, 'unique INFO server format'
    at = data.index(marker)
    begin, end = data.rfind(b'\0', 0, at) + 1, data.index(b'\0', at) + 1
    old = data[begin:end]
    assert INFO_ROWS not in old and b'reorder:%d\r\n' in old
    new = old.replace(marker, marker + INFO_ROWS)
    address = ro[3] + begin
    phoff = struct.unpack_from('<Q', raw, 32)[0]
    phsize, phcount = struct.unpack_from('<HH', raw, 54)
    assert phsize == 56
    headers = [(phoff + i * phsize, struct.unpack_from('<IIQQQQQQ', raw, phoff + i * phsize))
               for i in range(phcount)]
    notes = [(at, h) for at, h in headers if h[0] == 4]
    assert notes, 'PT_NOTE slot for appended read-only INFO format'
    align = lambda n: (n + 4095) & -4096
    offset = align(len(raw))
    target = align(max(h[3] + h[6] for _, h in headers if h[0] == 1))
    header = struct.pack('<IIQQQQQQ', 1, 4, offset, target, target, len(new), len(new), 4096)
    edits = [dict(kind='read-only PT_LOAD', offset=notes[-1][0],
                  old=raw[notes[-1][0]:notes[-1][0] + phsize].hex(), new=header.hex())]
    callers = []
    for fn in elf.functions().values():
        if '8cmd_infoE' not in fn['name']:
            continue
        for ip, body, asm, _ in instructions(disassemble(path, fn['name'])):
            rip = re.fullmatch(r'lea\s+[^,]*\(%rip\),%r[a-z0-9]+\s+#\s+([0-9a-f]+) <.*>', asm)
            immediate = re.fullmatch(r'mov\s+\$0x([0-9a-f]+),%e[a-z0-9]+', asm)
            if rip and int(rip[1], 16) == address:
                assert len(body) == 7 and body[1] == 0x8d
                replacement = body[:3] + struct.pack('<i', target - ip - len(body))
            elif immediate and int(immediate[1], 16) == address:
                assert len(body) == 5 and 0xb8 <= body[0] <= 0xbf and target < 2**31
                replacement = body[:1] + struct.pack('<I', target)
            else:
                continue
            sec = elf.sections[fn['sec']]
            edits.append(dict(kind='INFO format reference', offset=sec[4] + ip - sec[3],
                              symbol=fn['name'], old=body.hex(), new=replacement.hex()))
            callers.append(fn['name'])
    assert len(callers) == len(set(callers)) == 2, ('both namespaces', callers)
    return dict(kind='A: PRE overlap=0 observable data-plane behavior at POST layout',
                source_sha256=digest(raw), patches=edits, appended_offset=offset,
                appended_address=target, appended_hex=new.hex(), callers=callers)


def verify_pad(source, output, plan):
    assert plan == pad_plan(source), 'independent patch inventory'
    a, b = Elf(source), Elf(output)
    assert a.sections == b.sections, 'section table moved'
    assert a.symbols == b.symbols, 'symbol table moved'
    raw = bytearray(b.data)
    at = plan['appended_offset']
    assert raw[at:] == bytes.fromhex(plan['appended_hex']), 'PRE INFO rows missing'
    assert raw[len(a.data):at] == bytes(at - len(a.data)), 'unplanned tail'
    del raw[len(a.data):]
    for change in plan['patches']:
        old, new = bytes.fromhex(change['old']), bytes.fromhex(change['new'])
        at = change['offset']
        assert raw[at:at + len(new)] == new, 'planned retarget missing'
        raw[at:at + len(new)] = old
    assert bytes(raw) == a.data, 'unplanned byte change'


def pad():
    source, output = BASE / 'POST/tomokv', BASE / 'PAD-A/tomokv'
    plan = pad_plan(source)
    a = Elf(source)
    data = bytearray(a.data)
    data += bytes(plan['appended_offset'] - len(data)) + bytes.fromhex(plan['appended_hex'])
    for change in plan['patches']:
        at = change['offset']
        data[at:at + len(bytes.fromhex(change['new']))] = bytes.fromhex(change['new'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    output.chmod(source.stat().st_mode)
    verify_pad(source, output, plan)
    first = plan['patches'][1]
    missing = bytearray(data)
    at = first['offset']
    missing[at:at + len(bytes.fromhex(first['old']))] = bytes.fromhex(first['old'])
    bad = bytearray(data)
    bad[a.sections[a.names.index('.text')][4]] ^= 1
    controls = {}
    for name, raw, expected in (
            ('missing-retarget', missing, 'planned retarget missing'),
            ('moved-symbol', moved_symbol(data, a, first['symbol']), 'symbol table moved'),
            ('one-byte', bad, 'unplanned byte change')):
        path = output.with_name('negative-' + name + '.DO-NOT-RUN')
        path.write_bytes(raw)
        try:
            verify_pad(source, path, plan)
        except AssertionError as error:
            assert str(error) == expected, (name, str(error))
            controls[name] = dict(rejected=True, reason=str(error))
        else:
            raise AssertionError('negative control escaped: ' + name)
        finally:
            path.unlink()
    out = BASE / 'pad-proof'
    before, after = tables(a, out, 'POST'), tables(Elf(output), out, 'PAD-A')
    assert before['function_table_sha256'] == after['function_table_sha256']
    assert before['section_table_sha256'] == after['section_table_sha256']
    save(DOCS / 'pad-proof.json', dict(kind=plan['kind'], post=before, pad=after,
         patches=plan['patches'], restored_info_rows=INFO_ROWS.decode(), controls=controls,
         exact_function_and_section_tables=True, all_other_original_bytes_identical=True,
         limitation='Default-only null control. The two retired INFO rows are restored, but the '
         'retired CLI/CONFIG surface and overlap=1 are intentionally not restored. POST already '
         'retains PRE overlap=0 data-plane behavior. There is no independent data-path treatment; '
         'POST/PAD cannot attribute compiler-codegen versus address-layout effects. A non-null '
         'result requires investigation; this control cannot justify a speedup claim.'))
    save(out / 'plan.json', plan)
    print('PASS PAD-A exact tables and all other bytes; both namespaces; 3 negative controls')


def layout():
    script = BASE / 'layout.gdb'
    script.write_text('''set pagination off
python
import gdb,json
expected=dict(Op=336,Client=1984,ThreadCtx=1408,Shard=1440,FlatStore=944,AtomicEntry=144,Config=624)
expected['Rob<64>']=192
rows={}
for ns in ('tomo','tomo_db0'):
    sizes={name:int(gdb.lookup_type(ns+'::'+name).sizeof) for name in expected}
    assert sizes==expected,(ns,sizes)
    fields={}
    for name in ('Op','Client','ThreadCtx','Shard','FlatStore','AtomicEntry','Config','IoLoop','ModeScheduleStats'):
        t=gdb.lookup_type(ns+'::'+name)
        fields[name]={'size':int(t.sizeof),'fields':{f.name:[int(f.bitpos)//8,int(f.type.sizeof)] for f in t.fields() if hasattr(f,'bitpos')}}
    rows[ns]={'sizes':sizes,'layouts':fields}
print('LAYOUT='+json.dumps(rows))
end
''')
    rows = {}
    for arm in ('PRE', 'POST'):
        result = subprocess.check_output(['gdb', '-nx', '-q', '-batch', str(BASE / arm / 'tomokv'),
                                          '-x', str(script)], text=True)
        rows[arm] = json.loads(next(line[7:] for line in result.splitlines() if line.startswith('LAYOUT=')))
    changed = []
    for ns in rows['PRE']:
        for name, before in rows['PRE'][ns]['layouts'].items():
            after = rows['POST'][ns]['layouts'][name]
            assert before['size'] == after['size'], (ns, name)
            for field, value in before['fields'].items():
                if name == 'Config' and field == 'overlap':
                    assert after['fields']['network_reserved'] == value
                elif name == 'ModeScheduleStats' and field.startswith('overlap_'):
                    changed.append(dict(namespace=ns, type=name, field=field, old=value, replacement='reserved storage'))
                else:
                    assert after['fields'][field] == value, (ns, name, field)
    save(DOCS / 'layout.json', dict(arms=rows, retired_fields=changed,
         all_eight_size_locks=True, all_surviving_member_offsets_equal=True))
    print('PASS all eight locks and every surviving member offset, both namespaces')


def reason(row):
    name = row['name']
    if 'prefetch_overlap_batch' in name:
        return 'Fused owner prefetch renamed; optional overlap witness removed; no split caller survives.'
    if 'prefetch_owner_batch' in name:
        return 'Preserved fused owner prefetch under its surviving name; test-only witness is absent in production.'
    if not row['post_size'] and any(x in name for x in ('pipeline_pass', 'ifid_', 'IoPipe', 'wb_gather', 'wb_observe', 'wb_prefetch', 'wb_retire', 'wb_submit')):
        return 'Deleted split overlap schedule/helper specialization; fused shared helpers retained where instantiated.'
    if 'parse_config_args' in name or 'validate_config' in name:
        return 'Retired parser/validation branches deleted; ordinary unknown-option fallback now handles overlap.'
    if 'cmd_info(' in name or 'append_mode_schedule_info' in name:
        return 'Retired INFO rows/witnesses removed; reorder reporting retained.'
    if 'cmd_config(' in name or 'init_config(' in name or 'config_' in name:
        return 'Removed CONFIG table entry and shifted cold dispatch/table references.'
    if 'print_boot_presentation' in name:
        return 'Retired overlap banner field removed; fused owner-prefetch description retained.'
    if 'Server::' in name:
        return 'Config reserved slot and reorder-only optional schedule allocation change initialization/validation.'
    if any(x in name for x in ('parse_and_dispatch', 'flush_ready', 'drive_tls', 'on_cqe', 'epoll_', 'run_loop', 'handle_', 'IoLoop::init')):
        return 'Removed Pipeline/IoPipe template arguments and overlap-only branches; default/fused specializations re-emitted. Codegen/target differences are recorded, not treated as byte identity.'
    if 'ExLoopT<' in name or 'fused_pass' in name or 'genthread_' in name:
        return 'Removed split owner-prefetch eligibility/witness plumbing or changed renamed/template call targets in the surrounding fused/executor body. Default behavior retained; byte identity not inferred.'
    if name.startswith(('void ', 'bool ', 'unsigned ', 'tomo::', 'tomo_db0::')) and 'IoLoop::' in name:
        return 'Surviving IO dispatch re-emitted after removal of split overlap selector/templates; codegen and named relocation differences retained.'
    if row['object'].endswith('version.o'):
        return 'Build/source identity metadata differs between frozen PRE and POST.'
    if not row['post_size']:
        return 'Helper emission disappears from this object after removal of the overlap instantiation graph. This records object-local emission, not deletion of its shared source implementation.'
    if not row['pre_size']:
        return 'New out-of-line helper emission from the reduced instantiation graph; shared source implementation was not added by this lane.'
    return 'Compiler emission/relocation consequence in a translation unit whose included Config/IO/executor code changed; no direct source edit to this body. This is an unresolved byte-level difference, not a claimed performance-neutral change.'


def explain():
    source = BASE / 'body-audit'
    with gzip.open(source / 'bodies.json.gz', 'rt') as stream:
        rows = json.load(stream)
    changed = [dict(row, reason=reason(row)) for row in rows if not row['equal']]
    save(DOCS / 'changed-bodies.json', changed)
    (DOCS / 'bodies.json.gz').write_bytes((source / 'bodies.json.gz').read_bytes())
    summary = json.loads((source / 'summary.json').read_text())
    summary = {key: value for key, value in summary.items() if not isinstance(value, list)}
    summary['changed_by_object'] = dict(sorted(collections.Counter(r['object'] for r in changed).items()))
    summary['changed_hot_inventory'] = [dict(row, reason=reason(row)) for row in changed
                                        if HOT.search(row['name']) or re.search(r'ExLoopT<.*>::run\(', row['name'])]
    summary['interpretation'] = 'Existing ccfix_audit normalization retains opcode/member-offset/callee identity. Symbol renames and template removals are deliberately reported. Hot-body identity fails, so PAD-A and mainline null are mandatory. Raw equality is separately recorded for every body.'
    save(DOCS / 'body-summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, (dict, list))}))


def campaign():
    snapshot = BASE / 'campaign-proof'
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', PRE, 'tests', 'tools'],
                                    cwd=ROOT, text=True).splitlines()
    rows = []
    for name in paths:
        frozen = subprocess.check_output(['git', 'show', PRE + ':' + name], cwd=ROOT)
        actual = (snapshot / name).read_bytes()
        assert frozen == actual, 'campaign input changed: ' + name
        rows.append(dict(path=name, sha256=digest(actual)))
    for name in ('tools/mkprobe_probe.py', 'tests/mkprobe_cells.txt'):
        assert (ROOT / name).read_bytes() == (snapshot / name).read_bytes(), name
    binary = Path('/home/user/Projects/cx-final/build/mkprobe-mainline/server/tomokv')
    save(DOCS / 'campaign-proof.json', dict(base=PRE, frozen_root=str(snapshot),
         binary=str(binary), binary_sha256=digest(binary.read_bytes()), files=rows,
         native_root_compatible=False,
         reason='The protected tool pins PRE headline recipe bytes and fingerprints imported instruments. Run from the frozen input snapshot for the existing campaign/null. Active POST recipes deliberately differ.'))
    print('PASS protected tool/recipe unchanged;', len(rows), 'frozen campaign inputs byte-identical to PRE')


def units():
    commands = [['build/config-parser-test'], ['build/owner-prefetch-unit'],
                ['python3', 'tests/splitlocal_checks.py', 'check', '--output',
                 'build/overlapaxe/splitlocal-controls']]
    for binary in ('build/netcmd-unit', 'build/netcmd-unit-db0'):
        for case in ('config-knobs', 'config-bounds'):
            commands.append([binary, case])
    # The broad multi-DB config fixture also covers tracking SWAPDB; keep it intact.
    commands.append(['build/netcmd-unit', 'config'])
    for binary in ('build/reorder-engagement-unit', 'build/reorder-engagement-unit-db0'):
        commands.append([binary, 'on', 'shadow'])
    for binary in ('build/r7shadow-split-unit', 'build/r7shadow-split-unit-db0'):
        commands.append([binary, 'positive'])
        for requested in (0, 1):
            for local in (0, 1):
                commands.append([binary, str(requested), str(local)])
    for binary in ('build/wb-rule-phase-unit', 'build/wb-rule-db0-phase-unit'):
        for case in ('wbland-fused', 'wbland-split', 'wbland-local', 'fused-budget',
                     'split-budget', 'split-policy', 'split-fastpath', 'split-fifo',
                     'split-capture', 'split-progress', 'split-chunk', 'split-aof',
                     'split-capture-multi', 'split-local', 'split-local-sweep',
                     'fused-parse', 'split-parse', 'split-ex', 'split-ex-unmasked', 'split-ex-timed'):
            commands.append([binary, case])
    for binary in ('build/wb-rule-completion-unit', 'build/wb-rule-db0-completion-unit'):
        for case in ('table', 'knobs', 'exits', 'lifetime', 'knob-lifetime'):
            commands.append([binary, case])
    results = []
    for command in commands:
        print('COMMAND', command, flush=True)
        result = subprocess.run(command, cwd=ROOT, timeout=60)
        results.append(dict(command=command, returncode=result.returncode))
        save(DOCS / 'unit-proofs.json', results)
        assert result.returncode == 0, command
    print('PASS', len(results), 'serverless unit invocations')


def smoke():
    """Owner task step 6: sequential short boots, no benchmark or gate invocation."""
    sys.path.insert(0, str(ROOT / 'tests'))
    from _gate_process import server, info
    from _lib import RespError
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin driver to 112-127'
    rows = []
    for arm in ('POST', 'PAD-A'):
        binary = BASE / arm / 'tomokv'
        for databases in (1, 16):
            for mode in ('1s', '2s'):
                label = f'{arm}-db{databases}-{mode}'
                flags = ['--databases', databases, '--shards', 16, '--thread-mode', mode,
                         '--read-local', 0, '--reorder', 0, '--atomic', 1, '--net-io', 'uring']
                if mode == '2s':
                    flags += ['--ratio', '6:2']
                for name in ('overlap', 'x-overlap', 'thread-pipeline', 'overlapaxe-unknown'):
                    result = subprocess.run([str(binary), '--databases', str(databases),
                        '--thread-mode', mode, '--' + name, '0', '--help'],
                        text=True, capture_output=True, timeout=10)
                    assert result.returncode == 1 and result.stderr == \
                        f"unknown argument '--{name}' (see --help)\n", (label, name, result)
                directory = BASE / 'smoke' / label
                with server(binary, '112-119', 18489, directory, flags) as (conn, process):
                    actual = info(conn, 'SERVER')
                    assert actual['process_id'] == str(process.pid)
                    assert actual['thread_mode'] == mode and actual['shards'] == '16'
                    assert actual['read_local'] == actual['reorder'] == '0'
                    for name in ('overlap', 'overlap_enabled'):
                        assert actual.get(name) == ('0' if arm == 'PAD-A' else None)
                    assert conn.must('PING') == b'PONG'
                    assert conn.must('SET', 'overlapaxe:a', 'first') == b'OK'
                    assert conn.must('GET', 'overlapaxe:a') == b'first'
                    assert conn.must('MSET', 'overlapaxe:a', 'second', 'overlapaxe:b', 'third') == b'OK'
                    assert conn.must('MGET', 'overlapaxe:a', 'overlapaxe:b') == [b'second', b'third']
                    for name in ('overlap', 'x-overlap', 'thread-pipeline'):
                        assert conn.must('CONFIG', 'GET', name) == []
                        assert conn.cmd('CONFIG', 'SET', name, '0') == RespError(
                            f"ERR Unknown option or number of arguments for CONFIG SET - '{name}'")
                    save(directory / 'info.json', actual)
                row = dict(arm=arm, databases=databases, mode=mode, server_cpus='112-119',
                           shards=16, ratio='6:2' if mode == '2s' else '8 fused',
                           binary_sha256=digest(binary.read_bytes()),
                           commands=['PING', 'SET', 'GET', 'MSET', 'MGET', 'CONFIG GET/SET'],
                           exit=json.loads((directory / 'exit.json').read_text()))
                assert not row['exit']['forced_kill'] and row['exit']['returncode'] == 0
                rows.append(row)
                save(DOCS / 'smoke.json', rows)
                print('PASS smoke', label, 'owned process reaped; clean shutdown', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('pad', 'layout', 'explain', 'campaign', 'units', 'smoke'))
    globals()[parser.parse_args().action]()
