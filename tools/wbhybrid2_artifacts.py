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
        '    const bool complete = n <= kSmallPipe && c.wb_deferrals() < kDeferVisits;\n'
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
    deps = {obj: (ROOT / obj).with_suffix('.d').read_text().replace('\\\n', ' ').split()
            for obj in compiles}
    rows = []
    for name, delay in ARMS.items():
        source = STUDY / name
        source.mkdir(exist_ok=True)
        for tree in ('src', 'third_party'):
            shutil.copytree(ROOT / tree, source / tree, dirs_exist_ok=True)
        shutil.copy2(ROOT / 'Makefile', source / 'Makefile')
        patch = ''
        for path, text in sources(delay).items():
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
    # The predecessor's DWARF + decoded-instruction selector audit also applies
    # to our boolean selector, on its source line. Never patch counter compares.
    locator = header.replace('const bool complete =', 'const unsigned threshold =')
    return old.pad(binary, target, 16, locator)


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
            for case in ('table', 'exits', 'lifetime'):
                rows.append(run(binary, case))
            if delay:
                raw = binary.with_name(binary.name + '-pad-raw')
                twin = binary.with_name(binary.name + '-pad')
                compile_unit(source, raw, delay, db0, small=0)
                pad_rows.append(pad(raw, twin, (source / POLICY).read_text()))
                for case in ('table', 'exits', 'lifetime'):
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
        print('PASS table/exits/lifetime and controls:', name, flush=True)
    write_json('proofs', rows)
    write_json('pad-unit-sites', pad_rows)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('builds', 'pads', 'proofs'))
    args = p.parse_args()
    old.pinned()
    STUDY.mkdir(parents=True, exist_ok=True)
    globals()[args.action]()
