#!/usr/bin/env python3
"""Offline 2s arm, byte-identity, PAD and instruction receipts. Never run tomokv."""
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
from wb_rule_artifacts import body, clean

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
PRE = BUILD / 'wbrule2s-pre'
PRE_SRC = BUILD / 'wbrule2s-pre-src'
STUDY = BUILD / 'wbrule2s34-src'
GROUPS = ('policy', 'phase', 'stages', 'split-phase', 'split-overlap')


def pinned():
    assert os.sched_getaffinity(0) <= set(range(112, 128)), 'use taskset -c 112-127'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def receipt(path):
    elf = Elf(path)
    sizes = dict(zip(elf.names, (s[5] for s in elf.sections)))
    return dict(path=str(path), sha256=sha(path), text=sizes['.text'],
                tdata=sizes.get('.tdata', 0), tbss=sizes.get('.tbss', 0))


def replace(path, old, new):
    s = path.read_text()
    assert s.count(old) == 1, (path, old, s.count(old))
    path.write_text(s.replace(old, new))


def prepare34():
    files = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
    for name in files:
        source = ROOT / name
        if not source.is_file(): continue
        dest = STUDY / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    policy = STUDY / 'src/core/wb_rule.h'
    s = policy.read_text()
    start = s.index('template <class Connection>\ninline bool defer(')
    end = s.index('// Both modes use', start)
    split = s[start:end].replace('inline bool defer(', 'inline bool defer_split34(')
    split = split.replace('kPolicyFraction', 'kSplitStudyFraction')
    s = s[:end] + '// Isolated measurement overlay only; never a production selector.\ninline constexpr std::ratio<3, 4> kSplitStudyFraction{};\n' + split + s[end:]
    s = s.replace('!client->dead() && defer(*client)', '!client->dead() && defer_split34(*client)')
    first = s.index('    template <bool HasTls, bool kEp, class Loop, bool Coded = true>')
    last = s.index('\n};', first)
    serve = s[first:last].replace('uint32_t serve(', 'uint32_t serve_split34(').replace('defer(*c)', 'defer_split34(*c)')
    s = s[:last] + '\n' + serve + s[last:]
    policy.write_text(s)
    replace(STUDY/'src/core/io_loop.h', 'return work + wb_rule::Phase2::serve<HasTls, kEp, IoLoop, Fused>(*this);',
            'if constexpr (Fused && !SplitLocal)\n            return work + wb_rule::Phase2::serve<HasTls, kEp, IoLoop, Fused>(*this);\n        else\n            return work + wb_rule::Phase2::serve_split34<HasTls, kEp, IoLoop, Fused>(*this);')
    replace(STUDY/'tests/wb_rule_phase_unit.cc', 'split_fraction_num = 1, split_fraction_den = 2',
            'split_fraction_num = 3, split_fraction_den = 4')
    replace(STUDY/'tests/wb_rule_2s_cost.cc', 'wb_rule::defer(*clients[i])', 'wb_rule::defer_split34(*clients[i])')
    replace(STUDY/'tests/wb_rule_2s_cost.cc', 'numerator = 1, denominator = 2', 'numerator = 3, denominator = 4')
    subprocess.run(['python3', 'tests/r7shadow_sync.py', '--write'], cwd=STUDY, check=True)
    patch = ''.join(''.join(difflib.unified_diff((ROOT/name).read_text().splitlines(True),
                     (STUDY/name).read_text().splitlines(True), fromfile='a/'+name, tofile='b/'+name))
                    for name in ('src/core/wb_rule.h', 'src/core/io_loop.h', 'src/core/reorder.cc',
                                 'tests/wb_rule_phase_unit.cc', 'tests/wb_rule_2s_cost.cc'))
    (BUILD/'wbrule2s34.patch').write_text(patch)
    with (BUILD/'wbrule2s34-build.log').open('w') as log:
        subprocess.run(['make', '-j16', 'all', 'build/wb-rule-unit', 'build/wb-rule-db0-unit',
                        'build/wb-rule-phase-unit', 'build/wb-rule-db0-phase-unit'],
                       cwd=STUDY, stdout=log, stderr=subprocess.STDOUT, check=True)
    shutil.copy2(STUDY/'build/tomokv', BUILD/'tomokv-2s34')
    for group in GROUPS:
        with (BUILD/f'wbrule2s34-{group}-check.log').open('w') as log:
            subprocess.run(['python3', 'tests/wb_rule_checks.py', 'check', group, '--positive-only'],
                           cwd=STUDY, stdout=log, stderr=subprocess.STDOUT, check=True)
    print(json.dumps(receipt(BUILD/'tomokv-2s34'), indent=2))


def code_digest(value):
    return hashlib.sha256(value[0] + json.dumps(value[1], sort_keys=True).encode()).hexdigest()


def identity():
    rows = []
    for post in (BUILD, STUDY/'build'):
        for ns in ('src', 'db0/src'):
            for file in ('core/genthread.o', 'core/reorder.o', 'cmd/t_string.o', 'cmd/t_string_notify.o'):
                a, b = Elf(PRE/ns/file), Elf(post/ns/file)
                before, after = a.functions(), b.functions()
                names = sorted(before.keys() | after.keys())
                labels = subprocess.check_output(['c++filt'], input='\n'.join(names)+'\n', text=True).splitlines()
                for name, label in zip(names, labels):
                    if '/cmd/' in '/'+file and not re.search(r'::cmd_(get|set)(?:<|\(|_tls\(|_notify\()', label): continue
                    ca = a.canonical(before[name]) if name in before else None
                    cb = b.canonical(after[name]) if name in after else None
                    rows.append(dict(arm='half' if post == BUILD else 'three-quarter', object=ns+'/'+file,
                                     symbol=name, name=label, identical=ca == cb,
                                     pre=code_digest(ca) if ca else None, post=code_digest(cb) if cb else None))
    (BUILD/'wbrule2s-identity.json').write_text(json.dumps(rows, indent=2)+'\n')
    wrong = [r for r in rows if not r['identical']]
    print(f'Fused objects and GET/SET: {len(rows)-len(wrong)}/{len(rows)} identical functions')
    for r in wrong[:25]: print(r['arm'], r['object'], r['name'])
    assert not wrong, 'fused/command byte identity failed'
    for arm in ('half', 'three-quarter'):
        for obj in sorted({r['object'] for r in rows if r['arm'] == arm}):
            subset = [(r['symbol'], r['post']) for r in rows if r['arm'] == arm and r['object'] == obj]
            print(arm, obj, hashlib.sha256(json.dumps(subset).encode()).hexdigest())


def link_command():
    lines = (BUILD/'wbrule2s-pre-build.log').read_text().splitlines()
    cmd = next(shlex.split(s) for s in reversed(lines) if ' -o ../wbrule2s-pre/tomokv ' in s)
    return [str((PRE_SRC/a).resolve()) if a.endswith('.o') else a for a in cmd]


def pads():
    command = link_command()
    probe = BUILD/'wbrule2s-pre-relink'
    command[command.index('-o')+1] = str(probe)
    subprocess.run(command, cwd=PRE_SRC, check=True)
    assert sha(probe) == sha(PRE/'tomokv'), 'PRE relink changed bytes'
    result = []
    for candidate, output in ((BUILD/'tomokv', BUILD/'tomokv-pad'),
                               (BUILD/'tomokv-2s34', BUILD/'tomokv-2s34-pad')):
        before, after = receipt(PRE/'tomokv'), receipt(candidate)
        delta = after['text'] - before['text']
        assert delta >= 0, 'PRE cannot be padded down; use an explicit common-size control'
        prefix, suffix = output.with_suffix('.prefix.o'), output.with_suffix('.suffix.o')
        prefix_bytes, suffix_bytes = delta//16*16, 0
        for _ in range(4):
            for obj, count in ((prefix, prefix_bytes), (suffix, suffix_bytes)):
                source = f'.section .text,"ax",@progbits\n.balign 1\n.fill {count},1,0x90\n.section .note.GNU-stack,"",@progbits\n'
                subprocess.run(['g++', '-x', 'assembler', '-c', '-o', str(obj), '-'], input=source, text=True, check=True)
            cmd = list(command)
            cmd[cmd.index('-o')+1] = str(output)
            first = next(i for i, a in enumerate(cmd) if a.endswith('.o'))
            cmd.insert(first, str(prefix)); cmd.insert(cmd.index('-o'), str(suffix))
            subprocess.run(cmd, cwd=PRE_SRC, check=True)
            observed = receipt(output)
            remaining = after['text'] - observed['text']
            if not remaining: break
            if suffix_bytes + remaining < 0:
                prefix_bytes -= 16; suffix_bytes += remaining + 16
            else: suffix_bytes += remaining
        assert observed['text'] == after['text']
        row = dict(kind='A: behaviour twin', scope='PRE behaviour, exact aggregate candidate .text size; individual addresses and function layout are not matched',
                   pre=before, post=after, pad=observed, prefix_bytes=prefix_bytes, suffix_bytes=suffix_bytes,
                   pre_relink_sha256=sha(probe))
        output.with_suffix('.json').write_text(json.dumps(row, indent=2)+'\n')
        result.append(row)
    (BUILD/'wbrule2s-pads.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


def costs():
    trace = BUILD/'wbrule2s-instruction-trace'
    subprocess.run(['g++', '-std=c++20', '-O2', '-Wall', '-Wextra', str(ROOT/'tools/wb_rule_2s_trace.cc'), '-o', str(trace)], check=True)
    rows = []
    for name, source in (('half', ROOT), ('three-quarter', STUDY)):
        witness = BUILD/f'wbrule2s-cost-{name}'
        subprocess.run(['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
                        '-DTOMO_JEMALLOC', '-I'+str(source), str(source/'tests/wb_rule_2s_cost.cc'), '-o', str(witness), '-ljemalloc'], check=True)
        elf = Elf(witness); section = elf.sections[elf.names.index('.text')]
        for kind in ('walk', 'select'):
            symbol = elf.functions()['wb_rule_2s_cost_'+kind]
            for shape in ('p32', 'mget'):
                for count in (16, 128):
                    case = f'{kind}-{shape}-{count}'
                    command = [str(trace), str(witness), case, f'{symbol["value"]:x}', f'{section[3]:x}', f'{section[5]:x}', str(int(elf.kind == 3))]
                    run = subprocess.run(command, capture_output=True, text=True, timeout=180)
                    assert run.returncode == 0 and 'PASS wb-rule 2s cost' in run.stdout, run.stdout+run.stderr
                    counts = json.loads(next(s[6:] for s in run.stdout.splitlines() if s.startswith('TRACE=')))
                    rows.append(dict(arm=name, case=case, **counts, witness_sha256=sha(witness), command=command, stdout=run.stdout))
                    print(name, case, counts, flush=True)
    (BUILD/'wbrule2s-costs.json').write_text(json.dumps(dict(scope='One deterministic synthetic invocation, x86 instruction steps, not PMU instructions/op, cycles, IPC, or latency. walk is eligibility only; select adds production FIFO/scratch selection on a fixture deque. No retirement, IFID, AOF or sends.', tracer_sha256=sha(trace), rows=rows), indent=2)+'\n')


def audit():
    # The acquire walk is literally inherited. Study differences are only the fraction.
    pre = (PRE_SRC/'src/core/wb_rule.h').read_text()
    post = (ROOT/'src/core/wb_rule.h').read_text()
    study = (STUDY/'src/core/wb_rule.h').read_text()
    clauses = {}
    for name in ('staged_bytes', 'code_bytes', 'reply_bytes', 'defer'):
        a, b = clean(body(pre, name)), clean(body(post, name))
        assert a == b, name
        clauses[name] = hashlib.sha256(a.encode()).hexdigest()
    assert clean(body(study, 'defer_split34').replace('kSplitStudyFraction', 'kPolicyFraction')) == clean(body(post, 'defer'))
    proofs = {}
    for root, tag, suffix in ((BUILD, 'half', ''), (STUDY/'build', 'three-quarter', '-positive')):
        for group in GROUPS:
            path = root/f'wb-rule-{group}{suffix}-proofs.json'
            rows = json.loads(path.read_text())
            assert rows and all(r['passed'] and sha(r['binary']) == r['sha256'] for r in rows)
            proofs[tag+'/'+group] = dict(path=str(path), sha256=sha(path), positive=sum(r['expected_exit']==0 for r in rows), negative=sum(r['expected_exit']==1 for r in rows))
    identity_rows = json.loads((BUILD/'wbrule2s-identity.json').read_text())
    assert all(r['identical'] for r in identity_rows)
    result = dict(baseline='32d27ee7562ed5a17ff889c0fe5cf250f3fdc63c',
                  source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  clause_hashes=clauses, proofs=proofs,
                  inputs={str(p):sha(p) for p in (Path('/home/user/Projects/cx-final/MEASURE-REQUEST-wbrule.md'), Path('/home/user/Projects/cx-drainall-test/MEASURE-REQUEST-window5.md'), Path('/home/user/Projects/cx-drainall-test/tools/drainall_window5.patch'))},
                  receipts={name:sha(BUILD/name) for name in ('wbrule2s-identity.json', 'wbrule2s-pads.json', 'wbrule2s-costs.json', 'wbrule2s34.patch')},
                  binaries=[receipt(p) for p in (PRE/'tomokv', BUILD/'tomokv', BUILD/'tomokv-2s34', BUILD/'tomokv-pad', BUILD/'tomokv-2s34-pad')])
    (BUILD/'wbrule2s-artifacts.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare34', 'identity', 'pads', 'costs', 'audit'))
    args = parser.parse_args(); pinned(); globals()[args.action]()
