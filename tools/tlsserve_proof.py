#!/usr/bin/env python3
"""Offline TLS staging proofs. Pin to 112-127. Never execute a production ELF.

Production arms are built at the same source/output paths and captured with
ttlstate_proof.py. Mutants below are generated serverless fixtures only.
"""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from lbstall_artifacts import Elf
from ttlstate_proof import compare_files, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cleanup-tlsserve'
FLAGS = ['-std=c++20', '-O1', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
         '-DTOMO_JEMALLOC']
LIBS = ['-luring', '-ljemalloc', '-lssl', '-lcrypto']
DRIVER = '''#include "tests/tlsserve_checks.inc"
// Clients in this fixture never own a MULTI session. Unexpected use fails.
namespace tomo { void multi_session_destroy(MultiSession* p) { if (p) std::abort(); } }
int main() { tlsserve_test::run(); }
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source():
    # Multi-character operators and string/character literals remain indivisible.
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
                        r'[A-Za-z_][A-Za-z_0-9]*|[0-9][A-Za-z_0-9.]*|'
                        r'>>=|<<=|->\*|\.\.\.|::|->|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||'
                        r'\+=|-=|\*=|/=|%=|&=|\|=|\^=|\.\*|##|[^\s]')
    rows = []
    for variant in ('normal', 'db0'):
        post = OUT / f'wb-{variant}-post.ii'
        cmd = ['g++', '-std=c++20', '-DTOMO_JEMALLOC', '-I.', '-E', '-P', '-x', 'c++']
        if variant == 'db0':
            cmd += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        with (OUT / f'preprocess-{variant}.log').open('w') as log:
            subprocess.run(cmd + ['src/net/wb.h', '-o', str(post)], cwd=ROOT,
                           stderr=log, check=True)
        pre = OUT / f'freeze/wb-{variant}.ii'
        a, b = tokens.findall(pre.read_text()), tokens.findall(post.read_text())
        assert a == b, f'{variant}: expanded C++ tokens differ'
        rows.append(dict(variant=variant, equal=True, tokens=len(a),
                         token_sha256=hashlib.sha256('\n'.join(a).encode()).hexdigest()))
    save(OUT / 'expanded-tokens.json', rows)


def inventory():
    rows = json.loads((OUT / 'freeze/object-inventory.json').read_text())
    output = []
    for row in rows:
        item = dict(object=row['object'], source=row['source'], variant=row['variant'],
                    make_header_prerequisite=True, actual_includer=row['wb_includer'])
        variants = dict(plaintext=set(), no_borrow=set(), userspace_tls=set())
        if row['wb_includer']:
            relative = Path(row['object']).relative_to('build')
            obj = OUT / 'PRE/artifacts' / relative
            dest = OUT / 'instantiations' / relative.with_suffix('.txt')
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Include inlined instances that nm alone cannot see. Preserve raw matched DWARF
            # lines; full readelf symbols/relocations and objdump are in both arm captures.
            proc = subprocess.Popen(['readelf', '--debug-dump=info', str(obj)],
                                    stdout=subprocess.PIPE, text=True)
            with dest.open('w') as log:
                for line in proc.stdout:
                    if 'DW_AT_name' not in line:
                        continue
                    match = re.search(r'\b(serve_impl|serve_tls_impl)<([^>]+)>', line)
                    if not match:
                        continue
                    log.write(line)
                    values = tuple(v.strip() for v in match[2].split(','))
                    assert set(values) <= {'true', 'false'}, values
                    if match[1] == 'serve_tls_impl':
                        assert len(values) == 5
                        group = 'userspace_tls'
                    else:
                        assert len(values) == 6
                        group = 'no_borrow' if values[1] == 'true' else 'plaintext'
                    variants[group].add(values)
            assert proc.wait() == 0
        item['instantiations'] = {k: sorted(v) for k, v in variants.items()}
        output.append(item)
    save(OUT / 'instantiation-inventory.json', dict(
        serve_impl_parameters=['TrackOutput', 'TlsNoBorrow', 'kEp', 'Submit', 'ClassifySend', 'Coded'],
        serve_tls_impl_parameters=['TrackOutput', 'kEp', 'Submit', 'ClassifySend', 'Coded'],
        rows=output))


def elf_controls():
    out = OUT / 'elf-controls'
    out.mkdir(exist_ok=True)
    rows = []
    for name, source_path, kind in [
            ('text-byte', OUT / 'POST/artifacts/tomokv', 'text'),
            ('text-subsection-byte', OUT / 'POST/artifacts/src/core/genthread.o', 'subsection'),
            ('relocation-target', OUT / 'POST/artifacts/src/core/genthread.o', 'relocation'),
            ('function-address', OUT / 'POST/artifacts/tomokv', 'address'),
            ('entry-point', OUT / 'POST/artifacts/tomokv', 'entry')]:
        elf = Elf(source_path)
        data = bytearray(elf.data)
        if kind in ('text', 'subsection'):
            index = next(i for i, (s, n) in enumerate(zip(elf.sections, elf.names))
                         if s[2] & 4 and s[5] and
                         (n == '.text' if kind == 'text' else n.startswith('.text.')))
            data[elf.sections[index][4]] ^= 1
            error = f'executable {elf.names[index]}: bytes differ'
        elif kind == 'relocation':
            section = next(s for s in elf.sections if s[1] == 4 and s[5] and
                           s[7] < len(elf.sections) and elf.sections[s[7]][2] & 4)
            offset = section[4] + 16
            struct.pack_into('<q', data, offset, struct.unpack_from('<q', data, offset)[0] + 1)
            error = 'allocated relocation targets differ'
        elif kind == 'entry':
            struct.pack_into('<Q', data, 24, struct.unpack_from('<Q', data, 24)[0] + 1)
            error = 'ELF kind/machine/entry or program headers differ'
        else:
            table, index = next((t, i) for t, symbols in elf.tables.items()
                                for i, s in enumerate(symbols) if s['info'] & 15 == 2 and s['size']
                                and 0 < s['sec'] < len(elf.sections) and elf.sections[s['sec']][2] & 4)
            offset = elf.sections[table][4] + index * elf.sections[table][9] + 8
            struct.pack_into('<Q', data, offset, struct.unpack_from('<Q', data, offset)[0] + 1)
            error = 'allocated symbol addresses/identities differ'
        broken = out / (name + '.NEVER-RUN')
        broken.write_bytes(data)
        broken.chmod(0o600)
        result = compare_files(source_path, broken)
        assert not result['okay'] and error in result['errors'], result
        save(out / (name + '.json'), result)
        rows.append(dict(control=name, rejected=True, expected_error=error,
                         sha256=sha(broken), executed=False))
    save(out / 'results.json', rows)


# Each entry names an exercised state and the exact rejection expected when its
# real mechanism is removed. No mutation is compiled into a production object.
CONTROLS = [
    ('false-progress', 'empty', 'empty-progress'),
    ('deny-submit', 'empty', 'prepare-allows-submit'),
    ('direct', 'direct-spill', 'direct-spill-bytes'),
    ('spill', 'direct-spill', 'direct-spill-bytes'),
    ('coded', 'coded-frontier', 'coded-or-materialized-bytes'),
    ('materialize', 'pending-code', 'coded-or-materialized-bytes'),
    ('materialize', 'coded-borrow', 'borrow-crlf-oob-order'),
    ('seal', 'borrow-oob', 'borrow-crlf-oob-order'),
    ('prefix', 'borrow-oob', 'borrow-crlf-oob-order'),
    ('borrow', 'borrow-oob', 'borrow-crlf-oob-order'),
    ('copy', 'borrow-oob', 'release-order'),
    ('release', 'borrow-oob', 'borrow-policy-release-suppression'),
    ('crlf', 'borrow-oob', 'borrow-crlf-oob-order'),
    ('retire', 'borrow-oob', 'borrow-crlf-oob-order'),
    ('retire-double', 'borrow-oob', 'retire-before-stage'),
    ('release-double', 'borrow-oob', 'release-identity-count'),
    ('note-before', 'borrow-oob', 'retire-before-stage'),
    ('note-after', 'borrow-oob', 'borrow-policy-release-suppression'),
    ('oob', 'borrow-oob', 'borrow-crlf-oob-order'),
    ('oob-refuse', 'borrow-oob', 'hook-oob-armed'),
    ('oob-refuse', 'oob-hole', 'oob-hole-armed'),
    ('oob-refuse', 'limit-reply', 'limit-oob-armed'),
    ('draining-clear', 'borrow-oob', 'oob-fully-flushed'),
    ('teardown-release', 'borrow-oob', 'borrow-released-once'),
    ('false-no-progress', 'borrow-oob', 'borrow-progress'),
    ('early-oob', 'oob-hole', 'oob-held-at-hole'),
    ('oob', 'oob-hole', 'oob-flushed-after-frontier'),
    ('ignore-limit', 'limit-reply', 'limit-prevents-pump'),
    ('ignore-limit', 'limit-empty', 'limit-progress'),
    ('oob', 'limit-reply', 'limit-after-oob-before-accounting'),
    ('skip-limit', 'empty', 'limit-callback-gating'),
    ('allowed', 'limit-reply', 'limit-submit-allowed'),
    ('force-submit', 'cipher-only', 'cipher-only-pump-selection'),
    ('cipher-condition', 'cipher-only', 'cipher-only-pump-selection'),
    ('plain-pump', 'pump-ready', 'plain-pump-selection'),
    ('classification', 'pump-ready', 'plain-send-and-classification'),
    ('classification', 'cipher-only', 'tls-send-and-classification'),
    ('plain-frontier', 'pump-ready', 'plain-frontier-unchanged'),
    ('cipher-frontier', 'cipher-only', 'cipher-frontier-unchanged'),
    ('start-tracking', 'direct-spill', 'output-accounting'),
    ('stop-tracking', 'pending-code', 'output-accounting'),
    ('serves', 'empty', 'serve-retire-direct-empty-counts'),
    ('retired', 'direct-spill', 'serve-retire-direct-empty-counts'),
    ('retired', 'limit-reply', 'serve-retire-direct-empty-counts'),
    ('direct-count', 'direct-spill', 'serve-retire-direct-empty-counts'),
    ('empty-count', 'empty', 'serve-retire-direct-empty-counts'),
    ('empty-count', 'limit-empty', 'serve-retire-direct-empty-counts'),
    ('no-cipher-window', 'cipher-only', 'ciphertext-window-armed'),
    ('no-done-window', 'direct-spill', 'direct-spill-bytes'),
    ('acquire-fail', 'direct-spill', 'fixture-rob-acquire'),
    ('bio-fail', 'cipher-only', 'fixture-bio-pair'),
    ('wrong-cipher-window', 'cipher-only', 'cipher-only-no-plaintext'),
    ('unknown-state', 'unknown-state', 'selected-state-entered'),
]


def mutant(tree):
    header = tree / 'src/net/wb.h'
    text = header.read_text()
    hook = '''inline bool tlsserve_fault(const char* name) {
    const char* selected = std::getenv("TLSERVE_FAULT");
    return selected && std::strcmp(selected, name) == 0;
}
'''
    text = text.replace('namespace tomo {', hook + '\nnamespace tomo {', 1)
    a = text.index('#define TOMO_WB_SERVE_BODY(')
    b = text.index('#undef TOMO_WB_SERVE_BODY', a)
    body = text[a:b]

    def replace(before, after):
        nonlocal body
        assert before in body, before
        body = body.replace(before, after)

    for fault, statement in [
            ('direct', 'conn.commit_fill(op.direct_len);'),
            ('direct', 'conn.fill_buf().commit_raw(op.direct_len);'),
            ('spill', 'conn.append_fill(op.reply.data(), op.reply.size());'),
            ('spill', 'conn.fill_buf().append(op.reply.data(), op.reply.size());'),
            ('coded', 'stage_coded_reply<TrackOutput>(conn, op);'),
            ('materialize', 'op_materialise_code(op);'),
            ('seal', 'conn.seal_fill_segment();'),
            ('copy', 'conn.append_buf_segment(op.zc_ptr, op.zc_len);'),
            ('release', 'release(op.zc_shard, op.zc_ptr);'),
            ('borrow', 'conn.append_borrow_segment(op.zc_ptr, op.zc_len, op.zc_shard);'),
            ('crlf', 'conn.append_static_segment(kCrlf, sizeof(kCrlf));'),
            ('oob', 'did |= flush_deferred_oob(conn);'),
            ('serves', 'stats_.serves++;'),
            ('retired', 'stats_.retired += retired;'),
            ('direct-count', 'stats_.direct++;'),
            ('empty-count', 'stats_.serves_empty++;')]:
        replace(statement, f'{{ if (!tlsserve_fault("{fault}")) {statement} }}')
    replace('conn.append_buf_segment(op.direct, op.direct_len,',
            'if (!tlsserve_fault("prefix")) conn.append_buf_segment(op.direct, op.direct_len,')
    replace('if (op.zc_ptr) retire_fn_', 'if (op.zc_ptr && !tlsserve_fault("retire")) retire_fn_')
    replace('if (op.no_borrow())', 'if (op.no_borrow() && !tlsserve_fault("note-before"))')
    body, count = re.subn(r'^(\s+)note_zc_suppressed_tls\(\);',
                         r'\1if (!tlsserve_fault("note-after")) note_zc_suppressed_tls();',
                         body, flags=re.M)
    assert count == 2
    replace('if (limit_fn_(limit_ctx_, c))',
            'if (!tlsserve_fault("skip-limit") && limit_fn_(limit_ctx_, c) && !tlsserve_fault("ignore-limit"))')
    replace('if (submit_allowed)', 'if (submit_allowed && !tlsserve_fault("allowed"))')
    replace('if constexpr (Submit)', 'if (Submit || tlsserve_fault("force-submit"))')
    replace('if (!conn.nothing_to_write()) did |= pump<',
            'if (!conn.nothing_to_write() && !tlsserve_fault("plain-pump")) did |= pump<')
    replace('|| tls.output_pending()', '|| (!tlsserve_fault("cipher-condition") && tls.output_pending())')
    # Braces are essential here: the existing else belongs to if constexpr.
    replace('if constexpr (TrackOutput) conn.start_obuf_tracking();',
            'if constexpr (TrackOutput) { if (!tlsserve_fault("start-tracking")) conn.start_obuf_tracking(); }')
    replace('else conn.stop_obuf_tracking();',
            'else { if (!tlsserve_fault("stop-tracking")) conn.stop_obuf_tracking(); }')
    replace('draining_ = nullptr;', 'if (!tlsserve_fault("draining-clear")) draining_ = nullptr;')
    replace('return did;', 'return tlsserve_fault("false-progress") ? true : tlsserve_fault("false-no-progress") ? false : did;')
    replace('retire_fn_(retire_ctx_, conn, op);',
            '{ retire_fn_(retire_ctx_, conn, op); if (tlsserve_fault("retire-double")) retire_fn_(retire_ctx_, conn, op); }')
    # The second release is inside the first release's fault guard.
    replace('release(op.zc_shard, op.zc_ptr);',
            '{ release(op.zc_shard, op.zc_ptr); if (tlsserve_fault("release-double")) release(op.zc_shard, op.zc_ptr); }')
    replace('did |= pump<kEp, ClassifySend>(c);',
            '{ did |= tlsserve_fault("classification") ? pump<kEp, false>(c) : pump<kEp, ClassifySend>(c); '
            'if (tlsserve_fault("plain-frontier")) c.commit_write(1); }')
    replace('did |= pump_tls<kEp, ClassifySend>(c, tls);',
            '{ did |= tlsserve_fault("classification") ? pump_tls<kEp, false>(c, tls) : pump_tls<kEp, ClassifySend>(c, tls); '
            'if (tlsserve_fault("cipher-frontier")) tls.consume_output(1); }')
    text = text[:a] + body + text[b:]
    text = text.replace('submit_allowed = true;', 'if (!tlsserve_fault("deny-submit")) submit_allowed = true;')
    anchor = '        if (draining_ != &c) {'
    assert text.count(anchor) == 1
    text = text.replace(anchor, '        if (tlsserve_fault("oob-refuse")) return false;\n' + anchor)
    anchor = '        c.release_all_segments([&](int32_t shard, const char* ptr) { release(shard, ptr); });'
    assert text.count(anchor) == 1
    text = text.replace(anchor, '        if (!tlsserve_fault("teardown-release"))\n' + anchor)
    anchor = 'while (!queue.empty() && queue.front().after <= retired_through)'
    assert text.count(anchor) == 1
    text = text.replace(anchor, 'while (!queue.empty() && (tlsserve_fault("early-oob") || queue.front().after <= retired_through))')
    header.write_text(text)
    driver = tree / 'tests/tlsserve_checks.inc'
    text = driver.read_text().replace('BIO_write(writer, "ciphertext", 10)',
        '(tlsserve_fault("no-cipher-window") ? 10 : BIO_write(writer, "ciphertext", 10))')
    text = text.replace('op->state.store(OpState::Done, std::memory_order_release);',
        'op->state.store(tlsserve_fault("no-done-window") ? OpState::Issued : OpState::Done, std::memory_order_release);')
    text = text.replace('Op* op = c.rob().acquire();',
                        'Op* op = tlsserve_fault("acquire-fail") ? nullptr : c.rob().acquire();')
    text = text.replace('BIO_new_bio_pair(&writer, 4096, &external, 4096)',
                        '(tlsserve_fault("bio-fail") ? 0 : BIO_new_bio_pair(&writer, 4096, &external, 4096))')
    text = text.replace('require(f.c.nothing_to_write(), "cipher-only-no-plaintext");',
                        'if (tlsserve_fault("wrong-cipher-window")) f.c.append_fill("x", 1);\n'
                        '            require(f.c.nothing_to_write(), "cipher-only-no-plaintext");')
    driver.write_text(text)


def controls():
    out = OUT / 'controls'
    tree = out / 'source'
    tree.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'src', tree / 'src', dirs_exist_ok=True)
    (tree / 'tests').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'tests/tlsserve_checks.inc', tree / 'tests/tlsserve_checks.inc')
    mutant(tree)
    (tree / 'main.cc').write_text(DRIVER)
    results = []
    for variant in ('normal', 'db0'):
        binary = out / f'unit-{variant}'
        flags = FLAGS + (['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if variant == 'db0' else [])
        cmd = ['g++', *flags, '-I' + str(tree), '-I' + str(ROOT), str(tree / 'main.cc'),
               str(tree / 'src/net/tls.cc'), *LIBS, '-o', str(binary)]
        (out / f'command-{variant}.json').write_text(json.dumps(cmd, indent=2) + '\n')
        with (out / f'build-{variant}.log').open('w') as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        jobs = [('positive', None, None, None)]
        for fault, case, rejection in CONTROLS:
            configs = [None]
            if fault == 'force-submit':
                # Both prepare APIs, both event engines, coded flags and tracking states.
                configs = ['2/' + '/'.join(map(str, flags))
                           for flags in itertools.product((0, 1), (0, 1), (0, 1), (2, 3))]
            jobs += [(fault, case, rejection, config) for config in configs]
        for index, (fault, case, rejection, config) in enumerate(jobs):
            env = dict(os.environ)
            env.pop('TLSERVE_FAULT', None)
            env.pop('TLSERVE_CASE', None)
            env.pop('TLSERVE_CONFIG', None)
            if case:
                env.update(TLSERVE_FAULT=fault, TLSERVE_CASE=case)
            if config:
                env['TLSERVE_CONFIG'] = config
            logfile = out / f'{variant}-{index:02d}-{fault}-{case or "all"}.log'
            with logfile.open('w') as log:
                result = subprocess.run([str(binary)], env=env, stdout=log, stderr=subprocess.STDOUT)
            detail = logfile.read_text()
            okay = result.returncode == (1 if rejection else 0)
            if rejection:
                okay &= f': {rejection}\n' in detail
            results.append(dict(variant=variant, fault=fault, state=case, config=config, expected=rejection,
                                returncode=result.returncode, okay=okay, output=detail))
        save(out / 'results.json', results)
    assert all(r['okay'] for r in results), 'unexpected control result; see controls/results.json'
    labels = set(re.findall(r'"([a-z][a-z-]+)"\);',
                            (ROOT / 'tests/tlsserve_checks.inc').read_text()))
    covered = {r['expected'] for r in results if r['expected']}
    assert labels == covered, dict(missing=sorted(labels - covered), extra=sorted(covered - labels))
    save(out / 'assertion-coverage.json', {label: [dict(fault=r['fault'], state=r['state'],
         variant=r['variant'], config=r['config'], returncode=r['returncode'])
         for r in results if r['expected'] == label] for label in sorted(labels)})


def inputs():
    frozen = json.loads((OUT / 'freeze/resolved-inputs.json').read_text())
    changed = {path: dict(pre=digest, post=sha(path)) for path, digest in frozen.items()
               if sha(path) != digest}
    # Only the header and the new test-only dependency line in Makefile may change.
    assert set(changed) <= {str(ROOT / 'src/net/wb.h'), str(ROOT / 'Makefile')}, changed
    current = subprocess.check_output(['make', '-Bn', '-j16', 'all'], cwd=ROOT, text=True)
    (OUT / 'POST-build-commands.txt').write_text(current)
    before = (OUT / 'freeze/build-commands.txt').read_text()
    assert [x for x in before.splitlines() if x.startswith('g++ ')] == [
        x for x in current.splitlines() if x.startswith('g++ ')]
    save(OUT / 'reproducibility.json', dict(identical_build_commands=True,
         resolved_inputs=len(frozen), changed_inputs=changed, source_path=str(ROOT),
         production_output_path='build/tomokv', affinity=sorted(os.sched_getaffinity(0))))


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['source', 'inventory', 'elf-controls', 'controls', 'inputs'])
    args = parser.parse_args()
    globals()[args.command.replace('-', '_')]()
    print('PASS', args.command)


if __name__ == '__main__':
    main()
