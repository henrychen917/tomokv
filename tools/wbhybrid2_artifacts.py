#!/usr/bin/env python3
"""Offline bounded-revisit study. Run under taskset -c 112-127; never boots a server.

The checkout remains REF. All candidate source, objects, and mutation controls
live in build/wbhybrid2. D=0 is the predecessor's exact S=16 source.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess

import wbhybrid_artifacts as old
from lbstall_artifacts import Elf

ROOT, BUILD = old.ROOT, old.BUILD
STUDY = BUILD / 'wbhybrid2'
LAUNCH = '018d23a4cac8f32a4eb56915ca394d80576b5883'
BASE = old.BASE
POLICY, CLIENT = old.POLICY, 'src/net/conn.h'
ARMS = {'hyb16-d0': 0, 'hyb16-d1': 1, 'hyb16-d2': 2}
replace, sha, receipt = old.replace, old.sha, old.receipt
old.STUDY = STUDY


def write_json(name, data):
    (STUDY / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')


def sources(delay):
    rule = old.policy(16)[1]
    client = (ROOT / CLIENT).read_text()
    if not delay:
        return {POLICY: rule, CLIENT: client}
    rule = replace(rule, 'inline constexpr unsigned kSmallPipe = 16;',
        'inline constexpr unsigned kSmallPipe = 16;\n'
        f'inline constexpr unsigned kDeferVisits = {delay};')
    rule = replace(rule, f'    const unsigned threshold = n <= kSmallPipe ? n : {old.HALF};',
        '    // Keep this per-visit predicate off the encoder\'s register set. A live\n'
        '    // register here spills once per integer reply; one stack byte keeps all\n'
        '    // additional work at the visit boundary (locked by code-costs receipts).\n'
        '    const volatile bool complete = n <= kSmallPipe && c.wb_deferrals() < kDeferVisits;\n'
        f'    const unsigned threshold = complete ? n : {old.HALF};')
    rule = replace(rule, '    if (prefix >= threshold) return false;\n    return true;',
        '    if (prefix >= threshold) return false;\n'
        '    // One byte update per deferred visit, never per operation. The predicate\n'
        '    // caps the count at D: a half-rule deferral adds zero, so it cannot wrap.\n'
        '    c.wb_deferrals() += complete;\n'
        '    return true;')
    for name in ('client', 'c'):
        rule = replace(rule, f'            {name}->set_serve_pending(false);',
            f'            {name}->wb_deferrals() = 0; // served or dead: leaving the FIFO\n'
            f'            {name}->set_serve_pending(false);')
    client = replace(client, '    bool serve_pending() const { return serve_pending_; }',
        '    // IO-owned across the pending-serve FIFO lifetime, including tail rotations.\n'
        '    uint8_t& wb_deferrals() { return wb_deferrals_; }\n'
        '    static constexpr size_t wb_deferrals_offset();\n'
        '    static constexpr size_t wb_rob_offset();\n'
        '    bool serve_pending() const { return serve_pending_; }')
    client = replace(client, '    Session   session_;                 // 68..71',
        '    Session   session_;                 // 68..71\n'
        '    uint8_t   wb_deferrals_ = 0;         // 72: existing IO-only padding before ROB')
    client = replace(client, 'constexpr size_t Client::acl_user_idx_offset()',
        'constexpr size_t Client::wb_deferrals_offset() { return offsetof(Client, wb_deferrals_); }\n'
        'constexpr size_t Client::wb_rob_offset() { return offsetof(Client, rob_); }\n'
        'static_assert(Client::wb_deferrals_offset() == 72);\n'
        'static_assert(Client::wb_rob_offset() == 128);\n'
        'static_assert(Client::wb_deferrals_offset() / 64 == 1);\n'
        'constexpr size_t Client::acl_user_idx_offset()')
    return {POLICY: rule, CLIENT: client}


def builds():
    assert not subprocess.check_output(['git', 'diff', BASE, '--', 'src', 'Makefile'], cwd=ROOT)
    compiles, link = old.commands()
    # GCC retains spelling such as src/core/../net/conn.h. Normalize before
    # selecting the closure, otherwise a Client constructor can keep the old type.
    deps = {obj: {os.path.normpath(p.rstrip(':')) for p in
            (ROOT / obj).with_suffix('.d').read_text().replace('\\\n', ' ').split()}
            for obj in compiles}
    rows = []
    for name, delay in ARMS.items():
        source = STUDY / name
        source.mkdir(exist_ok=True)
        for tree in ('src', 'third_party'):
            if not (source / tree).exists():
                shutil.copytree(ROOT / tree, source / tree)
        shutil.copy2(ROOT / 'Makefile', source / 'Makefile')
        patch = ''
        for path, text in sources(delay).items():
            if (source / path).read_text() != text:
                (source / path).write_text(text)
            patch += ''.join(difflib.unified_diff((ROOT / path).read_text().splitlines(True),
                text.splitlines(True), fromfile='a/' + path, tofile='b/' + path))
        (STUDY / (name + '.patch')).write_text(patch)
        # D2 shares D1's Client, so only the rule closure needs rebuilding again.
        donor = STUDY / 'hyb16-d1' if delay == 2 else ROOT
        changed = [POLICY, CLIENT] if delay == 1 else [POLICY]
        affected = [obj for obj in compiles if any(p in deps[obj] for p in changed)]
        reused = [obj for obj in compiles if obj not in affected]
        make = ['.PHONY: all', 'all: build/tomokv',
                'build/tomokv: ' + ' '.join(compiles), '\t' + shlex.join(link)]
        for obj, cmd in compiles.items():
            dest = source / obj
            dest.parent.mkdir(parents=True, exist_ok=True)
            if obj in affected:
                make += [obj + ': ' + ' '.join(changed), '\t' + shlex.join(cmd)]
            else:
                shutil.copy2(donor / obj, dest)
                shutil.copy2((donor / obj).with_suffix('.d'), dest.with_suffix('.d'))
        (source / 'study.mk').write_text('\n'.join(make) + '\n')
        print('Building', name, len(affected), 'objects', flush=True)
        with (STUDY / (name + '-build.log')).open('w') as log:
            subprocess.run(['make', '-j16', '-f', 'study.mk'], cwd=source,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        shutil.copy2(source / 'build/tomokv', BUILD / ('tomokv-' + name))
        rows.append(dict(arm=name, donor=str(donor.relative_to(ROOT)), affected=affected, reused=reused))
        print(receipt(BUILD / ('tomokv-' + name)), flush=True)
    shutil.copy2(BUILD / 'tomokv', BUILD / 'tomokv-wbhybrid2-ref')
    write_json('dependencies', rows)


def pad(binary, target, header):
    # Same selector patch as the predecessor, restricted to the actual outlined
    # defer symbols. This avoids decoding unrelated megabytes of server text.
    elf = Elf(binary)
    line_number = next(i for i, line in enumerate(header.splitlines(), 1)
                       if 'bool complete = n <= kSmallPipe' in line)
    symbols = [s for n, s in elf.functions().items() if '7wb_rule5defer' in n]
    assert symbols, binary
    sites = []
    for symbol in symbols:
        source_line, pending = None, None
        disasm = subprocess.check_output(['objdump', '-dwl',
            f'--start-address={symbol["value"]}',
            f'--stop-address={symbol["value"] + symbol["size"]}', str(binary)], text=True)
        for line in disasm.splitlines():
            match = re.search(r'([^\s]+\.(?:h|cc)):(\d+)', line)
            if match: source_line = (match[1], int(match[2]))
            insn = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
            if not insn: continue
            address, raw, asm = int(insn[1], 16), bytes.fromhex(insn[2]), insn[3]
            if pending is not None:
                assert re.match(r'(jbe|ja|cmovbe|cmova)\s', asm), asm
                pending['select'] = asm; sites.append(pending); pending = None
            if source_line and source_line[0].endswith('/' + POLICY) and source_line[1] == line_number:
                if re.match(r'cmp\s+\$0x10,%[a-z0-9]+$', asm):
                    opcode = raw[1:] if 0x40 <= raw[0] <= 0x4f else raw
                    assert len(opcode) == 3 and opcode[0] == 0x83 and opcode[1] & 0xf8 == 0xf8
                    sec = elf.sections[symbol['sec']]
                    offset = sec[4] + address - sec[3] + len(raw) - 1
                    pending = dict(address=address, offset=offset, instruction=asm,
                                   source=source_line, symbol=symbol['name'])
        assert pending is None
    assert len(sites) == len(symbols), (binary, sites, symbols)
    data = bytearray(elf.data)
    for site in sites:
        assert data[site['offset']] == 16
        data[site['offset']] = 1
    target.write_bytes(data); target.chmod(binary.stat().st_mode)
    changed = [i for i, (a, b) in enumerate(zip(elf.data, data)) if a != b]
    assert changed == sorted(s['offset'] for s in sites)
    return dict(kind='A: half-rule behaviour, exact candidate ELF layout and instruction shape',
                candidate=receipt(binary), pad=receipt(target), sites=sites,
                differing_bytes=len(changed), scope='Every other ELF byte identical; retained build ID, use SHA-256')


def pads():
    rows = []
    for name in ('hyb16-d1', 'hyb16-d2'):
        rows.append(pad(BUILD / ('tomokv-' + name), BUILD / ('tomokv-' + name + '-pad'),
                        (STUDY / name / POLICY).read_text()))
    write_json('pads', rows)
    write_json('binaries', [receipt(BUILD / 'tomokv-wbhybrid2-ref'),
        receipt(BUILD / 'tomokv-hyb16-d0')] + [item for row in rows for item in (row['candidate'], row['pad'])])


def compile_unit(source, output, delay, db0=False, small=16, has_counter=None):
    flags = old.FLAGS + (['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else [])
    flags += [f'-DWBHYBRID2_DELAY={delay}', f'-DWBHYBRID2_SMALL={small}',
              f'-DWBHYBRID2_COUNTER={int(delay > 0 if has_counter is None else has_counter)}']
    subprocess.run(flags + ['-I' + str(source), '-I' + str(ROOT),
        str(ROOT / 'tests/wbhybrid2_unit.cc'), '-o', str(output), '-ljemalloc'], check=True)


def run(binary, case, failure=None, **kw):
    return old.run_case(binary, case, failure, marker='wbhybrid2', **kw)


def proofs():
    rows, pad_rows = [], []
    for name, delay in {'ref': 0, **ARMS}.items():
        source = ROOT if name == 'ref' else STUDY / name
        for db0 in (False, True):
            binary = STUDY / (name + ('-db0' if db0 else '') + '-unit')
            compile_unit(source, binary, delay, db0, small=0 if name == 'ref' else 16)
            for case in ('table', 'exits', 'lifetime', 'lifetime-serve'):
                rows.append(run(binary, case))
            if delay:
                raw = binary.with_name(binary.name + '-pad-raw')
                twin = binary.with_name(binary.name + '-pad')
                compile_unit(source, raw, delay, db0, small=0)
                pad_rows.append(pad(raw, twin, (source / POLICY).read_text()))
                for case in ('table', 'exits', 'lifetime', 'lifetime-serve'):
                    rows.append(run(twin, case))
                for mutation, case, failure in (
                    ('early', 'table', 'bounded decision table'),
                    ('late', 'table', 'bounded decision table'),
                    ('no-reset', 'lifetime', 'served connection completes again next pipe')):
                    control = STUDY / (name + '-' + mutation)
                    shutil.copytree(source / 'src', control / 'src', dirs_exist_ok=True)
                    text = (control / POLICY).read_text()
                    if mutation == 'no-reset':
                        text = text.replace('->wb_deferrals() = 0;', '->wb_deferrals() += 0;')
                    else:
                        text = replace(text, f'kDeferVisits = {delay};',
                                       f'kDeferVisits = {delay + (1 if mutation == "late" else -1)};')
                    (control / POLICY).write_text(text)
                    mutant = binary.with_name(binary.name + '-' + mutation)
                    compile_unit(control, mutant, delay, db0)
                    rows.append(run(mutant, case, failure))
                    if mutation == 'no-reset': rows.append(run(mutant, 'lifetime-serve', failure))
        print('PASS table/exits/lifetime and controls:', name, flush=True)
    write_json('proofs', rows)
    write_json('pad-unit-sites', pad_rows)


def paths():
    _, link = old.commands()
    objects = [arg for arg in link if arg.endswith('.o') and not arg.endswith('/main.o')]
    libraries = link[link.index('-o') + 2:]
    original = (ROOT / 'tests/wb_rule_phase_unit.cc').read_text()
    begin = original.index('    template <bool Fused, bool Local = false> static void wbland_policies')
    end = original.index('    static int run(', begin)
    fixture = original[:begin] + '#include "tests/wbhybrid2_paths.inc"\n' + original[end:]
    fixture = replace(fixture, 'config.wb_policy = policy;',
                      'config.wb_policy = policy;\n            config.databases = kSingleDatabase ? 1 : 4;')
    fixture_path = STUDY / 'phase.cc'
    fixture_path.write_text(fixture)
    make, jobs = ['.PHONY: all', 'all:'], []
    for name, delay in ARMS.items():
        source = STUDY / name
        for db0 in (False, True):
            flags = old.FLAGS + (['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else [])
            deps = [str(source / p) for p in objects if db0 or not p.startswith('build/db0/')]
            for twin in (False, True) if delay else (False,):
                binary = STUDY / (name + ('-db0' if db0 else '') + ('-pad' if twin else '') + '-phase')
                output = binary.with_suffix('.raw') if twin else binary
                cmd = flags + [f'-DWBHYBRID2_DELAY={delay}', f'-DWBHYBRID2_SMALL={0 if twin else 16}',
                    '-I' + str(source), '-I' + str(ROOT), str(fixture_path), *deps,
                    '-o', str(output), *libraries,
                    '-Wl,--wrap=io_uring_submit', '-Wl,--wrap=io_uring_submit_and_get_events']
                make += [f'all: {output}', f'{output}: {fixture_path} ' + ' '.join(deps),
                         '\t' + shlex.join(cmd)]
                jobs.append((source, output, binary, twin))
    makefile = STUDY / 'paths.mk'
    makefile.write_text('\n'.join(make) + '\n')
    with (STUDY / 'paths-build.log').open('w') as log:
        subprocess.run(['make', '-j16', '-f', str(makefile)], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    rows, pad_rows = [], []
    for source, output, binary, twin in jobs:
        if twin:
            pad_rows.append(pad(output, binary, (source / POLICY).read_text()))
        for args in ((), ('r7',)):
            rows.append(old.run_case(binary, 'wbland-fused', args=args, marker='wb-rule'))
        for args in ((), ('natural',), ('shallow',)):
            for case in ('wbland-split', 'wbland-local'):
                rows.append(old.run_case(binary, case, args=args, marker='wb-rule'))
        print('PASS repeated physical schedules:', binary.name, flush=True)
    write_json('paths', rows)
    write_json('pad-path-sites', pad_rows)


def costs():
    tracer = STUDY / 'instruction-trace'
    subprocess.run(old.FLAGS + [str(ROOT / 'tools/wb_rule_2s_trace.cc'), '-o', str(tracer)], check=True)
    fixtures = [(1, 0, 0, 1, 0), (64, 1, 0, 0, 0), (64, 0, 512, 1, 0)]
    fixtures += [(n, done, 0, 1, 0) for n in (4, 8, 16, 17, 32, 64) for done in (0, 1, n//2, n)]
    fixtures += [(8, 1, 0, 1, 1)]
    rows = []
    for name in ('ref', *ARMS):
        for db0 in (False, True):
            binary = STUDY / (name + ('-db0' if db0 else '') + '-unit')
            elf = Elf(binary)
            symbol = elf.functions()['wbhybrid2_defer']
            sec = elf.sections[elf.names.index('.text')]
            for fixture in fixtures:
                for waits in range(4):
                    case = 'trace-' + '-'.join(map(str, (*fixture, waits)))
                    result = subprocess.run([str(tracer), str(binary), case, f'{symbol["value"]:x}',
                        f'{sec[3]:x}', f'{sec[5]:x}', str(int(elf.kind == 3))],
                        text=True, capture_output=True, timeout=60)
                    assert result.returncode == 0 and f'PASS wbhybrid2 {case}' in result.stdout, result.stdout + result.stderr
                    count = json.loads(next(line[6:] for line in result.stdout.splitlines() if line.startswith('TRACE=')))
                    rows.append(dict(arm=name, db0=db0, case=case, **count, binary_sha256=sha(binary)))
            print('PASS instruction receipts:', binary.name, flush=True)
    write_json('costs', dict(scope='Single defer invocation; ptrace instruction count, no clocks, PMU or load',
                            tracer_sha256=sha(tracer), rows=rows))


def identity():
    deps = json.loads((STUDY / 'dependencies.json').read_text())
    rows = []
    for record in deps:
        name = record['arm']; source = STUDY / name
        changed = [str(p.relative_to(ROOT)) for tree in ('src', 'third_party')
                   for p in (ROOT / tree).rglob('*') if p.is_file() and
                   p.read_bytes() != (source / p.relative_to(ROOT)).read_bytes()]
        assert sorted(changed) == sorted([POLICY, CLIENT] if ARMS[name] else [POLICY]), changed
        assert (ROOT / 'Makefile').read_bytes() == (source / 'Makefile').read_bytes()
        for obj in record['reused']:
            assert sha(ROOT / record['donor'] / obj) == sha(source / obj), (name, obj)
        for obj in record['affected']:
            assert (ROOT / obj).with_suffix('.d').read_text() == (source / obj).with_suffix('.d').read_text()
        rows.append(dict(arm=name, changed_sources=changed, donor=record['donor'],
                         reused_objects=len(record['reused']), affected_objects=len(record['affected'])))
    predecessor = Path('/home/user/Projects/cx-wbhybrid/build/tomokv-hyb16')
    a, b = Elf(predecessor), Elf(BUILD / 'tomokv-hyb16-d0')
    before, after = (e.section_data(e.names.index('.text')) for e in (a, b))
    assert before == after, 'D0 must retain predecessor .text exactly'
    write_json('identity', dict(source=rows, predecessor=receipt(predecessor) if predecessor.is_relative_to(ROOT)
        else dict(path=str(predecessor), sha256=sha(predecessor)), d0=receipt(BUILD / 'tomokv-hyb16-d0'),
        predecessor_text_identical=True, text_bytes=len(before),
        launch_runtime_source_identical=not subprocess.check_output(['git', 'diff', LAUNCH, '--', 'src', 'Makefile'], cwd=ROOT)))
    print('PASS source scope, immutable objects, and predecessor D0 .text identity', flush=True)


def layout():
    rows = []
    for name in ('ref', 'hyb16-d1', 'hyb16-d2'):
        binary = BUILD / ('tomokv' if name == 'ref' else 'tomokv-' + name)
        for ns in ('tomo', 'tomo_db0'):
            text = subprocess.check_output(['gdb', '-nx', '-batch', str(binary),
                '-ex', f'ptype /o {ns}::Client'], text=True, stderr=subprocess.STDOUT)
            (STUDY / f'{name}-{ns}-layout.txt').write_text(text)
            probe = (f"python import gdb,json; t=gdb.lookup_type('{ns}::Client'); "
                "print('LAYOUT='+json.dumps({'bytes':t.sizeof, 'fields':{f.name:"
                "[f.bitpos//8,f.type.sizeof] for f in t.fields() if hasattr(f,'bitpos')}}))")
            raw = subprocess.check_output(['gdb', '-nx', '-batch', str(binary), '-ex', probe], text=True)
            data = json.loads(next(line[7:] for line in raw.splitlines() if line.startswith('LAYOUT=')))
            assert data['bytes'] == 1984 and 'rob_' in data['fields'] and 'tls_slot_' in data['fields']
            rows.append(dict(arm=name, namespace=ns, **data))
    ref = rows[0]['fields']
    for row in rows:
        assert {k: v for k, v in row['fields'].items() if k != 'wb_deferrals_'} == ref
        if row['arm'] != 'ref': assert row['fields']['wb_deferrals_'] == [72, 1]
    write_json('layout', rows)
    print('PASS every Client member offset/width; counter consumes byte 72 padding in both namespaces', flush=True)


def code_identity():
    """Audit all emitted bodies, not just handpicked hot symbols."""
    class AuditElf(Elf):
        def canonical(self, symbol):
            # The inherited hot-symbol audit never encountered R_X86_64_TPOFF32
            # (23). The complete audit includes cold TLS users as well.
            saved = self.relocs.get(symbol['sec'], [])
            tls = [r for r in saved if r[1] == 23]
            self.relocs[symbol['sec']] = [r for r in saved if r[1] != 23]
            try:
                body, targets = super().canonical(symbol)
            finally:
                self.relocs[symbol['sec']] = saved
            body = bytearray(body)
            for offset, kind, target, addend in tls:
                at = offset - symbol['value']
                if 0 <= at < len(body):
                    body[at:at+4] = bytes(4)
                    targets.append((at, kind, self.target(target, addend, kind)))
            return bytes(body), sorted(targets, key=lambda r: r[0])
    compiles, _ = old.commands()
    rows = []
    for name in ARMS:
        changed, total, missing = [], 0, []
        for obj in compiles:
            pre, post = ROOT / obj, STUDY / name / obj
            if sha(pre) == sha(post):
                continue  # separately sealed whole objects
            a, b = AuditElf(pre), AuditElf(post)
            af, bf = a.functions(), b.functions()
            for symbol in sorted(af.keys() | bf.keys()):
                total += 1
                if symbol not in af or symbol not in bf:
                    missing.append(dict(object=obj, symbol=symbol, before=symbol in af, after=symbol in bf))
                    continue
                # canonical() compares instruction bytes and exact relocation
                # targets, ignoring only linker addresses/constant ordinals.
                if a.canonical(af[symbol]) != b.canonical(bf[symbol]):
                    changed.append(dict(object=obj, symbol=symbol,
                        before=af[symbol]['size'], after=bf[symbol]['size']))
        names = [r['symbol'] for r in changed + missing]
        readable = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
        for row, demangled in zip(changed + missing, readable): row['name'] = demangled
        rows.append(dict(arm=name, compared=total, changed=changed, missing=missing))
        print('Code audit:', name, total, 'bodies;', len(changed), 'changed;', len(missing), 'added/removed', flush=True)
        write_json('code-identity', rows)


def legacy_hybrid():
    rows = []
    for name, small in (('ref', 0), ('hyb16-d0', 16), ('hyb16-d1', 0), ('hyb16-d2', 0)):
        source = ROOT if name == 'ref' else STUDY / name
        for db0 in (False, True):
            binary = STUDY / (name + ('-db0' if db0 else '') + '-legacy-hybrid')
            raw = binary.with_suffix('.raw') if name in ('hyb16-d1', 'hyb16-d2') else binary
            old.compile_unit(source, raw, small, db0)
            if raw != binary: pad(raw, binary, (source / POLICY).read_text())
            for case in ('table', 'exits'): rows.append(old.run_case(binary, case))
    source = STUDY / 'legacy-s17'
    shutil.copytree(ROOT / 'src', source / 'src', dirs_exist_ok=True)
    (source / POLICY).write_text(old.policy(17)[1])
    for db0 in (False, True):
        binary = STUDY / ('legacy-s17' + ('-db0' if db0 else '') + '-unit')
        old.compile_unit(source, binary, 16, db0)
        rows.append(old.run_case(binary, 'table', 'piecewise threshold table'))
    write_json('legacy-hybrid', rows)
    print('PASS unchanged wbhybrid oracle, exits and strict S+1 controls', flush=True)


def code_costs():
    tracer = STUDY / 'instruction-trace'
    rows = []
    for arm, delay in {'ref': 0, **ARMS}.items():
        source = ROOT if arm == 'ref' else STUDY / arm
        for db0 in (False, True):
            binary = STUDY / (arm + ('-db0' if db0 else '') + '-codes')
            flags = old.FLAGS + (['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else [])
            subprocess.run(flags + [f'-DWBHYBRID2_DELAY={delay}', f'-DWBHYBRID2_SMALL={0 if arm == "ref" else 16}',
                f'-DWBHYBRID2_COUNTER={int(delay > 0)}', '-I' + str(source), '-I' + str(ROOT),
                str(ROOT / 'tests/wbhybrid2_codes.cc'), '-o', str(binary), '-ljemalloc'], check=True)
            elf = Elf(binary); symbol = elf.functions()['wbhybrid2_defer']; sec = elf.sections[elf.names.index('.text')]
            for done in range(3):
                for waits in (0, 2):
                    for shape in (1, 2, 3):
                        case = f'codes-{done}-{waits}-{shape}'
                        r = subprocess.run([str(tracer), str(binary), case, f'{symbol["value"]:x}',
                            f'{sec[3]:x}', f'{sec[5]:x}', str(int(elf.kind == 3))], capture_output=True, text=True, timeout=60)
                        assert r.returncode == 0 and f'PASS wbhybrid2 {case}' in r.stdout, r.stdout + r.stderr
                        count = json.loads(next(line[6:] for line in r.stdout.splitlines() if line.startswith('TRACE=')))
                        rows.append(dict(arm=arm, db0=db0, case=case, binary=str(binary.relative_to(ROOT)),
                                         sha256=sha(binary), **count))
    write_json('code-costs', rows)
    print('PASS 144 GET/OK/integer instruction receipts, both namespaces', flush=True)


def audit():
    assert not subprocess.check_output(['git', 'diff', BASE, '--', 'src', 'Makefile'], cwd=ROOT)
    assert not subprocess.check_output(['git', 'diff', 'origin/cpp', '--', 'tests/gate.sh'], cwd=ROOT)
    cache = {}
    def digest(path):
        path = Path(path)
        if path not in cache: cache[path] = sha(path)
        return cache[path]
    groups = {}
    files = [(name, STUDY / (name + '.json')) for name in ('proofs', 'paths', 'legacy-hybrid')]
    files += [(name, BUILD / (name + '-proofs.json')) for name in (
        'wb-rule-policy', 'wb-rule-phase', 'wb-rule-stages', 'wb-rule-split-phase',
        'wb-rule-split-overlap', 'wbland-clauses', 'wbland-paths')]
    for name, path in files:
        rows = json.loads(path.read_text())
        assert rows and all(r['passed'] and digest(ROOT / r['binary']) == r['sha256'] for r in rows)
        groups[name] = dict(positive=sum(r['expected_exit'] == 0 for r in rows),
                           negative=sum(r['expected_exit'] == 1 for r in rows), sha256=digest(path))
    for name, delay in ARMS.items():
        assert all((STUDY / name / path).read_text() == text for path, text in sources(delay).items())
    binaries = json.loads((STUDY / 'binaries.json').read_text())
    assert all(digest(ROOT / r['path']) == r['sha256'] for r in binaries)
    for name in ('pads', 'pad-unit-sites', 'pad-path-sites'):
        for row in json.loads((STUDY / (name + '.json')).read_text()):
            before = (ROOT / row['candidate']['path']).read_bytes()
            after = bytearray((ROOT / row['pad']['path']).read_bytes())
            assert digest(ROOT / row['candidate']['path']) == row['candidate']['sha256']
            assert digest(ROOT / row['pad']['path']) == row['pad']['sha256']
            for site in row['sites']:
                assert before[site['offset']] == 16 and after[site['offset']] == 1
                after[site['offset']] = 16
            assert before == after
            if name == 'pads': assert row['differing_bytes'] == len(row['sites']) == 2
    costs = json.loads((STUDY / 'costs.json').read_text())
    assert digest(STUDY / 'instruction-trace') == costs['tracer_sha256']
    counts = {}
    for row in costs['rows']:
        binary = STUDY / (row['arm'] + ('-db0' if row['db0'] else '') + '-unit')
        assert digest(binary) == row['binary_sha256'] and row['library_instructions'] == 0
        counts[(row['arm'], row['db0'], row['case'])] = row['instructions']
    assert len(counts) == 896
    code_costs = json.loads((STUDY / 'code-costs.json').read_text())
    assert len(code_costs) == 144 and all(digest(ROOT / r['binary']) == r['sha256'] for r in code_costs)
    coded_counts = {(r['arm'], r['db0'], r['case']): r['instructions'] for r in code_costs}
    for arm in ('hyb16-d1', 'hyb16-d2'):
        for db0 in (False, True):
            for waits in (0, 2):
                for shape in (1, 2, 3):
                    deltas = [coded_counts[(arm, db0, f'codes-{done}-{waits}-{shape}')] -
                              coded_counts[('hyb16-d0', db0, f'codes-{done}-{waits}-{shape}')]
                              for done in range(3)]
                    assert len(set(deltas)) == 1, ('per-reply overhead', arm, db0, waits, shape, deltas)
    for arm in ('ref', *ARMS):
        for db0 in (False, True):
            for waits in range(4):
                for stem in ('1-0-0-1-0', '64-1-0-0-0', '64-0-512-1-0'):
                    case = f'trace-{stem}-{waits}'
                    assert counts[(arm, db0, case)] == counts[('ref', db0, case)]
                for n in (4, 8, 16, 17, 32, 64):
                    # Every extra acquired Done in this unchanged empty-reply walk
                    # costs the same 26 instructions. State work is per visit only.
                    assert counts[(arm, db0, f'trace-{n}-1-0-1-0-{waits}')] - \
                           counts[(arm, db0, f'trace-{n}-0-0-1-0-{waits}')] == 26
    code = json.loads((STUDY / 'code-identity.json').read_text())
    assert [r['arm'] for r in code] == list(ARMS)
    disassembly = {}
    for arm in ('ref', *ARMS):
        binary = BUILD / ('tomokv-wbhybrid2-ref' if arm == 'ref' else 'tomokv-' + arm)
        elf = Elf(binary)
        for name, symbol in elf.functions().items():
            if '7wb_rule5defer' not in name: continue
            ns = 'db0' if 'tomo_db0' in name else 'multi'
            output = STUDY / f'{arm}-{ns}-defer.asm'
            output.write_text(subprocess.check_output(['objdump', '-dwC',
                f'--start-address={symbol["value"]}',
                f'--stop-address={symbol["value"] + symbol["size"]}', str(binary)], text=True))
            disassembly[output.name] = dict(sha256=sha(output), symbol_bytes=symbol['size'])
    result = dict(launch=LAUNCH, reference=BASE, groups=groups, binaries=binaries,
        instruction_receipts=len(counts), coded_instruction_receipts=len(code_costs), per_extra_done_instructions=26,
        extra_work_per_scanned_get_ok_integer_reply=0,
        early_exit_instruction_delta=0, disassembly=disassembly,
        identity=json.loads((STUDY / 'identity.json').read_text()),
        layout=json.loads((STUDY / 'layout.json').read_text()),
        strict_all_body_identity=False,
        code_audit=[dict(arm=r['arm'], compared=r['compared'], changed=len(r['changed']),
                        added_or_removed=len(r['missing'])) for r in code],
        limitation='Native compiler bodies outside the intended stores/rule also change, including d0. '
                   'Source scope and whole objects outside the include closure pass; full code-body identity does not. '
                   'Exact-layout PAD A twins isolate policy behaviour within each native layout.',
        inputs={str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__).resolve(),
            ROOT / 'tests/wbhybrid2_unit.cc', ROOT / 'tests/wbhybrid2_paths.inc',
            ROOT / 'tests/wbhybrid2_codes.cc')},
        receipts={p.name: sha(p) for p in sorted(STUDY.glob('*.json')) if p.name != 'audit.json'})
    write_json('audit', result)
    (ROOT / 'tests/wbhybrid2_evidence.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS frozen correctness, PAD, layout and instruction audit; strict code identity exceptions recorded', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('builds', 'pads', 'proofs', 'paths', 'costs', 'identity', 'layout', 'legacy',
                                     'code_identity', 'legacy_hybrid', 'code_costs', 'audit'))
    args = p.parse_args()
    old.pinned()
    STUDY.mkdir(parents=True, exist_ok=True)
    (old.legacy if args.action == 'legacy' else globals()[args.action])()
