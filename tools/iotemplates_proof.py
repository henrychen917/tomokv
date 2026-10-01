#!/usr/bin/env python3
"""Offline IO-interface proofs. Never starts a server or measures an ELF arm.

Run builds and checks under taskset -c 112-127. PRE is the merged launch reference,
not the older staging commit. The ELF verdict uses unmodified section bytes.
"""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile

from ttlstate_proof import capture, compare_arms, compare_files, save
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cleanup-iotemplates'
BASE = '2a9e484035960b0ba5925824cc581148c359c0f8'
CALL = re.compile(r'\b((?:r7_)?parse_and_dispatch)\s*<([^>]*)>\s*\(')


def run(argv, log, cwd=ROOT, expected=0):
    result = subprocess.run(list(map(str, argv)), cwd=cwd, capture_output=True, text=True)
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    Path(log).write_text(result.stdout + result.stderr)
    assert result.returncode == expected, (argv, result.returncode, str(log))
    return result.stdout + result.stderr


def reference(path):
    return subprocess.check_output(['git', 'show', BASE + ':' + path], cwd=ROOT, text=True)


def removal_inventory(root):
    sys.path.insert(0, str(ROOT / 'tests'))
    from r7shadow_sync import removal_inventory as check
    return check(root)


def parser_calls(text):
    # Newly added fixture calls have their own runtime witnesses; compare the
    # complete original caller inventory without letting them shift ordinals.
    if '    static void io_dispatch_membership(' in text:
        a = text.index('    // The ordinary and generated parsers must retain')
        b = text.index('    template <bool ReadLocal>\n    static void shadow_pipes', a)
        text = text[:a] + text[b:]
    return [(m[1], [s.strip() for s in m[2].split(',')]) for m in CALL.finditer(text)]


def policies(root=ROOT, destination=None, negative=False):
    root = Path(root)
    destination = Path(destination or OUT / 'policies')
    destination.mkdir(parents=True, exist_ok=True)
    found = subprocess.check_output(['git', 'grep', '-l', 'parse_and_dispatch', BASE, '--', 'src', 'tests'],
                                    cwd=ROOT, text=True).splitlines()
    files = [p.split(':', 1)[1] for p in found if Path(p).suffix in ('.h', '.cc', '.inc')]
    rows, assertions = [], []
    for path in files:
        old, new = parser_calls(reference(path)), parser_calls((root / path).read_text())
        assert len(old) == len(new), ('parser caller inventory changed', path, len(old), len(new))
        for index, ((before, a), (after, b)) in enumerate(zip(old, new)):
            assert before == after
            if len(a) > 3:
                assert len(a) == 7
                assert a[3:6] in (['false'] * 3,
                    ['TargetedIfid', 'SuppressOrdinaryActiveMark', 'IofusedPrivateQueue'])
            label = f'{path} caller {index} {before}: Fused/SplitLocal/Coded and transport policies'
            assertions.append('static_assert(pre<' + ','.join(a) + '>() == post<' +
                              ','.join(b) + '>(), ' + json.dumps(label) + ');')
            rows.append(dict(path=path, ordinal=index, method=before, pre=a, post=b))
    old = reference('src/core/io_loop.h')
    new = (root / 'src/core/io_loop.h').read_text()
    formula = lambda text: re.search(r'static constexpr bool Fused = ([\s\S]*?);', text)[1]
    old_fused, new_fused = formula(old), formula(new)
    # These are the real ROB acquisition policies, not an invented coded-reply model.
    old_coded = re.search(r': rob.acquire<([^>]+)>', old)[1]
    new_coded = re.search(r': rob.acquire<([^>]+)>', new)[1]
    assert 'op = rob.acquire<false>' in old and 'op = rob.acquire<false>' in new
    source = '''#include <array>
#include "src/core/genthread_pipeline.h"
using namespace tomo;
template <bool NoBorrow, uint32_t BatchOps=0, bool IoPipe=false,
          bool TargetedIfid=false, bool SuppressOrdinaryActiveMark=false,
          bool IofusedPrivateQueue=false, bool SplitLocal=false>
consteval auto pre() {
    constexpr bool Fused = OLD_FUSED;
    return std::array<unsigned, 6>{NoBorrow, BatchOps, IoPipe, SplitLocal,
                                   Fused, Fused && (OLD_CODED)};
}
template <bool NoBorrow, uint32_t BatchOps=0, bool IoPipe=false, bool SplitLocal=false>
consteval auto post() {
    constexpr bool Fused = NEW_FUSED;
    return std::array<unsigned, 6>{NoBorrow, BatchOps, IoPipe, SplitLocal,
                                   Fused, Fused && (NEW_CODED)};
}
template <bool Fused, bool SplitLocal, bool IoPipe, bool NoBorrow, bool ReadLocal,
          uint32_t BatchOps, uint32_t B> consteval bool callers() {
    constexpr bool TargetedIfid=false, SuppressOrdinaryActiveMark=false, IofusedPrivateQueue=false;
ASSERTIONS
    return true;
}
'''.replace('OLD_FUSED', old_fused).replace('NEW_FUSED', new_fused).replace(
        'OLD_CODED', old_coded).replace('NEW_CODED', new_coded).replace('ASSERTIONS', '\n'.join(assertions))
    for booleans in itertools.product(('false', 'true'), repeat=5):
        for batch, b in itertools.product(('0', 'kGenthreadIfidBatchOps'), repeat=2):
            source += 'static_assert(callers<' + ','.join((*booleans, batch, b)) + '>());\n'
    witness = destination / 'policies.cc'
    witness.write_text(source)
    logs = []
    for namespace in ('normal', 'db0'):
        argv = ['g++', '-std=c++20', '-fsyntax-only', '-I' + str(ROOT)]
        if namespace == 'db0':
            argv += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        log = run(argv + [witness], destination / (namespace + '.log'), expected=1 if negative else 0)
        if negative:
            assert 'static assertion failed' in log and 'Fused/SplitLocal/Coded' in log
        logs.append(namespace)
    # All transport/boot and writeback policy sites are unchanged, including the
    # explicitly deferred park defect. Compare every occurrence, not 16 selected sites.
    preserved = r'\b((?:r7_)?(?:run_loop|epoll_pass|on_cqe|flush_ready|wb_retire_prepare|wb_serve_natural))\s*<([^>]*)>'
    for filename in ('src/core/io_loop.h', 'src/core/reorder.cc', 'src/core/genthread.cc', 'src/core/rl2s.cc'):
        a = re.findall(preserved, reference(filename))
        b = re.findall(preserved, (root / filename).read_text())
        assert a == b, ('boot/transport/Fused/SplitLocal/Coded policy sites changed', filename)
    save(destination / 'result.json', dict(okay=True, negative_rejected=negative,
         callers=rows, context_combinations=128, namespaces=logs,
         ordinary_park='epoll_pass<HasUnix, HasTls, !SplitLocal, Pipeline>(50)',
         claim='real source call arguments and Fused/ROB expressions compile equal to frozen PRE'))


def source_controls():
    out = OUT / 'source-controls'
    tree = out / 'tree'
    tree.mkdir(parents=True, exist_ok=True)
    for directory in ('src', 'tests', 'tools'):
        shutil.copytree(ROOT / directory, tree / directory, dirs_exist_ok=True)
    results = []
    removal_inventory(tree)
    header = tree / 'src/core/io_loop.h'
    original = header.read_text()
    for name in ('Targeted' + 'Ifid', 'SuppressOrdinary' + 'ActiveMark',
                 'IofusedPrivateQueue', 'mark_active_' + 'known', 'multi_dispatch_entry_' + 'iofused',
                 'multi_owner_pass_entry_' + 'iofused'):
        if name == 'IofusedPrivateQueue':
            changed = original.replace('bool SplitLocal = false>\n    DispatchResult parse_and_dispatch',
                'bool IofusedPrivateQueue = false, bool SplitLocal = false>\n    DispatchResult parse_and_dispatch', 1)
        else:
            changed = original + '\nvoid ' + name + '();\n'
        assert changed != original
        header.write_text(changed)
        try:
            removal_inventory(tree)
        except AssertionError as error:
            results.append(dict(control=name, rejected=True, diagnostic=str(error)))
        else:
            raise AssertionError('removal inventory accepted ' + name)
        header.write_text(original)
    test = tree / 'tests/reorder_engagement_unit.cc'
    text = test.read_text()
    needle = 'parse_and_dispatch<false, 0, true, true>(&a)'
    assert text.count(needle) == 1
    test.write_text(text.replace(needle, 'parse_and_dispatch<false, 0, true, false, false, false, true>(&a)'))
    try:
        removal_inventory(tree)
    except AssertionError as error:
        assert 'obsolete IO call arity' in str(error)
        results.append(dict(control='restore old test call arity', rejected=True, diagnostic=str(error)))
    else:
        raise AssertionError('old test call arity was accepted')
    test.write_text(text.replace(needle, 'parse_and_dispatch<false, 0, true>(&a)'))
    policies(tree, out / 'dropped-splitlocal', negative=True)
    results.append(dict(control='drop true SplitLocal', rejected=True,
                        diagnostic='static assertion failed: Fused/SplitLocal/Coded and transport policies'))
    test.write_text(text)
    copied = tree / 'src/core/reorder.cc'
    text = copied.read_text()
    assert 'shadow_dispatch.stamp(t);' in text
    copied.write_text(text.replace('shadow_dispatch.stamp(t);', '(void)t;', 1))
    log = run(['python3', tree / 'tests/r7shadow_sync.py'], out / 'manual-copy.log', cwd=tree, expected=1)
    assert 'stale R7 envelope' in log
    results.append(dict(control='manually altered generated stamp body', rejected=True,
                        diagnostic='stale R7 envelope'))
    copied.write_text(text)
    run(['python3', tree / 'tests/r7shadow_sync.py'], out / 'current-copy.log', cwd=tree)
    save(out / 'results.json', results)


def elf_controls():
    out = OUT / 'elf-controls'
    out.mkdir(exist_ok=True)
    rows = []
    for label, path, kind in [
            ('linked-byte', OUT / 'POST/artifacts/tomokv', 'byte'),
            ('subsection-byte', OUT / 'POST/artifacts/src/core/genthread.o', 'subsection'),
            ('relocation', OUT / 'POST/artifacts/src/core/genthread.o', 'relocation'),
            ('function-address', OUT / 'POST/artifacts/tomokv', 'address')]:
        elf = Elf(path)
        data = bytearray(elf.data)
        if kind in ('byte', 'subsection'):
            i = next(i for i, (s, n) in enumerate(zip(elf.sections, elf.names))
                     if s[2] & 4 and s[5] and (n == '.text' if kind == 'byte' else n.startswith('.text.')))
            data[elf.sections[i][4]] ^= 1
            expected = f'executable {elf.names[i]}: bytes differ'
        elif kind == 'relocation':
            s = next(s for s in elf.sections if s[1] == 4 and s[5] and
                     s[7] < len(elf.sections) and elf.sections[s[7]][2] & 4)
            at = s[4] + 16
            struct.pack_into('<q', data, at, struct.unpack_from('<q', data, at)[0] + 1)
            expected = 'allocated relocation targets differ'
        else:
            t, i = next((t, i) for t, syms in elf.tables.items() for i, s in enumerate(syms)
                        if s['info'] & 15 == 2 and s['size'] and 0 < s['sec'] < len(elf.sections)
                        and elf.sections[s['sec']][2] & 4)
            at = elf.sections[t][4] + i * elf.sections[t][9] + 8
            struct.pack_into('<Q', data, at, struct.unpack_from('<Q', data, at)[0] + 1)
            expected = 'allocated symbol addresses/identities differ'
        mutant = out / (label + '.NEVER-RUN')
        mutant.write_bytes(data)
        mutant.chmod(0o600)
        result = compare_files(path, mutant)
        assert not result['okay'] and expected in result['errors'], result
        save(out / (label + '.json'), result)
        rows.append(dict(control=label, rejected=True, diagnostic=expected, executed=False))
    save(out / 'results.json', rows)


def fixture_build(tree, objects_arm, output, db0=False, reorder_object=None):
    rows = json.loads((OUT / 'frozen/object-inventory.json').read_text())
    prefix = 'build/db0/' if db0 else 'build/src/'
    objects = [OUT / objects_arm / 'artifacts' / Path(row['object']).relative_to('build')
               for row in rows if row['source'] != 'src/main.cc' and
               (db0 or row['object'].startswith(prefix))]
    # DB0 library order is the same as the production test target.
    if db0:
        objects.sort(key=lambda p: (0 if '/db0/' in str(p) else 1, str(p)))
    if reorder_object:
        objects = [p for p in objects if not str(p).endswith('/src/core/reorder.o')]
        objects.insert(0, reorder_object)
    argv = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native',
            '-pthread', '-DTOMO_JEMALLOC', '-I.']
    if db0:
        argv += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
    argv += ['tests/reorder_engagement_unit.cc', *map(str, objects), '-o', str(output),
             '-ljemalloc', '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
    run(argv, str(output) + '-build.log', cwd=tree)


def controls():
    out = OUT / 'runtime-controls'
    tree = out / 'source'
    tree.mkdir(parents=True, exist_ok=True)
    for directory in ('src', 'tests'):
        shutil.copytree(ROOT / directory, tree / directory, dirs_exist_ok=True)
    if not (tree / 'third_party').exists():
        (tree / 'third_party').symlink_to(ROOT / 'third_party', target_is_directory=True)
    header = tree / 'src/core/io_loop.h'
    text = header.read_text()
    text = text.replace('namespace tomo {', '''namespace tomo {
inline bool iotemplates_fault(const char* name) {
    const char* selected = std::getenv("IOTEMPLATES_FAULT");
    return selected && std::strcmp(selected, name) == 0;
}
''', 1)
    needle = '            touch_worker(worker_id);\n            mark_active(c);'
    assert text.count(needle) == 1
    text = text.replace(needle, '            touch_worker(worker_id);\n'
                        '            if (!iotemplates_fault("omit-dispatch-mark")) mark_active(c);')
    needle = '            conn.advance_parse(consumed);\n            sig.ops++;\n            flip_fingerprint_note'
    assert text.count(needle) == 1
    text = text.replace(needle, '            if (!iotemplates_fault("omit-advance")) conn.advance_parse(consumed);\n'
                        '            sig.ops++;\n            flip_fingerprint_note')
    needle = '            return owner.post_task_quiet(self_id, task, sig);'
    assert text.count(needle) == 1
    text = text.replace(needle, '            return iotemplates_fault("omit-owner-post") ||\n'
                        '                   owner.post_task_quiet(self_id, task, sig);')
    start = text.index('    void fused_executor_completion(')
    end = text.index('\n    }', start)
    body = text[start:end].replace('enqueue_serve(client);',
                                  'if (!iotemplates_fault("omit-serve")) enqueue_serve(client);')
    body = body.replace('!client || client->dead()',
                        '!client || (!iotemplates_fault("admit-dead-serve") && client->dead())')
    text = text[:start] + body + text[end:]
    start = text.index('    void mark_active(Client* c) {')
    end = text.index('\n    }', start)
    body = text[start:end].replace('if (c->dead())', 'if (!iotemplates_fault("admit-dead") && c->dead())')
    body = body.replace('if (c->in_active())', 'if (!iotemplates_fault("duplicate-active") && c->in_active())')
    text = text[:start] + body + text[end:]
    header.write_text(text)
    driver = tree / 'tests/reorder_engagement_unit.cc'
    text = driver.read_text()
    assert text.count('const uint32_t prefix = wire.size() - 1;') == 1
    text = text.replace('const uint32_t prefix = wire.size() - 1;',
        'const uint32_t prefix = wire.size() - (iotemplates_fault("unentered-frame") ? 0 : 1);')
    start = text.index('    static void io_dispatch_membership(')
    end = text.index('    static void io_dispatch_membership_all()', start)
    body = text[start:end].replace('require(f.loop.self_->post_task_quiet(',
                                   'require(!iotemplates_fault("refuse-requeue") && f.loop.self_->post_task_quiet(')
    body = body.replace('require(f.drain() == 1',
                        'require((iotemplates_fault("omit-owner-drain") ? 0 : f.drain()) == 1')
    body = body.replace('client.rob().drain([](Op&) {}) == 1',
                        '(iotemplates_fault("omit-retire") ? 0 : client.rob().drain([](Op&) {})) == 1')
    driver.write_text(text[:start] + body + text[end:])
    binary = out / 'membership-controls'
    fixture_build(tree, 'POST', binary)
    run([binary, 'on', 'shadow'], out / 'positive.log')
    rows = []
    for fault, message in (
            ('omit-dispatch-mark', 'iotemplates dispatched frame has active membership'),
            ('admit-dead', 'iotemplates dead client never enters active or serve set'),
            ('admit-dead-serve', 'iotemplates dead client never enters active or serve set'),
            ('duplicate-active', 'iotemplates active membership is deduplicated'),
            ('omit-serve', 'iotemplates active membership is deduplicated'),
            ('omit-advance', 'iotemplates completed frame made parser progress'),
            ('omit-owner-post', 'iotemplates completed frame posted exactly one owner task'),
            ('refuse-requeue', 'iotemplates requeue owner task'),
            ('omit-owner-drain', 'iotemplates owner progress and ordered retirement'),
            ('omit-retire', 'iotemplates owner progress and ordered retirement'),
            ('unentered-frame', 'iotemplates incomplete frame entered without dispatch or active membership')):
        result = subprocess.run([str(binary), 'iotemplates'], capture_output=True, text=True,
                                env=dict(os.environ, IOTEMPLATES_FAULT=fault))
        (out / (fault + '.log')).write_text(result.stdout + result.stderr)
        expected = 'FAIL R7 engagement: ' + message
        assert result.returncode == 1 and expected in result.stderr, (fault, result.returncode, result.stderr)
        rows.append(dict(control=fault, exit=1, exact_failure=expected))
    generated = tree / 'src/core/reorder.cc'
    text = generated.read_text()
    assert text.count('shadow_dispatch.stamp(t);') == 1
    generated.write_text(text.replace('shadow_dispatch.stamp(t);', '(void)t;'))
    obj = out / 'no-stamp.o'
    argv = next(row['argv'] for row in json.loads((OUT / 'frozen/object-inventory.json').read_text())
                if row['object'] == 'build/src/core/reorder.o')[:]
    argv[argv.index('-o') + 1] = str(obj)
    run(argv, out / 'no-stamp-build.log', cwd=tree)
    stamped = out / 'no-stamp-unit'
    fixture_build(tree, 'POST', stamped, reorder_object=obj)
    log = run([stamped, 'on', 'shadow'], out / 'no-stamp.log', expected=1)
    expected = 'FAIL R7 engagement: dispatch shadow stamp count/PAD/FIFO witness'
    assert expected in log
    rows.append(dict(control='omit real generated shadow stamp', exit=1, exact_failure=expected))
    save(out / 'results.json', rows)


def arm_fixtures(arm):
    out = OUT / (arm + '-fixtures')
    tree = out / 'source'
    tree.mkdir(parents=True, exist_ok=True)
    with tarfile.open(OUT / 'frozen/reference.tar') as archive:
        archive.extractall(tree, filter='data')
    # PAD A retains the original false arms with the new interface; PAD B uses
    # the inversely restored interface. Compile each fixture against its arm.
    if arm.startswith('PAD-'):
        shutil.copytree(OUT / (arm + '-source/src'), tree / 'src', dirs_exist_ok=True)
    text = (ROOT / 'tests/reorder_engagement_unit.cc').read_text()
    if arm in ('PRE', 'PAD-B'):
        def restore(match):
            args = [s.strip() for s in match[2].split(',')]
            if len(args) == 4:
                args = args[:3] + ['false', 'false', 'false', args[3]]
            return match[1] + '<' + ', '.join(args) + '>('
        text = CALL.sub(restore, text)
        text = text.replace('io.fused_executor_completion(', 'io.fused_executor_completion<false>(')
    (tree / 'tests/reorder_engagement_unit.cc').write_text(text)
    for db0 in (False, True):
        binary = out / ('engagement-db0' if db0 else 'engagement')
        fixture_build(tree, arm, binary, db0=db0)
        run([binary, 'on', 'shadow'], str(binary) + '.log')
    save(out / 'results.json', dict(okay=True, arm=arm, namespaces=['normal', 'db0'],
                                   interface_adapter_only=arm in ('PRE', 'PAD-B')))


def pad(kind):
    """Source controls, never executable patching or an unrelated R7 PAD.

    A constant-propagates PRE's inventoried false arguments while retaining its
    dead constexpr arms. Uncalled wrappers become inline (no emitted roots).
    B inversely restores precisely the removed compile-time residue to POST;
    those false parameters/dead functions are source padding, with PRE layout.
    Both must pass their complete layout/byte comparison after the build.
    """
    arm = 'PAD-' + kind
    source = OUT / (arm + '-source')
    source.mkdir(exist_ok=True)
    if kind == 'A':
        with tarfile.open(OUT / 'frozen/reference.tar') as archive:
            archive.extractall(source, filter='data')
        header = source / 'src/core/io_loop.h'
        text = header.read_text()
        text = text.replace('    template <bool TargetedIfid>\n    void fused_executor_completion',
                            '    void fused_executor_completion')
        text = text.replace('bool HasUnix, bool kEp, bool TargetedIfid = false', 'bool HasUnix, bool kEp')
        text = text.replace('              bool TargetedIfid = false,\n'
                            '              bool SuppressOrdinaryActiveMark = false,\n'
                            '              bool IofusedPrivateQueue = false, bool SplitLocal = false>',
                            '              bool SplitLocal = false>')
        text = re.sub(r'mark_active_known<[^>]+>', 'mark_active', text)
        text = text.replace('0, true, false, false, false, SplitLocal>', '0, true, SplitLocal>')
        text = text.replace('fused_executor_completion<false>', 'fused_executor_completion')
        start = text.index('    DispatchResult parse_and_dispatch(')
        end = text.index('    uint32_t flush_ifid_posts()', start)
        body = text[start:end]
        for name in ('TargetedIfid', 'SuppressOrdinaryActiveMark', 'IofusedPrivateQueue'):
            body = re.sub(r'\b' + name + r'\b', 'false', body)
        text = text[:start] + body + text[end:]
        header.write_text(text)
        for name in ('src/core/genthread.cc', 'src/core/rl2s.cc'):
            path = source / name
            path.write_text(path.read_text().replace('fused_executor_completion<false>', 'fused_executor_completion'))
        for name in ('src/cmd/multi.h', 'src/cmd/multi.inc'):
            path = source / name
            path.write_text(re.sub(r'^(bool|uint32_t) (multi_(?:dispatch|owner_pass)_entry_iofused\()',
                                   r'inline \1 \2', path.read_text(), flags=re.M))
        generator = source / 'tests/r7shadow_sync.py'
        generator.write_text(generator.read_text().replace(
            'return parse_and_dispatch<NoBorrow, BatchOps, IoPipe, TargetedIfid,\n'
            '            SuppressOrdinaryActiveMark, IofusedPrivateQueue, SplitLocal>(c);',
            'return parse_and_dispatch<NoBorrow, BatchOps, IoPipe, SplitLocal>(c);'))
        run(['python3', 'tests/r7shadow_sync.py', '--write'], OUT / (arm + '-generate.log'), cwd=source)
        expected = 'POST'
    else:
        # An exact inverse mechanical substitution, retained as a patch receipt.
        archive = OUT / 'POST-source.tar'
        with archive.open('wb') as target:
            subprocess.run(['git', 'archive', '5bd61cca9'], cwd=ROOT, stdout=target, check=True)
        with tarfile.open(archive) as tar:
            tar.extractall(source, filter='data')
        patch = subprocess.check_output(['git', 'diff', BASE, '5bd61cca9', '--', 'src', 'tests/r7shadow_sync.py'], cwd=ROOT)
        (OUT / 'PAD-B-inverse.patch').write_bytes(patch)
        subprocess.run(['patch', '-p1', '-R'], input=patch, cwd=source, check=True, stdout=subprocess.PIPE)
        # Bind the inverse to every PRE production source, not a size guess.
        for path in (source / 'src').rglob('*'):
            if path.is_file():
                assert path.read_text() == reference(str(path.relative_to(source)))
        expected = 'PRE'
    inventory = json.loads((OUT / 'frozen/object-inventory.json').read_text())
    commands = []
    for row in inventory:
        dest = source / row['object']
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OUT / 'PRE/artifacts' / Path(row['object']).relative_to('build'), dest)
        if any(Path(p).name in ('io_loop.h', 'multi.h', 'multi.inc') for p in row['dependencies']):
            commands.append((row['object'], row['argv']))
    makefile = source / 'pad-build.mk'
    makefile.write_text('all: ' + ' '.join(p for p, _ in commands) + '\n.PHONY: all\n' +
                       ''.join(p + ':\n\t' + shlex.join(argv) + ' > ' + p + '.log 2>&1\n'
                               for p, argv in commands))
    run(['make', '-B', '-j16', '-f', 'pad-build.mk'], OUT / (arm + '-build.log'), cwd=source)
    link = next(line for line in (OUT / 'frozen/make-dry-run.txt').read_text().splitlines()
                if line.startswith('g++ ') and ' -o build/tomokv ' in line and ' -c ' not in line)
    run(shlex.split(link), OUT / (arm + '-link.log'), cwd=source)
    save(OUT / (arm + '-source-proof.json'), dict(kind=kind, base=BASE, rebuilt=commands,
         source=str(source), behavior='PRE false policies, unchanged live arms' if kind == 'A' else
         'POST behavior with the exact deleted, uninstantiated source residue restored',
         expected_layout=expected, executable_patch=False, nop_footer=False))
    previous = Path.cwd()
    try:
        os.chdir(source)
        capture(OUT / 'frozen/object-inventory.json', OUT / arm, [])
    finally:
        os.chdir(previous)
    result = compare_arms(OUT / arm, OUT / expected)
    save(OUT / ('identity-' + arm + '-' + expected + '.json'), result)
    assert result['okay'], arm + ' has no matched layout yet; inspect the raw failures'


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('source', 'policies', 'source-controls', 'identity', 'elf-controls',
                                          'pad-a', 'pad-b', 'controls', 'pre-fixtures', 'pad-a-fixtures', 'pad-b-fixtures'))
    args = parser.parse_args()
    if args.command == 'source':
        save(OUT / 'removal-inventory.json', removal_inventory(ROOT))
    elif args.command == 'policies':
        policies()
    elif args.command == 'source-controls':
        source_controls()
    elif args.command == 'elf-controls':
        elf_controls()
    elif args.command in ('pad-a', 'pad-b'):
        pad(args.command[-1].upper())
    elif args.command == 'controls':
        controls()
    elif args.command.endswith('-fixtures'):
        arm_fixtures(args.command.removesuffix('-fixtures').upper())
    else:
        result = compare_arms(OUT / 'PRE', OUT / 'POST')
        save(OUT / 'identity.json', result)
        print(sum(row['okay'] for row in result['rows']), '/', len(result['rows']), 'identical ELFs')
        return 0 if result['okay'] else 1
    print('PASS', args.command)
    return 0


if __name__ == '__main__':
    sys.exit(main())
