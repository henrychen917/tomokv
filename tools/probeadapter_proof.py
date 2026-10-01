#!/usr/bin/env python3
"""Offline probe adapter proofs and throwaway serverless controls; never run a server."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import tarfile

from lbstall_artifacts import Elf
from ttlstate_proof import compare_files, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cleanup-probeadapter'


def reference():
    with tarfile.open(OUT / 'freeze/reference.tar') as archive:
        return archive.extractfile('src/store/flatstore.h').read().decode()


def body(text, start, end):
    return text[text.index(start):text.index(end, text.index(start))]


def source():
    pre = reference()
    post = (ROOT / 'src/store/flatstore.h').read_text()
    start = '    ReadLocalPrefetchCapture read_local_prefetch_capture('
    end = '\n    void prefetch('
    # Restrict to the method itself, before the existing test-hook declaration.
    a = body(pre, start, '\n#ifdef TOMO_CORE_CONCURRENCY_TEST\n    // Deterministic')
    b = body(post, start, '\n#if defined(TOMO_CORE_CONCURRENCY_TEST) || defined(TOMO_PROBEADAPTER_TEST)\n    // Deterministic')
    b = b.replace('#ifdef TOMO_PROBEADAPTER_TEST\n        if (test_read_local_capture_entered) test_read_local_capture_entered(*this);\n#endif\n', '')
    b = b.replace('#if defined(TOMO_CORE_CONCURRENCY_TEST) || defined(TOMO_PROBEADAPTER_TEST)',
                  '#ifdef TOMO_CORE_CONCURRENCY_TEST')
    assert a == b, 'production capture changed beyond test-only witnesses'
    strip = lambda s: re.sub(r'\s+', '', re.sub(r'//[^\n]*', '', s))
    a = body(pre, '    const KvObj* read_local_capture_in(', '\n    static void read_local_prefetch_object(')
    b = body(post, '    const KvObj* read_local_capture_in(', '\n    static void read_local_prefetch_object(')
    assert strip(a) == strip(b), 'capture walk changed beyond rationale comment'
    assert 'read_local_find_in(' not in post
    adapter = body(post, '    ReadLocalProbe read_local_probe(', '\n#ifdef TOMO_PROBEADAPTER_TEST')
    assert strip(adapter) == strip('''
    ReadLocalProbe read_local_probe(uint64_t hash, Slice key) const {
        const auto capture = read_local_prefetch_capture(hash, key);
        return {capture.result, capture.object, capture.state};
    }
    ''')
    assertion = 'assert((pointer & ~kPtrMask) == 0'
    assert pre[:pre.index(assertion)].count('\n') == post[:post.index(assertion)].count('\n'), 'release assert line changed'
    save(OUT / 'source-proof.json', dict(capture_verbatim_except_test_hooks=True,
         capture_walk_verbatim_except_comment=True, obsolete_walk_absent=True,
         adapter_exact_projection=True, release_assert_line_preserved=True))


def elf_controls():
    out = OUT / 'elf-controls'
    out.mkdir(exist_ok=True)
    rows = []
    for name, relative, kind in [
            ('text-byte', 'tomokv', 'text'),
            ('text-subsection-byte', 'src/core/genthread.o', 'subsection'),
            ('relocation-target', 'src/core/genthread.o', 'relocation'),
            ('function-address', 'tomokv', 'address'),
            ('entry-point', 'tomokv', 'entry')]:
        path = OUT / 'POST/artifacts' / relative
        elf = Elf(path)
        data = bytearray(elf.data)
        if kind in ('text', 'subsection'):
            i = next(i for i, (s, n) in enumerate(zip(elf.sections, elf.names))
                     if s[2] & 4 and s[5] and (n == '.text' if kind == 'text' else n.startswith('.text.')))
            data[elf.sections[i][4]] ^= 1
            expected = f'executable {elf.names[i]}: bytes differ'
        elif kind == 'relocation':
            s = next(s for s in elf.sections if s[1] == 4 and s[5] and
                     s[7] < len(elf.sections) and elf.sections[s[7]][2] & 4)
            offset = s[4] + 16
            struct.pack_into('<q', data, offset, struct.unpack_from('<q', data, offset)[0] + 1)
            expected = 'allocated relocation targets differ'
        elif kind == 'address':
            table, i = next((t, i) for t, symbols in elf.tables.items()
                            for i, s in enumerate(symbols) if s['info'] & 15 == 2 and s['size']
                            and 0 < s['sec'] < len(elf.sections) and elf.sections[s['sec']][2] & 4)
            offset = elf.sections[table][4] + i * elf.sections[table][9] + 8
            struct.pack_into('<Q', data, offset, struct.unpack_from('<Q', data, offset)[0] + 1)
            expected = 'allocated symbol addresses/identities differ'
        else:
            struct.pack_into('<Q', data, 24, struct.unpack_from('<Q', data, 24)[0] + 1)
            expected = 'ELF kind/machine/entry or program headers differ'
        broken = out / (name + '.NEVER-RUN')
        broken.write_bytes(data)
        broken.chmod(0o600)
        result = compare_files(path, broken)
        assert not result['okay'] and expected in result['errors'], result
        save(out / (name + '.json'), result)
        rows.append(dict(control=name, rejected=True, expected_error=expected, executed=False))
    save(out / 'results.json', rows)


def replace_once(text, old, new):
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new, 1)


def generate():
    out = OUT / 'controls'
    tree = out / 'source'
    tree.mkdir(parents=True, exist_ok=True)
    for directory in ('src', 'tests'):
        shutil.copytree(ROOT / directory, tree / directory, dirs_exist_ok=True)
    if not (tree / 'third_party').exists():
        (tree / 'third_party').symlink_to(ROOT / 'third_party', target_is_directory=True)
    header = tree / 'src/store/flatstore.h'
    text = header.read_text()
    text = replace_once(text, 'namespace tomo {', '''inline bool probeadapter_fault(const char* name) {
    const char* fault = std::getenv("PROBEADAPTER_FAULT");
    return fault && std::strcmp(fault, name) == 0;
}
namespace tomo {''')
    pre = reference()
    legacy = body(pre, '    ReadLocalProbe read_local_probe(', '\n    bool read_local_validate(')
    legacy += body(pre, '    const KvObj* read_local_find_in(', '\n    const KvObj* read_local_capture_in(')
    legacy = legacy.replace('read_local_probe(', 'legacy_read_local_probe(').replace('read_local_find_in(', 'legacy_read_local_find_in(')
    anchor = '    ReadLocalProbe read_local_probe(uint64_t hash, Slice key) const {\n'
    text = replace_once(text, anchor, legacy + '\n' + anchor +
                        '        if (probeadapter_fault("legacy")) return legacy_read_local_probe(hash, key);\n')
    text = replace_once(text, 'return {capture.result, capture.object, capture.state};',
                        'return {capture.result, probeadapter_fault("drop-object") ? nullptr : capture.object, '
                        'probeadapter_fault("drop-state") ? 0 : capture.state};')
    start = text.index('    ReadLocalPrefetchCapture read_local_prefetch_capture(')
    end = text.index('\n#if defined(TOMO_CORE_CONCURRENCY_TEST)', text.index('    }', start))
    capture = text[start:end]
    capture = replace_once(capture, 'if (test_read_local_capture_entered)',
                           'if (!probeadapter_fault("no-entry") && test_read_local_capture_entered)')
    capture = replace_once(capture, 'if (test_read_local_captured)',
                           'if (!probeadapter_fault("no-walk") && test_read_local_captured)')
    capture = replace_once(capture, '{ReadLocalProbeResult::Churn, nullptr, nullptr, 0}',
                           '{probeadapter_fault("disabled-missing") ? ReadLocalProbeResult::Missing : ReadLocalProbeResult::Churn, nullptr, nullptr, 0}')
    capture = replace_once(capture, '{ReadLocalProbeResult::AtomicPending, nullptr, nullptr, state}',
                           '{probeadapter_fault("pending-missing") ? ReadLocalProbeResult::Missing : ReadLocalProbeResult::AtomicPending, nullptr, nullptr, state}')
    capture = replace_once(capture, 'if (!read_local_state_eligible(state))',
                           'if (!probeadapter_fault("accept-odd") && !read_local_state_eligible(state))')
    capture = replace_once(capture, 'if (!read_local_probe_sequence_equal(final_state, state))',
                           'if (!probeadapter_fault("accept-invalid") && !read_local_probe_sequence_equal(final_state, state))')
    capture = replace_once(capture, 'return {object ? ReadLocalProbeResult::Hit : ReadLocalProbeResult::Missing,\n                slot, object, state};',
                           'return {(object && !probeadapter_fault("hit-missing")) || probeadapter_fault("missing-hit")\n'
                           '                    ? ReadLocalProbeResult::Hit : ReadLocalProbeResult::Missing,\n'
                           '                probeadapter_fault("drop-slot") ? nullptr : slot, object, state};')
    header.write_text(text[:start] + capture + text[end:])
    checks = tree / 'tests/probeadapter_checks.h'
    text = checks.read_text()
    text = replace_once(text, 'witness.resize = true;', 'witness.resize = !probeadapter_fault("no-transition");')
    text = replace_once(text, '    f.store.foreign_read_scope_open(f.hash);',
                        '    if (!probeadapter_fault("no-pending-window")) f.store.foreign_read_scope_open(f.hash);')
    text = replace_once(text, '        auto guard = f.store.read_local_table_guard();',
                        '        std::optional<Store::ReadLocalTableGuard> guard;\n'
                        '        if (!probeadapter_fault("no-odd-window")) guard.emplace(f.store);')
    checks.write_text('#include <optional>\n' + text)
    # Use the actual Makefile commands and existing production objects. The three
    # instrumented test TUs link first, in their normal/db0 namespaces.
    commands = subprocess.check_output(['make', '-n', '-B', 'build/rehash-waits-unit', 'build/multidb-unit'], cwd=ROOT, text=True)
    wanted = {'build/rehash-waits-unit', 'build/tests/multidb_unit.o',
              'build/db0/tests/multidb_db0_unit.o', 'build/multidb-unit'}
    plans = []
    for line in commands.splitlines():
        argv = shlex.split(line)
        if not argv or argv[0] != 'g++' or '-o' not in argv:
            continue
        target = argv[argv.index('-o') + 1]
        if target not in wanted:
            continue
        for i, word in enumerate(argv):
            if word.startswith('build/'):
                argv[i] = str((tree if word in wanted else ROOT) / word)
        dest = tree / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        plans.append(dict(target=str(dest), argv=argv))
    assert len(plans) == 4
    makefile = ['all: ' + str(tree / 'build/rehash-waits-unit') + ' ' + str(tree / 'build/multidb-unit')]
    for p in plans:
        deps = [str(tree / name) for name in wanted if name.endswith('.o')] if p['target'].endswith('/multidb-unit') else []
        makefile += [p['target'] + ': ' + ' '.join(deps), '\t' + shlex.join(p['argv'])]
    (tree / 'controls.mk').write_text('\n'.join(makefile) + '\n')
    save(out / 'build-plan.json', plans)
    save(out / 'source-hashes.json', {str(p.relative_to(tree)): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in [header, checks]})


def run_controls():
    out = OUT / 'controls'
    tree = out / 'source'
    drivers = [('rehash', 'rehash-waits-unit', 'probeadapter'),
               ('multidb', 'multidb-unit', '--probeadapter-only'),
               ('db0', 'multidb-unit', '--probeadapter-db0-only')]
    faults = {
        'legacy': 'capture entered exactly once',
        'no-entry': 'capture entered exactly once',
        'no-walk': 'exact capture walk count',
        'drop-object': 'exact result/object/state projection',
        'drop-state': 'exact result/object/state projection',
        'disabled-missing': 'exact capture walk count',
        'pending-missing': 'exact capture walk count',
        'accept-odd': 'exact semantic result/object/state',
        'accept-invalid': 'invalid topology returns Churn/null/current state',
        'hit-missing': 'exact semantic result/object/state',
        'missing-hit': 'exact semantic result/object/state',
        'drop-slot': 'capture retains deciding slot only after a walk',
        'no-transition': 'real resize entered within 128 insertions',
        'no-pending-window': 'unsafe-key window entered',
        'no-odd-window': 'odd topology window entered',
    }
    rows = []
    env = dict(os.environ)
    env.pop('PROBEADAPTER_FAULT', None)
    for driver, binary, selection in drivers:
        path = tree / 'build' / binary
        for fault in [None, *faults]:
            label = driver + '-' + (fault or 'positive')
            result = subprocess.run([str(path), selection], env=dict(env, **({'PROBEADAPTER_FAULT': fault} if fault else {})),
                                    capture_output=True, text=True, timeout=60)
            (out / (label + '.log')).write_text(result.stdout + result.stderr)
            assert result.returncode == (1 if fault else 0), (label, result.returncode, result.stderr)
            if fault:
                assert 'FAIL probeadapter ' in result.stderr and faults[fault] in result.stderr, (label, result.stderr)
            rows.append(dict(driver=driver, fault=fault, exit=result.returncode, assertion=result.stderr.strip(),
                             binary_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    save(out / 'results.json', rows)


if __name__ == '__main__':
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['source', 'elf-controls', 'generate', 'run-controls'])
    args = parser.parse_args()
    {'source': source, 'elf-controls': elf_controls, 'generate': generate, 'run-controls': run_controls}[args.command]()
    print('PASS', args.command)
