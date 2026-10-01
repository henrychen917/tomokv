#!/usr/bin/env python3
"""Extend the frozen D2 study to D3/D4; offline only, on CPUs 112-127.

Native source builds prove the runtime sections. Measurement images retain the
frozen D2 ELF, changing only decoded D immediates, then two S immediates for PAD A.
This keeps the October 1 measured arms comparable despite the required merge.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

import wbhybrid2_artifacts as prior
from lbstall_artifacts import Elf

ROOT, BUILD = prior.ROOT, prior.BUILD
FROZEN = BUILD / 'wbhybrid2'
STUDY = BUILD / 'wbhybrid2b'
DONOR = FROZEN / 'hyb16-d2'
POLICY = prior.POLICY
ARMS = {'hyb16-d3': 3, 'hyb16-d4': 4}
LAUNCH = 'ae6b78bf8'
MERGE = '92bdd252e'
MAINLINE = '2a9e48403'
sha, receipt, replace = prior.sha, prior.receipt, prior.replace


def write_json(name, data):
    (STUDY / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')


def frozen_inputs():
    ledger = json.loads((ROOT / 'tests/wbhybrid2_evidence.json').read_text())
    for row in ledger['binaries']:
        assert receipt(ROOT / row['path']) == row, row['path']
    assert sha(BUILD / 'tomokv') == ledger['binaries'][0]['sha256']
    assert sha(DONOR / 'build/tomokv') == sha(BUILD / 'tomokv-hyb16-d2')
    assert not subprocess.check_output(['git', 'diff', MAINLINE, '--', 'src', 'Makefile', 'tests/gate.sh'], cwd=ROOT)
    for path, text in prior.sources(2).items():
        assert (DONOR / path).read_text() == text, path
    return ledger['binaries']


def d_sites(binary):
    elf = Elf(binary)
    symbols = [s for n, s in elf.functions().items() if '7wb_rule5defer' in n]
    assert len(symbols) == 2
    sites = []
    for symbol in symbols:
        asm = subprocess.check_output(['objdump', '-dw',
            f'--start-address={symbol["value"]}',
            f'--stop-address={symbol["value"] + symbol["size"]}', str(binary)], text=True)
        insns = []
        for line in asm.splitlines():
            m = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
            if m:
                insns.append((int(m[1], 16), bytes.fromhex(m[2]), m[3]))
        found = []
        for i, (address, raw, instruction) in enumerate(insns):
            if raw == bytes.fromhex('80 7f 48 01'):
                assert re.fullmatch(r'cmpb\s+\$0x1,0x48\(%rdi\)', instruction)
                assert insns[i + 1][1] == bytes.fromhex('0f 96 c0')  # unsigned <= D-1
                sec = elf.sections[symbol['sec']]
                found.append(dict(symbol=symbol['name'], address=address,
                    offset=sec[4] + address - sec[3] + 3, instruction=instruction,
                    following=insns[i + 1][2], before=1))
        assert len(found) == 1, (symbol['name'], found)
        sites.extend(found)
    return sorted(sites, key=lambda s: s['offset'])


def exact_diff(before, after, expected):
    """Reverse just the declared patches, then compare every ELF byte."""
    assert len(before) == len(after)
    restored = bytearray(after)
    for offset, (pre, post) in expected.items():
        assert pre != post and before[offset] == pre and after[offset] == post
        restored[offset] = pre
    assert restored == before, 'undeclared ELF byte difference'
    return [dict(offset=offset, offset_hex=hex(offset), before=pre, after=post)
            for offset, (pre, post) in sorted(expected.items())]


def builds():
    frozen_inputs()
    compiles, link = prior.old.commands()  # the frozen, complete reference build log
    deps = {obj: {os.path.normpath(p.rstrip(':')) for p in
        (DONOR / obj).with_suffix('.d').read_text().replace('\\\n', ' ').split()}
        for obj in compiles}
    affected = [obj for obj in compiles if POLICY in deps[obj]]
    reused = [obj for obj in compiles if obj not in affected]
    assert len(affected) == 40 and len(reused) == 44
    rows = []
    for name, delay in ARMS.items():
        source = STUDY / name
        source.mkdir(exist_ok=True)
        for tree in ('src', 'third_party'):
            if not (source / tree).exists():
                shutil.copytree(DONOR / tree, source / tree)
        shutil.copy2(DONOR / 'Makefile', source / 'Makefile')
        rule = replace((DONOR / POLICY).read_text(), 'kDeferVisits = 2;', f'kDeferVisits = {delay};')
        if (source / POLICY).read_text() != rule:
            (source / POLICY).write_text(rule)
        changed = [str(p.relative_to(DONOR)) for tree in ('src', 'third_party')
            for p in (DONOR / tree).rglob('*') if p.is_file() and
            p.read_bytes() != (source / p.relative_to(DONOR)).read_bytes()]
        assert changed == [POLICY], changed
        assert rule == prior.sources(delay)[POLICY]
        (STUDY / (name + '.patch')).write_text(''.join(difflib.unified_diff(
            (DONOR / POLICY).read_text().splitlines(True), rule.splitlines(True),
            fromfile='d2/' + POLICY, tofile=name + '/' + POLICY)))
        make = ['.PHONY: all', 'all: build/tomokv',
                'build/tomokv: ' + ' '.join(compiles), '\t' + shlex.join(link)]
        for obj, cmd in compiles.items():
            dest = source / obj
            dest.parent.mkdir(parents=True, exist_ok=True)
            if obj in affected:
                make += [obj + ': ' + POLICY, '\t' + shlex.join(cmd)]
            else:
                shutil.copy2(DONOR / obj, dest)
                shutil.copy2((DONOR / obj).with_suffix('.d'), dest.with_suffix('.d'))
                assert sha(dest) == sha(DONOR / obj)
        (source / 'study.mk').write_text('\n'.join(make) + '\n')
        print('Building', name, len(affected), 'objects with the D2 flags/link order', flush=True)
        with (STUDY / (name + '-build.log')).open('w') as log:
            subprocess.run(['make', '-j16', '-f', 'study.mk'], cwd=source,
                stdout=log, stderr=subprocess.STDOUT, check=True)
        rows.append(dict(arm=name, delay=delay, donor=str(DONOR.relative_to(ROOT)),
            affected=affected, reused=reused, native=receipt(source / 'build/tomokv')))
        print('Native build complete:', rows[-1]['native'], flush=True)
    write_json('builds', rows)


def images():
    frozen = frozen_inputs()
    binary = BUILD / 'tomokv-hyb16-d2'
    donor = Elf(binary)
    sites = d_sites(binary)
    rows, pads = [], []
    for name, delay in ARMS.items():
        target = BUILD / ('tomokv-' + name)
        data = bytearray(donor.data)
        changes = {s['offset']: (1, delay - 1) for s in sites}
        for offset, (_, post) in changes.items():
            data[offset] = post
        diffs = exact_diff(donor.data, data, changes)
        native = Elf(STUDY / name / 'build/tomokv')
        # Independently compiled runtime must be exactly this patched D2 image.
        # Native debug paths/constants and linker build ID necessarily differ.
        checked = []
        assert donor.names == native.names
        for i, (section, pre, post) in enumerate(zip(donor.names, donor.sections, native.sections)):
            if not pre[2] & 2 or section == '.note.gnu.build-id':
                continue
            assert (pre[1:4], pre[5:]) == (post[1:4], post[5:]), section
            if pre[1] != 8:  # NOBITS contains no file bytes
                assert data[pre[4]:pre[4] + pre[5]] == native.section_data(i), section
            checked.append(section)
        target.write_bytes(data)
        target.chmod(binary.stat().st_mode)
        rows.append(dict(arm=name, delay=delay, baseline=receipt(binary), candidate=receipt(target),
            native=receipt(native.path), sites=sites, differences=diffs,
            native_identical_allocated_sections=checked,
            retained_metadata='Frozen D2 debug sections and build ID; use SHA-256. Native build has current DWARF.'))
        pad = prior.pad(target, target.with_name(target.name + '-pad'),
                        (STUDY / name / POLICY).read_text())
        assert pad['differing_bytes'] == len(pad['sites']) == 2
        pads.append(pad)
        print('PASS exact D-only ELF and two-byte PAD A:', name, diffs, flush=True)
    write_json('images', rows)
    write_json('pads', pads)
    write_json('binaries', frozen + [r for p in pads for r in (p['candidate'], p['pad'])])


def proofs():
    # Reuse the original fixture compiler, PAD decoder and strict mutant oracle.
    prior.STUDY, prior.ARMS = STUDY, ARMS
    prior.proofs()
    for name, delay in (('hyb16-d0', 0), ('hyb16-d2', 2)):
        for db0 in (False, True):
            prior.compile_unit(FROZEN / name, STUDY / (name + ('-db0' if db0 else '') + '-unit'), delay, db0)


def trace(binary, case, tracer):
    elf = Elf(binary)
    symbol = elf.functions()['wbhybrid2_defer']
    section = elf.sections[elf.names.index('.text')]
    result = subprocess.run([str(tracer), str(binary), case, f'{symbol["value"]:x}',
        f'{section[3]:x}', f'{section[5]:x}', str(int(elf.kind == 3))],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and f'PASS wbhybrid2 {case}' in result.stdout, result.stdout + result.stderr
    count = json.loads(next(line[6:] for line in result.stdout.splitlines() if line.startswith('TRACE=')))
    assert count['library_instructions'] == 0
    return dict(case=case, binary=str(binary.relative_to(ROOT)), sha256=sha(binary), **count)


def costs():
    tracer = STUDY / 'instruction-trace'
    subprocess.run(prior.old.FLAGS + [str(ROOT / 'tools/wb_rule_2s_trace.cc'), '-o', str(tracer)], check=True)
    fixtures = [(1, 0, 0, 1, 0), (64, 1, 0, 0, 0), (64, 0, 512, 1, 0)]
    fixtures += [(n, done, 0, 1, 0) for n in (4, 8, 16, 17, 32, 64) for done in (0, 1, n//2, n)]
    fixtures += [(8, 1, 0, 1, 1)]
    rows, codes = [], []
    for arm, delay in {'ref': 0, 'hyb16-d0': 0, 'hyb16-d2': 2, **ARMS}.items():
        source = ROOT if arm == 'ref' else (STUDY if arm in ARMS else FROZEN) / arm
        limit = max(3, delay + 1)
        for db0 in (False, True):
            stem = arm + ('-db0' if db0 else '')
            binary = STUDY / (stem + '-unit')
            for fixture in fixtures:
                for waits in range(limit + 1):
                    case = 'trace-' + '-'.join(map(str, (*fixture, waits)))
                    rows.append(dict(arm=arm, db0=db0, **trace(binary, case, tracer)))
            coded = STUDY / (stem + '-codes')
            flags = prior.old.FLAGS + (['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else [])
            subprocess.run(flags + [f'-DWBHYBRID2_DELAY={delay}',
                f'-DWBHYBRID2_SMALL={0 if arm == "ref" else 16}', f'-DWBHYBRID2_COUNTER={int(delay > 0)}',
                '-I' + str(source), '-I' + str(ROOT), str(ROOT / 'tests/wbhybrid2_codes.cc'),
                '-o', str(coded), '-ljemalloc'], check=True)
            for done in range(3):
                for waits in sorted({0, delay, limit}):
                    for shape in (1, 2, 3):
                        case = f'codes-{done}-{waits}-{shape}'
                        codes.append(dict(arm=arm, db0=db0, **trace(coded, case, tracer)))
            print('PASS standard + boundary instruction receipts:', stem, flush=True)
    write_json('costs', dict(tracer_sha256=sha(tracer), rows=rows, codes=codes,
        scope='One wrapper/defer call, setup excluded; ptrace steps only, no clocks/PMU/server/load'))


def layout():
    rows = []
    for arm in ('hyb16-d2', *ARMS):
        binary = (DONOR if arm == 'hyb16-d2' else STUDY / arm) / 'build/tomokv'
        for ns in ('tomo', 'tomo_db0'):
            probe = (f"python import gdb,json; t=gdb.lookup_type('{ns}::Client'); "
                "print('LAYOUT='+json.dumps({'bytes':t.sizeof, 'fields':{f.name:"
                "[f.bitpos//8,f.type.sizeof] for f in t.fields() if hasattr(f,'bitpos')}}))")
            raw = subprocess.check_output(['gdb', '-nx', '-batch', str(binary), '-ex', probe], text=True)
            data = json.loads(next(line[7:] for line in raw.splitlines() if line.startswith('LAYOUT=')))
            assert data['bytes'] == 1984 and data['fields']['wb_deferrals_'] == [72, 1]
            assert data['fields']['rob_'] == [128, 192]
            rows.append(dict(arm=arm, namespace=ns, **data))
    assert all(r['fields'] == rows[0]['fields'] for r in rows)
    write_json('layout', rows)
    print('PASS every Client field/width vs D2, both namespaces; counter=72, Client=1984', flush=True)


def audit():
    frozen_inputs()
    digest_cache = {}
    def digest(path):
        path = Path(path)
        if path not in digest_cache:
            digest_cache[path] = sha(path)
        return digest_cache[path]

    images = json.loads((STUDY / 'images.json').read_text())
    builds = json.loads((STUDY / 'builds.json').read_text())
    for row, build in zip(images, builds):
        assert row['arm'] == build['arm']
        before, after = (ROOT / row[k]['path'] for k in ('baseline', 'candidate'))
        assert exact_diff(before.read_bytes(), after.read_bytes(),
            {d['offset']: (d['before'], d['after']) for d in row['differences']}) == row['differences']
        assert receipt(ROOT / row['native']['path']) == row['native'] == build['native']
        source = STUDY / row['arm']
        for path, expected in prior.sources(row['delay']).items():
            assert (source / path).read_text() == expected
        for obj in build['reused']:
            assert digest(source / obj) == digest(DONOR / obj)
    binaries = json.loads((STUDY / 'binaries.json').read_text())
    assert len(binaries) == 10
    for row in binaries:
        assert digest(ROOT / row['path']) == row['sha256']
    for name in ('pads', 'pad-unit-sites'):
        for row in json.loads((STUDY / (name + '.json')).read_text()):
            for kind in ('candidate', 'pad'):
                assert digest(ROOT / row[kind]['path']) == row[kind]['sha256']
            exact_diff((ROOT / row['candidate']['path']).read_bytes(),
                (ROOT / row['pad']['path']).read_bytes(), {s['offset']: (16, 1) for s in row['sites']})
            if name == 'pads':
                assert row['differing_bytes'] == len(row['sites']) == 2
    proofs = json.loads((STUDY / 'proofs.json').read_text())
    assert len(proofs) == 56
    for row in proofs:
        assert row['passed'] and row['exit'] == row['expected_exit']
        assert row['required'] in row['stdout'] + row['stderr']
        assert digest(ROOT / row['binary']) == row['sha256']
    costs = json.loads((STUDY / 'costs.json').read_text())
    assert digest(STUDY / 'instruction-trace') == costs['tracer_sha256']
    for row in costs['rows'] + costs['codes']:
        assert digest(ROOT / row['binary']) == row['sha256'] and row['library_instructions'] == 0
    counts = {(r['arm'], r['db0'], r['case']): r['instructions'] for r in costs['rows']}
    assert len(counts) == len(costs['rows']) == 1288
    # Recompiled REF, D0 and D2 must reproduce the previous standard fixtures.
    previous = json.loads((FROZEN / 'costs.json').read_text())['rows']
    comparisons = 0
    for row in previous:
        if row['arm'] in ('ref', 'hyb16-d0', 'hyb16-d2'):
            key = (row['arm'], row['db0'], row['case'])
            assert counts[key] == row['instructions'], (key, counts[key], row['instructions'])
            comparisons += 1
    same_branch, ordinary = [], []
    for row in costs['rows']:
        if row['arm'] not in ARMS:
            continue
        delay = ARMS[row['arm']]
        n, done, byte_count, policy, scatter, waits = map(int, row['case'].split('-')[1:])
        # Hold the threshold branch constant, accounting for the intentional D shift.
        equivalent_waits = 0 if waits < delay else 2
        fixture = '-'.join(row['case'].split('-')[:-1])
        d2 = counts[('hyb16-d2', row['db0'], f'{fixture}-{equivalent_waits}')]
        assert row['instructions'] == d2, ('D-only change altered same-branch cost', row, d2)
        same_branch.append(row['instructions'] - d2)
        ref = counts[('ref', row['db0'], f'{fixture}-0')]
        if policy == 0 or n <= 1 or byte_count >= 512:
            assert row['instructions'] == ref
        if done <= 1 or n > 16:  # the original standard same-prefix/ordinary-path criterion
            ordinary.append(dict(arm=row['arm'], db0=row['db0'], case=row['case'],
                ref=ref, candidate=row['instructions'], delta=row['instructions'] - ref))
    coded = {(r['arm'], r['db0'], r['case']): r['instructions'] for r in costs['codes']}
    assert len(coded) == len(costs['codes']) == 234
    for arm, delay in ARMS.items():
        for db0 in (False, True):
            for waits in (0, delay, delay + 1):
                for shape in (1, 2, 3):
                    deltas = [coded[(arm, db0, f'codes-{done}-{waits}-{shape}')] -
                        coded[('hyb16-d2', db0, f'codes-{done}-{0 if waits < delay else 2}-{shape}')]
                        for done in range(3)]
                    assert deltas == [0, 0, 0], (arm, db0, waits, shape, deltas)
    layouts = json.loads((STUDY / 'layout.json').read_text())
    assert len(layouts) == 6 and all(r['fields'] == layouts[0]['fields'] for r in layouts)
    disassembly = {}
    for arm in ('hyb16-d2', *ARMS):
        binary = BUILD / ('tomokv-' + arm)
        elf = Elf(binary)
        for symbol in elf.functions().values():
            if '7wb_rule5defer' not in symbol['name']:
                continue
            output = STUDY / f'{arm}-{"db0" if "tomo_db0" in symbol["name"] else "multi"}-defer.asm'
            output.write_text(subprocess.check_output(['objdump', '-dwC',
                f'--start-address={symbol["value"]}',
                f'--stop-address={symbol["value"] + symbol["size"]}', str(binary)], text=True))
            disassembly[output.name] = sha(output)
    violations = [r for r in ordinary if abs(r['delta']) > 1]
    result = dict(launch=LAUNCH, merged_commit=MERGE, mainline_at_merge=MAINLINE,
        frozen_measurement_reference='90ba908d3', binaries=binaries, images=images,
        groups=dict(positive=sum(r['expected_exit'] == 0 for r in proofs),
                    required_failures=sum(r['expected_exit'] == 1 for r in proofs)),
        instruction_receipts=len(counts), coded_instruction_receipts=len(coded),
        prior_standard_receipts_reproduced=comparisons, same_branch_instruction_delta_vs_d2=sorted(set(same_branch)),
        ordinary_within_one_instruction_of_ref=not violations,
        ordinary_delta_vs_ref=sorted({r['delta'] for r in ordinary}), ordinary_violations=violations,
        limitation='The inherited D2 counter path already exceeds +/-1 instruction versus REF. '
            'D3/D4 preserve D2 instructions on equivalent branches; fixing that cost would violate the D-immediates-only scope.',
        layout=layouts, disassembly=disassembly,
        inputs={str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__).resolve(),
            ROOT / 'tools/wbhybrid2_artifacts.py', ROOT / 'tools/wbhybrid_artifacts.py',
            ROOT / 'tools/wb_rule_2s_trace.cc', ROOT / 'tests/wbhybrid2_unit.cc',
            ROOT / 'tests/wbhybrid2_codes.cc', ROOT / 'tests/wbhybrid2_cells.txt')},
        receipts={p.name: sha(p) for p in sorted(STUDY.glob('*.json')) if p.name != 'audit.json'})
    write_json('audit', result)
    (ROOT / 'tests/wbhybrid2b_evidence.json').write_text(json.dumps(result, indent=2) + '\n')
    print('SEALED', result['groups'], len(counts), 'standard/boundary and', len(coded), 'encoder receipts', flush=True)
    print('ordinary +/-1 versus REF:', not violations, '; equivalent-branch delta versus D2:', sorted(set(same_branch)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('builds', 'images', 'proofs', 'costs', 'layout', 'audit'))
    args = parser.parse_args()
    prior.old.pinned()
    STUDY.mkdir(exist_ok=True)
    globals()[args.action]()
