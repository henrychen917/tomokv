#!/usr/bin/env python3
"""Offline cleanup-readreply proofs. Pin to 112-127; never execute a production ELF.

ELF comparison reuses the strict raw-section/relocation/address checker. Generated
controls are serverless rltopo fixtures, with the real implementation copied from
the worktree. No alternative read implementation or production option is added.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile

from ttlstate_proof import compare_arms, compare_files, save
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cleanup-readreply'


def elf_controls():
    out = OUT / 'elf-controls'
    out.mkdir(exist_ok=True)
    rows = []
    for name, source, kind in [
            ('text-byte', OUT / 'POST/artifacts/tomokv', 'text'),
            ('text-subsection-byte', OUT / 'POST/artifacts/src/core/genthread.o', 'subsection'),
            ('relocation-target', OUT / 'POST/artifacts/src/core/genthread.o', 'relocation'),
            ('function-address', OUT / 'POST/artifacts/tomokv', 'address')]:
        elf = Elf(source)
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
            offset = s[4] + 16
            struct.pack_into('<q', data, offset, struct.unpack_from('<q', data, offset)[0] + 1)
            error = 'allocated relocation targets differ'
        else:
            table, i = next((t, i) for t, symbols in elf.tables.items()
                            for i, s in enumerate(symbols) if s['info'] & 15 == 2 and s['size']
                            and 0 < s['sec'] < len(elf.sections) and elf.sections[s['sec']][2] & 4)
            offset = elf.sections[table][4] + i * elf.sections[table][9] + 8
            struct.pack_into('<Q', data, offset, struct.unpack_from('<Q', data, offset)[0] + 1)
            error = 'allocated symbol addresses/identities differ'
        broken = out / (name + '.NEVER-RUN')
        broken.write_bytes(data)
        broken.chmod(0o600)
        result = compare_files(source, broken)
        assert not result['okay'] and error in result['errors'], result
        save(out / (name + '.json'), result)
        rows.append(dict(control=name, rejected=True, expected_error=error, executed=False))
    save(out / 'results.json', rows)


def cfg():
    """Check paths through the real reference's optimized GIMPLE, not normalized asm."""
    directory = OUT / 'freeze'
    helper = (directory / 'read_local_reply_string.cfg').read_text()
    returns = re.findall(r'\breturn ([^;]+);', helper)
    assert len(returns) == 1 and re.search(re.escape(returns[0]) + r' = 1;', helper)
    body = (directory / 'prepare_local_read.optimized').read_text()
    parts = re.split(r'^  <bb (\d+)>[^\n]*\n', body, flags=re.M)
    blocks = {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}
    ids = list(blocks)
    edges = {}
    for i, bb in enumerate(ids):
        code = blocks[bb]
        edges[bb] = set(map(int, re.findall(r'goto <bb (\d+)>', code)))
        if not edges[bb] and not re.search(r'\b(return|resx|abort|__builtin_unreachable)\b', code):
            if i + 1 < len(ids):
                edges[bb].add(ids[i + 1])
    anchors = {
        'capture consumption': r' = captured_\d+->result;',
        'stable flags': r' = __atomic_load_1 ',
        'encoding dispatch': r' = object_\d+->enc;',
        'raw emission': r'# DEBUG INLINE_ENTRY read_local_reply_string',
        'final validation': r'# DEBUG INLINE_ENTRY read_local_validate',
    }
    checked = {}
    for label, pattern in anchors.items():
        matches = [bb for bb, code in blocks.items() if re.search(pattern, code)]
        assert len(matches) == 1, (label, matches)
        start = matches[0]
        todo, seen = list(edges[start]), set()
        while todo:
            bb = todo.pop()
            assert bb != start, (label, 'reply-attempt back edge')
            if bb in seen:
                continue
            seen.add(bb)
            todo.extend(edges.get(bb, set()))
        checked[label] = dict(block=start, reachable=sorted(seen), no_return_path=True)
    # Decimal conversion and buffer-growth loops are real loops; do not claim the
    # entire GET CFG is acyclic. Only the reply-attempt boundaries above are checked.
    save(OUT / 'reference-cfg.json', dict(helper_only_returns_true=True, blocks=len(blocks),
                                         edges={k: sorted(v) for k, v in edges.items()}, checks=checked))


def controls():
    out = OUT / 'controls'
    tree = out / 'source'
    tree.mkdir(parents=True, exist_ok=True)
    for directory in ('src', 'tests'):
        shutil.copytree(ROOT / directory, tree / directory, dirs_exist_ok=True)
    third_party = tree / 'third_party'
    if not third_party.exists():
        third_party.symlink_to(ROOT / 'third_party', target_is_directory=True)
    header = tree / 'src/core/ex_loop.h'
    text = header.read_text()
    # This selector exists only in a generated, uncommitted serverless mutant. It
    # selects one removed/bypassed mechanism per fresh process. No server is built.
    helper = '''
inline bool readreply_fault(const char* name) {
    const char* selected = std::getenv("READREPLY_FAULT");
    return selected && std::strcmp(selected, name) == 0;
}
'''
    text = text.replace('namespace tomo {', helper + '\nnamespace tomo {', 1)
    a = text.index('    void read_local_clear_reply(')
    b = text.index('\n    uint32_t drain_local_reads', a)
    body = text[a:b]
    body = body.replace('op.clear_reply();', 'if (!readreply_fault("omit-clear")) op.clear_reply(); else op.reply.clear();', 1)
    for statement in ('op.zc_ptr = nullptr;', 'op.zc_len = 0;', 'op.zc_shard = -1;'):
        body = body.replace(statement, 'if (!readreply_fault("omit-clear")) ' + statement, 1)
    body = body.replace('reply_bulk(op.sink(), object->read_local_str_value(stable_flags));',
                        'if (!readreply_fault("omit-raw")) reply_bulk(op.sink(), object->read_local_str_value(stable_flags));', 1)
    body = body.replace('reply_bulk(op.sink(), Slice(text, length));',
                        'if (!readreply_fault("omit-integer")) reply_bulk(op.sink(), Slice(text, length));')
    body = body.replace('if (static_cast<Type>(object->type) != Type::String)',
                        'if (!readreply_fault("accept-type") && static_cast<Type>(object->type) != Type::String)')
    body = body.replace('if (deadline >= 0 && deadline <=',
                        'if (!readreply_fault("accept-expired") && deadline >= 0 && deadline <=')
    body = body.replace('if (store.read_local_validate(probe_state))',
                        'if (readreply_fault("accept-invalid") || store.read_local_validate(probe_state))')
    anchor = '        std::atomic_thread_fence(std::memory_order_acquire);'
    assert body.count(anchor) == 1
    body = body.replace(anchor, '        if (readreply_fault("accept-invalid")) return ReadLocalFallbackReason::None;\n' + anchor)
    body = body.replace('return {ReadLocalFallbackReason::AtomicPending};',
                        'return {readreply_fault("wrong-pending") ? ReadLocalFallbackReason::Missing : ReadLocalFallbackReason::AtomicPending};')
    body = body.replace('return {ReadLocalFallbackReason::Missing};',
                        'return {readreply_fault("accept-missing") ? ReadLocalFallbackReason::None : ReadLocalFallbackReason::Missing};')
    body = body.replace('reply_null(op.sink(), op.resp3());',
                        'if (!readreply_fault("omit-null")) reply_null(op.sink(), op.resp3());')
    body = body.replace('return {ReadLocalFallbackReason::Typed};',
                        'return {readreply_fault("accept-encoding") ? ReadLocalFallbackReason::None : ReadLocalFallbackReason::Typed};')
    body = body.replace('prepared.keyspace_hits++;', 'prepared.keyspace_hits += readreply_fault("wrong-counts") ? 2 : 1;')
    body = body.replace('prepared.keyspace_misses++;', 'prepared.keyspace_misses += readreply_fault("wrong-counts") ? 2 : 1;')
    body = body.replace('return {ReadLocalFallbackReason::None, 1, 0};',
                        'return {ReadLocalFallbackReason::None, readreply_fault("wrong-counts") ? 2u : 1u, 0};')
    body = body.replace('void note_local_read_access(const Op& op, const KvObj* object, uint8_t flags) {',
                        'void note_local_read_access(const Op& op, const KvObj* object, uint8_t flags) {\n'
                        '        if (readreply_fault("omit-touch")) return;')
    start = body.index('    PreparedLocalRead prepare_local_read(')
    get = body[start:]
    anchor = '        const FlatStore::ReadLocalProbeResult result = captured->result;'
    assert get.count(anchor) == 1
    get = get.replace(anchor, '        for (unsigned control_attempt = 0; control_attempt < 2; ++control_attempt) {\n' + anchor)
    anchor = '            if (test_local_read_copied_) test_local_read_copied_();'
    assert get.count(anchor) == 1
    get = get.replace(anchor, anchor + '\n            if (readreply_fault("restore-continue") && !control_attempt) continue;')
    anchor = '        // Both a failed capture and a failed final validation demote through the same cleanup.'
    assert get.count(anchor) == 1
    get = get.replace(anchor, '            break;\n        }\n' + anchor)
    body = body[:start] + get
    header.write_text(text[:a] + body + text[b:])
    driver = tree / 'tests/rltopo_unit.cc'
    text = driver.read_text()
    text = text.replace('if (fault == Fault::NoFlip) return;',
                        'if (fault == Fault::NoFlip || readreply_fault("omit-window")) return;')
    text = text.replace('if (state == "external") value =',
                        'if (state == "external" && !readreply_fault("wrong-encoding")) value =')
    text = text.replace('guard.emplace(store.read_local_table_guard());',
                        'if (!readreply_fault("omit-topology-window")) guard.emplace(store.read_local_table_guard());')
    driver.write_text(text)
    flags = ['-std=c++20', '-O1', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
             '-fno-omit-frame-pointer', '-no-pie', '-DTOMO_MDBQSBR_TEST',
             '-DTOMO_CORE_CONCURRENCY_TEST', '-fsanitize=address,undefined', '-I.']
    objects = [ROOT / r['object'].replace('build/', 'build/mdbqsbr-asan/', 1)
               for r in json.loads((OUT / 'freeze/object-inventory.json').read_text())
               if r['object'].startswith('build/src/') and r['source'] != 'src/main.cc']
    binary = out / 'rltopo-controls'
    argv = ['g++', *flags, 'tests/rltopo_unit.cc', *map(str, objects), '-o', str(binary),
            '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
    save(out / 'build-command.json', dict(cwd=str(tree), argv=argv,
                                         mapping='real mutated driver linked first, ahead of unchanged instrumented implementation objects'))
    with (out / 'build.log').open('w') as log:
        subprocess.run(argv, cwd=tree, stdout=log, stderr=subprocess.STDOUT, check=True)
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1', UBSAN_OPTIONS='halt_on_error=1')
    env.pop('READREPLY_FAULT', None)
    for mode in ('1s', '2s'):
        with (out / ('positive-' + mode + '.log')).open('w') as log:
            subprocess.run([str(binary), mode], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    cases = []
    for command in ('GET', 'MGET'):
        for fault, states, message in [
                ('omit-raw', ['raw', 'external', 'empty', 'ttl-live', 'persisted'], 'exact private reply bytes'),
                ('omit-integer', ['integer'], 'exact private reply bytes'),
                ('accept-type', ['typed'], 'exact final fallback reason'),
                ('accept-encoding', ['encoding'], 'exact final fallback reason'),
                ('accept-expired', ['expired'], 'exact final fallback reason'),
                ('accept-invalid', ['invalid'], 'exact final fallback reason'),
                ('wrong-pending', ['pending'], 'exact final fallback reason'),
                ('omit-clear', ['raw', 'typed', 'expired', 'churn'], 'reply code and borrowed state cleared'),
                ('wrong-counts', ['raw'], 'exact accepted hit and miss counts'),
                ('omit-touch', ['raw'], 'access metadata ordering'),
                ('omit-window', ['invalid', 'tail-pending'], 'copy window entered exactly once'),
                ('omit-topology-window', ['churn'], 'topology window entered'),
                ('wrong-encoding', ['external'], 'requested encoding entered')]:
            cases.extend((fault, command, state, message) for state in states)
    cases += [('restore-continue', 'GET', 'raw', 'at most one GET reply attempt'),
              ('restore-continue', 'GET', 'integer', 'at most one GET reply attempt'),
              ('accept-missing', 'GET', 'missing', 'exact final fallback reason'),
              ('omit-null', 'MGET', 'missing', 'exact private reply bytes'),
              ('wrong-counts', 'MGET', 'missing', 'exact accepted hit and miss counts')]
    rows = []
    for mode in ('1s', '2s'):
        for fault, command, state, message in cases:
            expected = f'FAIL rltopo: readreply {command}/{state}: {message}\n'
            result = subprocess.run([str(binary), mode, 'readreply', command, state],
                                    env=dict(env, READREPLY_FAULT=fault), capture_output=True, text=True)
            name = '-'.join((mode, fault, command, state))
            (out / (name + '.log')).write_text(result.stdout + result.stderr)
            assert result.returncode == 1 and expected in result.stderr, (name, result.returncode, result.stderr)
            rows.append(dict(mode=mode, control=fault, command=command, state=state,
                             exit=result.returncode, exact_assertion=expected.strip()))
    save(out / 'results.json', dict(binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                                   positive_modes=['1s', '2s'], controls=rows))


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['identity', 'elf-controls', 'cfg', 'controls'])
    args = p.parse_args()
    if args.command == 'identity':
        result = compare_arms(OUT / 'PRE', OUT / 'POST')
        save(OUT / 'identity.json', result)
        print(f"{sum(r['okay'] for r in result['rows'])}/{len(result['rows'])} identical production ELFs")
        return 0 if result['okay'] else 1
    if args.command == 'elf-controls':
        elf_controls()
    elif args.command == 'controls':
        controls()
    else:
        cfg()
    print('PASS', args.command)
    return 0


if __name__ == '__main__':
    sys.exit(main())
