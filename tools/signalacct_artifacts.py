#!/usr/bin/env python3
"""Prepare isolated IO accounting controls and audit ELF identities; never run servers.

The exact-layout kind-A pair contains generated PRE and POST IO envelopes. A cold
role-entry selector chooses POST; patching only its return immediate selects PRE.
Both arms have identical sections, symbols, relocations and all other bytes.
This pair is an additional control: the ordinary release POST remains a separate arm.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lbstall_artifacts import Elf
ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / 'build/signalacct-pre'
OUT = ROOT / 'build/signalacct-proof'
sys.path.insert(0, str(ROOT / 'tests'))
import r7shadow_sync as sync


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after, 1)


def tree(name):
    dest = ROOT / 'build' / name
    dest.mkdir(parents=True, exist_ok=True)
    for directory in ('src', 'third_party', 'tests', 'tools'):
        shutil.copytree(ROOT / directory, dest / directory, dirs_exist_ok=True)
    shutil.copyfile(ROOT / 'Makefile', dest / 'Makefile')
    return dest


def legacy(body):
    # Preserve the frozen PRE work Span and every original start_ns consumer.
    # Add only independent, cold tenure endpoint evidence; do not book extra busy.
    original = body
    body = once(body, '    LoopSignals& sig = self_->sig();\n', '')
    marker = '    constexpr bool IoPipe = (!Fused || SplitLocal) && Pipeline == 1;'
    body = once(body, marker, '    LoopSignals& sig = self_->sig();\n    IoTenure tenure(sig);\n' + marker)
    marker = '    if constexpr (Fused) {\n        // The read loop is over for this tenure.'
    insertion = ('    const auto io_tenure = tenure.finish(self_->role() != Role::Ifid,\n'
                 '        self_->stop_flag().load(std::memory_order_relaxed), false);\n')
    body = once(body, marker, insertion + marker)
    body = once(body, '    // A close requested by the last pass',
                '    io_tenures_.push_back(io_tenure);\n    // A close requested by the last pass')
    # Reversal proves the PRE envelope is copied, not reconstructed by hand.
    restored = body.replace(insertion, '').replace('    IoTenure tenure(sig);\n', '').replace('    io_tenures_.push_back(io_tenure);\n', '')
    restored = once(restored, '    LoopSignals& sig = self_->sig();\n', '')
    restored = once(restored, '    // The disarmed specialization',
                    '    LoopSignals& sig = self_->sig();\n    // The disarmed specialization')
    assert restored == original
    return body


def optional_finish(dest):
    p = dest / 'src/core/signalacct.h'
    s = once(p.read_text(), 'finish(bool role_exit, bool stopped)',
             'finish(bool role_exit, bool stopped, bool book = true)')
    p.write_text(once(s, '        account(end);', '        if (book) account(end);'))


def prepare_pair():
    dest = tree('signalacct-pair')
    optional_finish(dest)
    p = dest / 'src/core/io_loop.h'
    s = p.read_text()
    old = legacy(sync.function((PRE / 'src/core/io_loop.h').read_text(), 'run_loop'))
    old = once(old, 'void run_loop()', 'void signalacct_legacy_run_loop()')
    current = sync.function(s, 'run_loop')
    opening = current.index('{') + 1
    patched = current[:opening] + '''
    if (!signalacct_candidate())
        return signalacct_legacy_run_loop<HasUnix, HasTls, kEp, Fused, Pipeline, SplitLocal>();
''' + current[opening:]
    indented = lambda t: '\n'.join(line if line.startswith('#') else '    ' + line if line else '' for line in t.splitlines())
    s = once(s, indented(current), indented(old) + '\n\n' + indented(patched))
    s = once(s, '#include "signalacct.h"', '#include "signalacct.h"\n#include "signalacct_selector.h"')
    declaration = '''    template <bool HasUnix, bool HasTls, bool kEp, bool Fused = false,
              uint8_t Pipeline = 0, bool SplitLocal = false>
    void r7_signalacct_legacy_run_loop();
'''
    s = once(s, '    void run_fused_reordered();', declaration + '    void run_fused_reordered();')
    p.write_text(s)
    (dest / 'src/core/signalacct_selector.h').write_text('''#pragma once
namespace tomo {
__attribute__((noinline, noclone, noipa, used)) inline bool signalacct_candidate() { return true; }
}
''')
    p = dest / 'tests/r7shadow_sync.py'
    p.write_text(once(p.read_text(), "        names = {name: 'r7_' + name for name in methods}",
                     "        names = {name: 'r7_' + name for name in methods}\n"
                     "        names['signalacct_legacy_run_loop'] = 'r7_signalacct_legacy_run_loop'"))
    subprocess.run([sys.executable, 'tests/r7shadow_sync.py', '--write'], cwd=dest, check=True)
    # Frozen armed envelope retains all R7 callees and shadow binding. It is generated
    # by the PRE synchronizer, not a handwritten alternate scheduler.
    old_r7 = legacy(sync.base.function((PRE / 'src/core/reorder.cc').read_text(), 'IoLoop::r7_run_loop', False))
    old_r7 = 'template <bool HasUnix, bool HasTls, bool kEp, bool Fused, uint8_t Pipeline, bool SplitLocal>\n' + once(old_r7, 'IoLoop::r7_run_loop()', 'IoLoop::r7_signalacct_legacy_run_loop()')
    p = dest / 'src/core/reorder.cc'
    marker = '// BEGIN R7 GENERATED ENVELOPES'
    p.write_text(once(p.read_text(), marker, old_r7 + '\n\n' + marker))
    subprocess.run([sys.executable, 'tests/r7shadow_sync.py'], cwd=dest, check=True)
    (OUT / 'pair-source.json').write_text(json.dumps(dict(
        kind='A: PRE IO work-span behaviour with paired POST text size/layout',
        reference=(OUT / 'reference.txt').read_text().strip(),
        pre_body_sha256=hashlib.sha256(sync.function((PRE / 'src/core/io_loop.h').read_text(), 'run_loop').encode()).hexdigest(),
        pre_r7_body_sha256=hashlib.sha256(sync.base.function((PRE / 'src/core/reorder.cc').read_text(), 'IoLoop::r7_run_loop', False).encode()).hexdigest(),
        reversal_exact=True, extra_clocks='four cold endpoint cuts per IO tenure in both arms',
        limitation='Pair has both generated envelopes and a cold selector. Also measure release POST; do not call pair byte-identical to release.'), indent=2) + '\n')
    return dest


def prepare_witness():
    dest = tree('signalacct-witness')
    p = dest / 'src/core/signalacct.h'
    s = p.read_text().replace('#pragma once', '#pragma once\n#define TOMO_SIGNALACCT_WITNESS 1', 1)
    s = once(s, '    void did_submit()', '    bool prime_sweep() const { return record_.sweep_submit == 0; }\n    void did_submit()')
    p.write_text(s)
    p = dest / 'src/core/io_loop.h'
    s = p.read_text()
    start = s.index('                if constexpr (IoPipe) {\n                    if (__builtin_expect(!routing_forward_')
    end = s.index('                did += flip_control_pass<kEp>();', start)
    # Defer only the ordinary ready-service block until the real sweep gets work.
    # The sweep invokes the same service code and must itself return nonzero. No
    # synthetic did/sweep counter or forced tolerance can satisfy the live checker.
    s = s[:start] + '                if (!tenure.prime_sweep()) {\n' + s[start:end] + '                }\n' + s[end:]
    p.write_text(s)
    subprocess.run([sys.executable, 'tests/r7shadow_sync.py', '--write'], cwd=dest, check=True)
    return dest


def pair(post, pad):
    elf = Elf(post)
    data = bytearray(elf.data)
    patches = []
    for name, symbol in elf.functions().items():
        if not name.endswith('20signalacct_candidateEv'):
            continue
        section = elf.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3]
        body = elf.body(symbol)
        if body.startswith(b'\xf3\x0f\x1e\xfa'):
            offset += 4; body = body[4:]
        assert body == b'\xb8\x01\x00\x00\x00\xc3', (name, body.hex())
        data[offset + 1] = 0
        patches.append(dict(symbol=name, offset=offset + 1))
    assert len(patches) == 2, patches
    pad.write_bytes(data)
    pad.chmod(post.stat().st_mode)
    verify_pair(post, pad, patches)
    receipt = dict(kind='A: PRE IO work-span behaviour with paired POST text size/layout',
                   post=str(post.relative_to(ROOT)), pad=str(pad.relative_to(ROOT)),
                   post_sha256=sha(post), pad_sha256=sha(pad), patches=patches,
                   sections_symbols_relocations_equal=True, all_other_bytes_equal=True)
    # Corrupt a separate, NON-executable copy. Never launch it.
    corrupt = pad.with_name(pad.name + '.corrupt-never-run')
    changed = bytearray(data)
    text = elf.sections[elf.names.index('.text')]
    changed[text[4]] ^= 1
    corrupt.write_bytes(changed)
    corrupt.chmod(0o600)
    try:
        verify_pair(post, corrupt, patches)
    except AssertionError:
        receipt['executable_byte_negative_control'] = 'REJECTED (never executed)'
    else:
        raise AssertionError('byte checker accepted executable corruption')
    (OUT / 'pad-a.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


def verify_pair(post, pad, patches):
    a, b = Elf(post), Elf(pad)
    assert a.sections == b.sections and a.symbols == b.symbols and a.relocs == b.relocs
    expected = bytearray(a.data)
    for p in patches:
        assert expected[p['offset']] == 1
        expected[p['offset']] = 0
    assert b.data == expected, 'unexpected executable/data byte change outside selector'


def dump(binary, arm):
    for suffix, command in [('sections-relocations.txt', ['readelf', '-WSr']),
                            ('disassembly.txt', ['objdump', '-drwC'])]:
        with (OUT / (arm + '.' + suffix)).open('w') as log:
            subprocess.run(command + [str(binary)], stdout=log, check=True)
    elf = Elf(binary)
    return dict(arm=arm, path=str(binary.relative_to(ROOT)), sha256=sha(binary),
                text_bytes=elf.sections[elf.names.index('.text')][5])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare-pair', 'prepare-witness', 'pair', 'dump'])
    parser.add_argument('paths', nargs='*')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.action == 'prepare-pair':
        print(prepare_pair())
    elif args.action == 'prepare-witness':
        print(prepare_witness())
    elif args.action == 'pair':
        pair(Path(args.paths[0]).resolve(), Path(args.paths[1]).resolve())
    else:
        rows = [dump((ROOT / p).resolve(), Path(p).name) for p in args.paths]
        (OUT / 'arms.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
