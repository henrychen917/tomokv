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
    root = Path(root)
    removed = ('Targeted' + 'Ifid', 'SuppressOrdinary' + 'ActiveMark',
               'mark_active_' + 'known', 'multi_dispatch_entry_' + 'iofused',
               'multi_owner_pass_entry_' + 'iofused')
    hits = []
    for path in sorted((root / 'src').rglob('*')):
        if path.suffix not in ('.h', '.cc', '.inc'):
            continue
        for line, text in enumerate(path.read_text().splitlines(), 1):
            if any(re.search(r'\b' + name + r'\b', text) for name in removed):
                hits.append((str(path.relative_to(root)), line, text))
    assert not hits, ('removed IO interface reintroduced', hits)
    for filename in ('src/core/io_loop.h', 'src/core/reorder.cc'):
        text = (root / filename).read_text()
        # The similarly named live executor and MULTI implementation templates
        # are intentionally outside the IO parser's interface/body.
        for match in re.finditer(r'(?:DispatchResult|IoLoop::DispatchResult) '
                                r'(?:IoLoop::)?(?:r7_)?parse_and_dispatch\(', text):
            start = text.rfind('template <', 0, match.start())
            end = text.find('\n    uint32_t flush_ifid_posts', match.end())
            if filename.endswith('reorder.cc'):
                end = text.find('\nvoid IoLoop::run_fused_reordered', match.end())
            interface = text[start:text.find(')', match.end()) + 1]
            assert 'IofusedPrivateQueue' not in interface, 'removed private-queue IO parameter'
    return dict(okay=True, removed=list(removed), scope='all production C++ source')


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
    files = ['src/core/io_loop.h', 'src/core/reorder.cc',
             'tests/reorder_engagement_unit.cc', 'tests/core_concurrency_unit.cc']
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
template <bool Fused, bool SplitLocal, bool IoPipe, bool NoBorrow,
          uint32_t BatchOps, uint32_t B> consteval bool callers() {
    constexpr bool TargetedIfid=false, SuppressOrdinaryActiveMark=false, IofusedPrivateQueue=false;
ASSERTIONS
    return true;
}
'''.replace('OLD_FUSED', old_fused).replace('NEW_FUSED', new_fused).replace(
        'OLD_CODED', old_coded).replace('NEW_CODED', new_coded).replace('ASSERTIONS', '\n'.join(assertions))
    for booleans in itertools.product(('false', 'true'), repeat=4):
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
         callers=rows, context_combinations=64, namespaces=logs,
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
                 'IofusedPrivateQueue', 'multi_dispatch_entry_' + 'iofused',
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


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('source', 'policies', 'source-controls', 'identity', 'elf-controls'))
    args = parser.parse_args()
    if args.command == 'source':
        save(OUT / 'removal-inventory.json', removal_inventory(ROOT))
    elif args.command == 'policies':
        policies()
    elif args.command == 'source-controls':
        source_controls()
    elif args.command == 'elf-controls':
        elf_controls()
    else:
        result = compare_arms(OUT / 'PRE', OUT / 'POST')
        save(OUT / 'identity.json', result)
        print(sum(row['okay'] for row in result['rows']), '/', len(result['rows']), 'identical ELFs')
        return 0 if result['okay'] else 1
    print('PASS', args.command)
    return 0


if __name__ == '__main__':
    sys.exit(main())
