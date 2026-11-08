#!/usr/bin/env python3
"""Offline cleanup-flipreport evidence and serverless controls; pin to CPUs 112-127.

Production ELF files are only read, copied, linked or compared, never executed.
The raw ELF checker is shared with the preceding cleanup lanes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tarfile

from lbstall_artifacts import Elf
from ttlstate_proof import (addresses, compare_addresses, compare_arms, compare_files,
                           program_headers, save, selected_sections)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cleanup-flipreport'
MEMBER = '    double stationary_s = 0;      // seconds the current workload has held still\n'
PADDING = '    double layout_padding = 0;   // inert: preserve report size and subsequent offsets\n'
ASSIGNMENT = '    report.stationary_s = 0;\n'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def trace_equal(expected, actual):
    assert actual == expected, 'controller trace/wire bytes differ'


def wire_control():
    out = OUT / 'controls'
    expected = (out / 'trace-PRE-normal.stdout').read_bytes()
    actual = (out / 'trace-POST-normal.stdout').read_bytes()
    trace_equal(expected, actual)
    field = b'flipctl_refine_steps:0\r\n'
    assert field in actual
    changed = actual.replace(field, b'', 1)
    (out / 'wire-field-removed.stdout').write_bytes(changed)
    try:
        trace_equal(expected, changed)
    except AssertionError as error:
        save(out / 'wire-negative.json', dict(rejected=True, exact_failure=str(error),
             removed_field=field.decode(), scope='copy of actual production formatter output'))
    else:
        raise AssertionError('wire comparison accepted an omitted field')
    print('Wire comparator rejects a removed INFO field')


def reference():
    with tarfile.open(OUT / 'freeze/PRE-source.tar') as archive:
        return {m.name: archive.extractfile(m).read()
                for m in archive.getmembers() if m.isfile() and m.name.startswith('src/')}


def source():
    old = reference()
    expected = dict(old)
    assert old['src/core/flipctl.h'].decode().count(MEMBER) == 1
    assert old['src/core/flipctl.cc'].decode().count(ASSIGNMENT) == 1
    expected['src/core/flipctl.h'] = old['src/core/flipctl.h'].replace(MEMBER.encode(), PADDING.encode())
    expected['src/core/flipctl.cc'] = old['src/core/flipctl.cc'].replace(ASSIGNMENT.encode(), b'')
    differences = [name for name, data in expected.items() if (ROOT / name).read_bytes() != data]
    result = dict(okay=not differences, unexpected_source_changes=differences,
                  files_checked=len(expected), allowed_edits=['report member to inert padding',
                                                            'remove report zero assignment'])
    save(OUT / 'source-proof.json', result)
    assert result['okay'], result
    before = json.loads((OUT / 'freeze/PRE-inputs.json').read_text())
    after = {name: digest(name) for name in before}
    save(OUT / 'freeze/POST-inputs.json', after)
    changed = [name for name in before if before[name] != after[name]]
    # Dependencies can spell one header through several relative include paths.
    assert {Path(name).resolve().relative_to(ROOT).as_posix() for name in changed} <= {
        'src/core/flipctl.h', 'src/core/flipctl.cc', 'Makefile'}, changed
    commands_equal = (OUT / 'freeze/production-commands.txt').read_bytes() == \
                     (OUT / 'freeze/POST-production-commands.txt').read_bytes()
    assert commands_equal
    save(OUT / 'freeze/reproducibility.json', dict(inputs=len(before), changed=changed,
         production_commands_identical=commands_equal, source_and_output_paths=str(ROOT)))
    print('Production source guard and frozen build-input check passed')


def elf_controls():
    out = OUT / 'elf-controls'
    out.mkdir(exist_ok=True)
    rows = []
    for name, path, kind in [
        ('text-byte', OUT / 'POST/artifacts/tomokv', 'text'),
        ('text-subsection-byte', OUT / 'POST/artifacts/src/core/flipctl.o', 'subsection'),
        ('relocation', OUT / 'POST/artifacts/src/core/flipctl.o', 'relocation'),
        ('function-address', OUT / 'POST/artifacts/tomokv', 'address'),
        ('entry-point', OUT / 'POST/artifacts/tomokv', 'entry')]:
        elf = Elf(path)
        data = bytearray(elf.data)
        if kind in ('text', 'subsection'):
            i = next(i for i, (s, n) in enumerate(zip(elf.sections, elf.names))
                     if s[2] & 4 and s[5] and
                     (n == '.text' if kind == 'text' else n.startswith('.text.')))
            data[elf.sections[i][4]] ^= 1
            error = f'executable {elf.names[i]}: bytes differ'
        elif kind == 'relocation':
            s = next(s for s in elf.sections if s[1] == 4 and s[5] and
                     s[7] < len(elf.sections) and elf.sections[s[7]][2] & 4)
            at = s[4] + 16
            struct.pack_into('<q', data, at, struct.unpack_from('<q', data, at)[0] + 1)
            error = 'allocated relocation targets differ'
        elif kind == 'entry':
            struct.pack_into('<Q', data, 24, struct.unpack_from('<Q', data, 24)[0] + 1)
            error = 'ELF kind/machine/entry or program headers differ'
        else:
            table, index = next((t, i) for t, symbols in elf.tables.items()
                                for i, s in enumerate(symbols) if s['info'] & 15 == 2 and s['size']
                                and 0 < s['sec'] < len(elf.sections) and elf.sections[s['sec']][2] & 4)
            at = elf.sections[table][4] + index * elf.sections[table][9] + 8
            struct.pack_into('<Q', data, at, struct.unpack_from('<Q', data, at)[0] + 1)
            error = 'allocated symbol addresses/identities differ'
        broken = out / (name + '.NEVER-RUN')
        broken.write_bytes(data)
        broken.chmod(0o600)
        result = compare_files(path, broken)
        save(out / (name + '.json'), result)
        assert not result['okay'] and error in result['errors'], result
        rows.append(dict(control=name, rejected=True, expected_error=error, executed=False))
    save(out / 'results.json', rows)
    print('Five corrupted ELF controls rejected without execution')


def pad():
    """Kind A, only if PRE already has POST's complete allocated/function layout.

    Copying PRE then proves PRE behavior exactly. No footer, instruction patch or
    candidate behavior is used. This does not assert PRE/POST byte identity.
    """
    pre, post = OUT / 'PRE', OUT / 'POST'
    rows = []
    for name in json.loads((pre / 'manifest.json').read_text()):
        a, b = Elf(pre / 'artifacts' / name), Elf(post / 'artifacts' / name)
        la = {n: v[0] for n, v in selected_sections(a, 2).items()}
        lb = {n: v[0] for n, v in selected_sections(b, 2).items()}
        addr, renames = compare_addresses(a, b)
        funcs_a = [row for row in addresses(a) if row[1][1] & 15 == 2]
        funcs_b = [row for row in addresses(b) if row[1][1] & 15 == 2]
        okay = (la == lb and addr and funcs_a == funcs_b and a.data[16:32] == b.data[16:32]
                and program_headers(a) == program_headers(b))
        rows.append(dict(artifact=name, okay=okay, functions=len(funcs_a),
                         allocated_sections=len(la), renamed_local_labels=renames))
    save(OUT / 'PAD-A-layout.json', dict(okay=all(r['okay'] for r in rows), rows=rows))
    assert all(r['okay'] for r in rows), 'PRE is not a behavior twin at POST layout'
    dest = OUT / 'PAD-A'
    assert not dest.exists(), 'refusing to overwrite PAD arm'
    shutil.copytree(pre, dest)
    result = compare_arms(pre, dest)
    save(OUT / 'identity-PRE-PAD-A.json', result)
    assert result['okay'] and all(r['whole_file_equal'] for r in result['rows'])
    save(OUT / 'identity-PAD-A-POST.json', compare_arms(dest, post))
    print('Kind-A PAD: exact PRE bytes, independently verified POST section/function layout')


def controls():
    out = OUT / 'controls'
    out.mkdir(exist_ok=True)
    pre_source = out / 'PRE-source'
    pre_source.mkdir(exist_ok=True)
    with tarfile.open(OUT / 'freeze/PRE-source.tar') as archive:
        archive.extractall(pre_source, members=(m for m in archive.getmembers()
                           if m.name.startswith(('src/', 'third_party/'))), filter='data')
    original = (ROOT / 'tests/core_concurrency_unit.cc').read_text()
    driver = original[:original.index('    static Op& prepare(')]
    driver += '#include "tests/flipreport_checks.inc"\n};\n}\n'
    driver += '''int main(int argc, char**) {
    using T = tomo::CoreConcurrencyTest;
    T::require(tomo::command_registry_init(false), "command registry initialization");
    T::flipreport_all(argc == 2);
}
'''
    (out / 'driver.cc').write_text(driver)
    flags = ['-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
             '-DTOMO_JEMALLOC', '-DTOMO_CORE_CONCURRENCY_TEST']
    libs = ['-ljemalloc', '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
    lines, targets = [], []

    def recipe(target, deps, command):
        lines.extend([str(target) + ': ' + ' '.join(map(str, deps)), '\t' + shlex.join(command)])

    def objects(arm, ns):
        base = OUT / arm / 'artifacts'
        normal = sorted(p for p in (base / 'src').rglob('*.o') if p.name not in ('main.o', 'version.o'))
        if ns == 'normal': return normal
        return sorted(p for p in (base / 'db0/src').rglob('*.o') if p.name not in ('main.o', 'version.o')) + normal

    drivers = {}
    for arm in ('PRE', 'POST'):
        for ns in ('normal', 'db0'):
            obj = out / f'driver-{arm}-{ns}.o'
            nsflags = [] if ns == 'normal' else ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
            include = ['-I' + str(pre_source)] if arm == 'PRE' else []
            recipe(obj, [out / 'driver.cc', ROOT / 'tests/flipreport_checks.inc'],
                   ['g++', *flags, *nsflags, *include, '-I' + str(ROOT), '-c', str(out / 'driver.cc'), '-o', str(obj)])
            drivers[arm, ns] = obj
    positives = []
    for arm in ('PRE', 'POST', 'PAD-A'):
        for ns in ('normal', 'db0'):
            obj = drivers['POST' if arm == 'POST' else 'PRE', ns]
            exe = out / f'trace-{arm}-{ns}'
            inputs = [obj, *objects(arm, ns)]
            recipe(exe, inputs, ['g++', '-pthread', *map(str, inputs), '-o', str(exe), *libs])
            positives.append((arm, ns, exe)); targets.append(exe)

    body = (ROOT / 'src/core/flipctl.cc').read_text()
    local = ('const double stationary_s = (now_ms > stationary_since_ms_ && stationary_since_ms_)\n'
             '            ? static_cast<double>(now_ms - stationary_since_ms_) / 1000.0 : 0;')
    assert body.count(local) == 1
    pricing = '        pays = debug_force || (model_verify_readings_ > 0 && model_cost_.pays);'
    assert body.count(pricing) == 1
    sampling = '    if (!sample_role_demand(server, now_ms, io_frac, io_headroom, ex_headroom)) return false;'
    assert body.count(sampling) == 1
    mutants = [
        ('local-zero', body.replace(local, 'const double stationary_s = 0;'),
         'FAIL flipreport short: actual horizon is 10 seconds'),
        ('local-frozen', body.replace(local, 'const double stationary_s = 10;'),
         'FAIL flipreport long: actual horizon grows to 45 seconds'),
        ('unentered', body.replace(sampling, '    return false;'),
         'FAIL flipreport short: cost window entered'),
        ('short-bypass', body.replace(pricing, '        if (now_ms == 11000) model_cost_.pays = true;\n' + pricing),
         'FAIL flipreport short: cost blocks move'),
        ('long-blocked', body.replace(pricing, '        if (now_ms == 46000) model_cost_.pays = false;\n' + pricing),
         'FAIL flipreport long: cost permits move')]
    for name, changed, _ in mutants:
        cc, obj, exe = (out / (name + suffix) for suffix in ('.cc', '.o', '.unit'))
        cc.write_text(changed)
        recipe(obj, [cc], ['g++', *flags, '-I' + str(ROOT), '-iquote', str(ROOT / 'src/core'),
                          '-c', str(cc), '-o', str(obj)])
        inputs = [drivers['POST', 'normal'], obj, *[p for p in objects('POST', 'normal') if p.name != 'flipctl.o']]
        recipe(exe, inputs, ['g++', '-pthread', *map(str, inputs), '-o', str(exe), *libs])
        targets.append(exe)

    # An assignment-only PRE twin separates removing the write from removing its name.
    old = (pre_source / 'src/core/flipctl.cc').read_text()
    assert old.count(ASSIGNMENT) == 1
    cc = out / 'assignment-only.cc'
    cc.write_text(old.replace(ASSIGNMENT, ''))
    for ns in ('normal', 'db0'):
        obj, exe = out / f'assignment-only-{ns}.o', out / f'trace-assignment-only-{ns}'
        nsflags = [] if ns == 'normal' else ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        recipe(obj, [cc], ['g++', *flags, *nsflags, '-I' + str(pre_source), '-I' + str(ROOT),
                          '-iquote', str(pre_source / 'src/core'), '-c', str(cc), '-o', str(obj)])
        oldobj = OUT / 'PRE/artifacts' / ('src/core/flipctl.o' if ns == 'normal' else 'db0/src/core/flipctl.o')
        inputs = [drivers['PRE', ns], obj, *[p for p in objects('PRE', ns) if p != oldobj]]
        recipe(exe, inputs, ['g++', '-pthread', *map(str, inputs), '-o', str(exe), *libs])
        positives.append(('assignment-only', ns, exe)); targets.append(exe)

    # Bypass the real formatter call: the wire fixture must reject empty output.
    inc = (ROOT / 'tests/flipreport_checks.inc').read_text()
    statement = '        op.spec->handler(f.server.shard(0), op);'
    assert inc.count(statement) == 1
    (out / 'no-wire.inc').write_text(inc.replace(statement, '        ;'))
    no_wire = out / 'no-wire.cc'
    no_wire.write_text(driver.replace('"tests/flipreport_checks.inc"', '"' + str(out / 'no-wire.inc') + '"'))
    exe = out / 'no-wire.unit'
    inputs = objects('POST', 'normal')
    recipe(exe, [no_wire, out / 'no-wire.inc', *inputs],
           ['g++', *flags, '-I' + str(ROOT), str(no_wire), *map(str, inputs), '-o', str(exe), *libs])
    targets.append(exe)
    (out / 'Makefile').write_text('\n'.join(lines) + '\n')
    with (out / 'build.log').open('w') as log:
        subprocess.run(['make', '-j16', '-f', str(out / 'Makefile'), *map(str, targets)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)

    traces, results = {}, []
    for arm, ns, exe in positives:
        p = subprocess.run([str(exe), 'wire'], capture_output=True)
        (out / f'{exe.name}.stdout').write_bytes(p.stdout)
        (out / f'{exe.name}.stderr').write_bytes(p.stderr)
        assert p.returncode == 0, (arm, ns, p.stderr)
        assert p.stdout.count(b'TRACE flipreport ') == (4 if ns == 'normal' else 2)
        assert p.stdout.count(b'WIRE flipreport ') == (20 if ns == 'normal' else 10)
        traces[arm, ns] = p.stdout
        if arm != 'PRE':
            trace_equal(traces['PRE', ns], p.stdout)
        results.append(dict(arm=arm, namespace=ns, rc=p.returncode, binary_sha256=digest(exe),
                            trace_sha256=hashlib.sha256(p.stdout).hexdigest(), equal_to_PRE=True))
    save(out / 'positives.json', results)
    negatives = []
    for name, _, diagnostic in mutants:
        exe = out / (name + '.unit')
        p = subprocess.run([str(exe)], capture_output=True)
        (out / (name + '.log')).write_bytes(p.stdout + p.stderr)
        assert p.returncode == 1 and diagnostic.encode() in p.stderr, (name, p.returncode, p.stderr)
        negatives.append(dict(control=name, rc=p.returncode, exact_failure=diagnostic))
    p = subprocess.run([str(out / 'no-wire.unit'), 'wire'], capture_output=True)
    (out / 'no-wire.log').write_bytes(p.stdout + p.stderr)
    diagnostic = 'FAIL flipreport short: wire entered'
    assert p.returncode == 1 and diagnostic.encode() in p.stderr, p.stderr
    negatives.append(dict(control='no-wire', rc=p.returncode, exact_failure=diagnostic))

    # Restore the actual old member in a throwaway header overlay. Compile the
    # real model unit's requires-expression; a comment/search match is insufficient.
    overlay = out / 'restored'
    shutil.copytree(ROOT / 'src', overlay / 'src', dirs_exist_ok=True)
    header = overlay / 'src/core/flipctl.h'
    header.write_text(header.read_text().replace(PADDING, MEMBER))
    command = ['g++', '-std=c++20', '-O2', '-fsyntax-only', '-I' + str(overlay),
               '-I' + str(ROOT), str(ROOT / 'tests/flipctl_unit.cc')]
    p = subprocess.run(command, capture_output=True)
    (out / 'restored-member.log').write_bytes(p.stdout + p.stderr)
    diagnostic = 'unused stationarity report member must remain absent'
    assert p.returncode != 0 and diagnostic.encode() in p.stderr, p.stderr
    negatives.append(dict(control='restored-member', rc=p.returncode, exact_failure=diagnostic))
    save(out / 'negatives.json', negatives)
    print('PRE/POST/PAD-A/assignment-only traces and wire bytes match; seven controls rejected')


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['source', 'elf-controls', 'pad', 'controls', 'wire-control'])
    args = parser.parse_args()
    {'source': source, 'elf-controls': elf_controls, 'pad': pad, 'controls': controls,
     'wire-control': wire_control}[args.command]()


if __name__ == '__main__':
    main()
