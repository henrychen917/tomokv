#!/usr/bin/env python3
"""Build and prove offline wbhybrid arms. Never starts a server or measures time/rate.

The production checkout stays on the half rule. Study source copies differ in
wb_rule.h only; compiler dependency files select the objects to rebuild. All
compilation and serverless execution must inherit CPUs 112-127.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
STUDY = BUILD / 'wbhybrid'
LAUNCH = 'e49471fa5620b747c18f4364ce990441bfe0ea64'
BASE = '5b3d9c4292bf8b332d493beb485266ecc5a289aa'
POLICY = 'src/core/wb_rule.h'
ARMS = {'hyb8': 8, 'hyb16': 16, 'hyb32': 32}
HALF = '(n * kPolicyFraction.num + kPolicyFraction.den - 1) / kPolicyFraction.den'
FLAGS = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native',
         '-pthread', '-DTOMO_JEMALLOC']


def pinned():
    assert os.sched_getaffinity(0) <= set(range(112, 128)), 'use taskset -c 112-127'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(name, data):
    (STUDY / name).write_text(json.dumps(data, indent=2) + '\n')


def receipt(path):
    elf = Elf(path)
    sizes = dict(zip(elf.names, (s[5] for s in elf.sections)))
    return dict(path=str(Path(path).relative_to(ROOT)), sha256=sha(path),
                text=sizes['.text'], tdata=sizes.get('.tdata', 0), tbss=sizes.get('.tbss', 0))


def replace(text, old, new):
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new)


def policy(small):
    original = (ROOT / POLICY).read_text()
    candidate = replace(original, 'namespace tomo::wb_rule {',
        'namespace tomo::wb_rule {\n'
        '// STUDY ARM: measured per-connection reply count, not a runtime knob.\n'
        '// No honest derivation from a connection batch, RYOW capacity, or variable reply size.\n'
        f'inline constexpr unsigned kSmallPipe = {small};')
    candidate = replace(candidate, f'const unsigned threshold = {HALF};',
        f'const unsigned threshold = n <= kSmallPipe ? n : {HALF};')
    return original, candidate


def commands():
    compiles, link = {}, None
    for line in (STUDY / 'ref-build.log').read_text().splitlines():
        if not line.startswith('g++ '):
            continue
        cmd = shlex.split(line)
        if '-o' not in cmd:
            continue
        output = cmd[cmd.index('-o') + 1]
        if '-c' in cmd:
            compiles[output] = cmd
        elif output == 'build/tomokv':
            link = cmd
    assert link and set(arg for arg in link if arg.endswith('.o')) == set(compiles)
    return compiles, link


def builds():
    assert not subprocess.check_output(['git', 'diff', BASE, '--', 'src', 'Makefile'], cwd=ROOT)
    compiles, link = commands()
    affected, reused = [], []
    for obj in compiles:
        deps = (ROOT / obj).with_suffix('.d').read_text().replace('\\\n', ' ').split()
        (affected if POLICY in deps else reused).append(obj)
    assert affected and reused
    write_json('dependencies.json', dict(base=BASE, launch=LAUNCH, affected=affected, reused=reused))
    print(f'{len(affected)} rule-dependent objects; {len(reused)} immutable reused objects', flush=True)
    for name, small in ARMS.items():
        source = STUDY / name
        source.mkdir(exist_ok=True)
        for tree in ('src', 'third_party'):
            shutil.copytree(ROOT / tree, source / tree, dirs_exist_ok=True)
        shutil.copy2(ROOT / 'Makefile', source / 'Makefile')
        original, candidate = policy(small)
        (source / POLICY).write_text(candidate)
        (STUDY / (name + '.patch')).write_text(''.join(difflib.unified_diff(
            original.splitlines(True), candidate.splitlines(True),
            fromfile='a/' + POLICY, tofile='b/' + POLICY)))
        make = ['.PHONY: all', 'all: build/tomokv',
                'build/tomokv: ' + ' '.join(compiles), '\t' + shlex.join(link)]
        for obj, cmd in compiles.items():
            dest = source / obj
            dest.parent.mkdir(parents=True, exist_ok=True)
            if obj in affected:
                make += [obj + ': ' + POLICY, '\t' + shlex.join(cmd)]
            elif not dest.exists():
                os.link(ROOT / obj, dest)  # immutable input; never a compiler output
        (source / 'study.mk').write_text('\n'.join(make) + '\n')
        print('Building', name, flush=True)
        with (STUDY / (name + '-build.log')).open('w') as log:
            subprocess.run(['make', '-j16', '-f', 'study.mk'], cwd=source,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        shutil.copy2(source / 'build/tomokv', BUILD / ('tomokv-' + name))
        print(json.dumps(receipt(BUILD / ('tomokv-' + name))), flush=True)


def pad(binary, target, small, header):
    """Exact-layout PAD A: patch only the C++ ternary's compare immediate S -> 1.

    n<=1 has already exited. The patched selector therefore always chooses half.
    DWARF source locations plus instruction boundaries identify every site. No
    pattern replacement in arbitrary bytes; no relink; every other byte matches.
    """
    elf = Elf(binary)
    line_number = next(i for i, line in enumerate(header.splitlines(), 1)
                       if 'const unsigned threshold = n <= kSmallPipe' in line)
    sites, source_line, pending = [], None, None
    process = subprocess.Popen(['objdump', '-dwl', str(binary)], stdout=subprocess.PIPE, text=True)
    for line in process.stdout:
        match = re.search(r'([^\s]+\.(?:h|cc)):(\d+)', line)
        if match:
            source_line = (match[1], int(match[2]))
        insn = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
        if not insn:
            continue
        address, raw, text = int(insn[1], 16), bytes.fromhex(insn[2]), insn[3]
        if pending is not None:
            assert re.match(r'(jbe|ja|cmovbe|cmova)\s', text), (pending, text)
            pending['select'] = text
            sites.append(pending)
            pending = None
        if source_line and source_line[0].endswith('/' + POLICY) and source_line[1] == line_number:
            if re.match(rf'cmp\s+\$0x{small:x},%[a-z0-9]+$', text):
                # GCC emits cmp imm8,r32 (optional REX prefix), never an address or displacement.
                opcode = raw[1:] if 0x40 <= raw[0] <= 0x4f else raw
                assert len(opcode) == 3 and opcode[0] == 0x83 and opcode[1] & 0xf8 == 0xf8
                assert raw[-1] == small
                sec = next(s for s in elf.sections if s[2] & 4 and s[3] <= address < s[3] + s[5])
                offset = sec[4] + address - sec[3] + len(raw) - 1
                pending = dict(address=address, offset=offset, instruction=text, source=source_line)
    assert process.wait() == 0 and pending is None and sites, (binary, sites)
    data = bytearray(elf.data)
    for site in sites:
        assert data[site['offset']] == small
        data[site['offset']] = 1
    target.write_bytes(data)
    target.chmod(binary.stat().st_mode)
    changed = [i for i, (a, b) in enumerate(zip(elf.data, data)) if a != b]
    assert changed == sorted(site['offset'] for site in sites)
    return dict(kind='A: half-rule behaviour, exact candidate ELF layout and instruction shape',
                candidate=receipt(binary), pad=receipt(target), sites=sites,
                differing_bytes=len(changed), scope='All other ELF bytes identical, including symbols and addresses; retained build ID, identify by SHA-256')


def pads():
    rows = []
    for name, small in ARMS.items():
        row = pad(BUILD / ('tomokv-' + name), BUILD / ('tomokv-' + name + '-pad'),
                  small, (STUDY / name / POLICY).read_text())
        rows.append(row)
        print(name, 'PAD A sites:', len(row['sites']), flush=True)
    write_json('pads.json', rows)
    write_json('binaries.json', [receipt(BUILD / 'tomokv')] +
               [item for row in rows for item in (row['candidate'], row['pad'])])


def run_case(binary, case, negative=None, args=(), marker='wbhybrid'):
    r = subprocess.run([str(binary), case, *args], text=True, capture_output=True, timeout=60)
    expected = 1 if negative else 0
    required = f'FAIL {marker} {case}: {negative}' if negative else f'PASS {marker} {case}'
    ok = r.returncode == expected and required in r.stdout + r.stderr
    row = dict(binary=str(binary.relative_to(ROOT)), sha256=sha(binary), case=case, args=args,
               expected_exit=expected, exit=r.returncode, required=required, passed=ok,
               stdout=r.stdout, stderr=r.stderr)
    assert ok, row
    return row


def compile_unit(source, output, small, db0=False, oracle=None):
    flags = FLAGS + (['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else [])
    flags += [f'-DWBHYBRID_EXPECT_SMALL={small if oracle is None else oracle}']
    subprocess.run(flags + ['-I' + str(source), '-I' + str(ROOT),
        str(ROOT / 'tests/wbhybrid_unit.cc'), '-o', str(output), '-ljemalloc'], check=True)


def proofs():
    rows, pad_rows = [], []
    for name, small in {'ref': 0, **ARMS}.items():
        source = ROOT if name == 'ref' else STUDY / name
        for db0 in (False, True):
            binary = STUDY / (name + ('-db0' if db0 else '') + '-unit')
            compile_unit(source, binary, small, db0)
            rows += [run_case(binary, case) for case in ('table', 'exits')]
            if small:
                # Freeze the exact same code with a half-rule oracle, then patch the
                # same instruction sites as the delivered server PAD. Oracle only
                # lives outside defer; the production template stays the candidate.
                raw = STUDY / (binary.name + '-pad-oracle')
                twin = STUDY / (binary.name + '-pad')
                compile_unit(source, raw, small, db0, oracle=0)
                pad_rows.append(pad(raw, twin, small, (source / POLICY).read_text()))
                rows += [run_case(twin, case) for case in ('table', 'exits')]
                control = STUDY / (name + '-off-by-one')
                shutil.copytree(source / 'src', control / 'src', dirs_exist_ok=True)
                (control / POLICY).write_text(policy(small + 1)[1])
                mutant = STUDY / (binary.name + '-off-by-one')
                compile_unit(control, mutant, small, db0)
                rows.append(run_case(mutant, 'table', 'piecewise threshold table'))
        print('PASS threshold/exit witnesses and strict controls:', name, flush=True)
    write_json('proofs.json', rows)
    write_json('pad-unit-sites.json', pad_rows)


def costs():
    tracer = STUDY / 'instruction-trace'
    subprocess.run(FLAGS + [str(ROOT / 'tools/wb_rule_2s_trace.cc'), '-o', str(tracer)], check=True)
    rows = []
    # Equal-prefix fixtures isolate selector work. Full pipes also expose the
    # deliberately longer walk; it must not be hidden as a fixed selector cost.
    fixtures = [(1, 0, 0, 1, 0), (64, 1, 0, 0, 0), (64, 0, 512, 1, 0)]
    fixtures += [(n, done, 0, 1, 0) for n in (8, 16, 17, 32, 33, 64) for done in (0, 1, n)]
    fixtures += [(64, 1, 0, 1, 1)]
    for name in ('ref', *ARMS):
        binary = STUDY / (name + '-unit')
        elf = Elf(binary)
        symbol = elf.functions()['wbhybrid_defer']
        sec = elf.sections[elf.names.index('.text')]
        for fixture in fixtures:
            case = 'trace-' + '-'.join(map(str, fixture))
            result = subprocess.run([str(tracer), str(binary), case, f'{symbol["value"]:x}',
                f'{sec[3]:x}', f'{sec[5]:x}', str(int(elf.kind == 3))],
                text=True, capture_output=True, timeout=60)
            assert result.returncode == 0 and f'PASS wbhybrid {case}' in result.stdout, result.stdout + result.stderr
            count = json.loads(next(line[6:] for line in result.stdout.splitlines() if line.startswith('TRACE=')))
            rows.append(dict(arm=name, case=case, **count, binary_sha256=sha(binary)))
        print('PASS single-step receipts:', name, flush=True)
    write_json('costs.json', dict(scope='One actual defer invocation, no timing/PMU/server/IO; fixture setup excluded',
                                tracer_sha256=sha(tracer), rows=rows))


def identity():
    deps = json.loads((STUDY / 'dependencies.json').read_text())
    rows = []
    for name in ARMS:
        source = STUDY / name
        changed_sources = [str(p.relative_to(ROOT)) for tree in ('src', 'third_party')
                           for p in (ROOT / tree).rglob('*') if p.is_file() and
                           p.read_bytes() != (source / p.relative_to(ROOT)).read_bytes()]
        assert changed_sources == [POLICY], changed_sources
        assert (source / 'Makefile').read_bytes() == (ROOT / 'Makefile').read_bytes()
        for obj in deps['reused']:
            before, after = sha(ROOT / obj), sha(source / obj)
            assert before == after, (name, obj)
            rows.append(dict(arm=name, object=obj, sha256=before, identical=True))
        # Recompiled includes have the same closure; no hidden source/input changes.
        for obj in deps['affected']:
            before = (ROOT / obj).with_suffix('.d').read_text()
            after = (source / obj).with_suffix('.d').read_text()
            assert before == after, (name, obj, 'dependency drift')
        print('PASS source and complete immutable-object identity:', name, flush=True)
    write_json('identity.json', dict(base=BASE, launch=LAUNCH, rows=rows, affected=deps['affected'],
        launch_merge_diff=subprocess.check_output(['git', 'diff', '--stat', LAUNCH, BASE], cwd=ROOT, text=True),
        caveat='The required merge imported unrelated mainline changes. Isolation is against merged BASE; literal launch identity is audited separately.'))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('builds', 'pads', 'proofs', 'costs', 'identity'))
    args = p.parse_args()
    pinned()
    STUDY.mkdir(exist_ok=True)
    globals()[args.action]()
