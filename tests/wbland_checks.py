#!/usr/bin/env python3
"""Serverless fixed writeback witnesses and strict production mutation controls."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import wb_rule_checks as legacy

ROOT = Path(__file__).resolve().parents[1]
POLICY = 'src/core/wb_rule.h'
CASES = ('endpoints', 'exits', 'grammar', 'info')
# Change actual production code, keep the oracle. Exact assertion + exit 1 required.
MUTANTS = {
    'flushall': ('endpoints', 'zero serves every prefix',
                 'if (policy == 0) return false;', 'if (policy == 0) policy = 1;'),
    'half': ('endpoints', 'policy one is exact landed half',
             'std::ratio<1, 2>', 'std::ratio<1, 1>'),
    'empty': ('exits', 'nothing in flight exits under half rule',
              'if (n <= 1) return false;', 'if (n == 0) return true; if (n == 1) return false;'),
    'byte-limit': ('exits', '512 bytes open half pipe',
                   'kWbufInline', '(8 * kWbufInline)'),
}


def emit(name, output):
    _, _, old, new = MUTANTS[name]
    # The existing safe overlay builder handles every include transitively.
    if name != 'byte-limit':
        legacy.MUTANTS[name] = ('clauses', POLICY, old, new, '', '')
        legacy.emit(name, output)
    else:
        text = (ROOT/POLICY).read_text()
        assert text.count(old) == 2
        legacy.MUTANTS[name] = ('clauses', POLICY, text, text.replace(old, new), '', '')
        legacy.emit(name, output)


def source():
    def ref(path):
        return subprocess.check_output(['git', 'show', '37eeb5e90:' + path], cwd=ROOT, text=True)
    for path in ('src/net/wb.h', 'src/core/io_loop.h', 'src/core/reorder.cc'):
        assert (ROOT/path).read_text() == ref(path), path + ': REF envelope changed'
    code = (ROOT/POLICY).read_text()
    start, end = 'template <class Connection>\ninline bool defer', '// Both modes use the same'
    before = ref(POLICY).split(start, 1)[1].split(end, 1)[0]
    after = code.split(start, 1)[1].split(end, 1)[0]
    after = after.replace('Connection& c, int policy = 1', 'Connection& c')
    after = after.replace('    if (policy == 0) return false; // LATENCY: every ready head on every captured pass\n', '')
    assert after == before, 'policy 1 differs from the REF composite rule'
    for path in (POLICY, 'src/core/server.h', 'src/core/io_loop.h', 'src/core/reorder.cc'):
        text = (ROOT/path).read_text()
        assert not any(token in text for token in (
            'wb_policy_signals_', 'wb_policy_signal(', 'wb_rule::State', 'wb_policy.pass(',
            'wb_policy.publish(', 'wb_adaptive', 'wb_thread_', 'struct Window', 'struct Published'))
    assert not any(token in code for token in ('now_ns(', 'clock_gettime', 'new ', 'malloc(', 'make_unique', 'build_arm'))
    subprocess.run(['python3', 'tests/r7shadow_sync.py'], cwd=ROOT, check=True)
    print('PASS wbland source: REF rule/envelopes, no detector or policy allocation, R7 parity')


def check(group, build):
    rows = []
    def run(binary, case, assertion=None, extra=(), prefix='wbland'):
        r = subprocess.run([str(binary), case, *extra], capture_output=True, text=True, timeout=60)
        marker = f'FAIL {prefix} {case}: {assertion}' if assertion else f'PASS {prefix} {case}'
        ok = r.returncode == (1 if assertion else 0) and marker in r.stdout+r.stderr
        rows.append(dict(binary=str(binary.relative_to(ROOT)), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                         case=case, extra=extra, expected_exit=1 if assertion else 0, exit=r.returncode,
                         required=marker, passed=ok, stdout=r.stdout, stderr=r.stderr))
        print(f'{"PASS" if ok else "FAIL"} {group} {binary.parent.name}/{binary.name} {case} {" ".join(extra)}', flush=True)
        if not ok: print(r.stdout+r.stderr, flush=True)
    for ns in ('', 'db0-'):
        if group == 'clauses':
            for case in CASES: run(build/f'wbland-{ns}unit', case)
            for case in ('fastpath', 'fraction', 'staged', 'submitted', 'bytes', 'holes', 'markers', 'codes', 'acquire'):
                run(build/f'wbland-{ns}clause-unit', case, prefix='wb-rule')
        else:
            binary = build/f'wb-rule-{ns}phase-unit'
            for extra in ((), ('r7',)): run(binary, 'wbland-fused', extra=extra, prefix='wb-rule')
            for extra in ((), ('natural',), ('shallow',)):
                for case in ('wbland-split', 'wbland-local'):
                    run(binary, case, extra=extra, prefix='wb-rule')
    if group == 'clauses':
        for name, (case, assertion, _, _) in MUTANTS.items():
            run(build/'wbland-controls'/name/'unit', case, assertion)
        source()
        # Same original clause deletions compiled through the runtime policy read.
        for name, (kind, _, _, _, case, assertion) in legacy.MUTANTS.items():
            if kind == 'policy': run(build/'wbland-clause-controls'/name/'unit', case, assertion, prefix='wb-rule')
    else:
        # Real schedules must notice when knob selection is bypassed or ignored.
        for name, case, assertion in (
            ('split-policy', 'wbland-fused', 'wb-policy exact retirement in every physical schedule'),
            ('gather-policy', 'wbland-split', 'wb-policy exact retirement in every physical schedule')):
            # R7 is linked separately: a header overlay mutates FIFO/overlap only.
            for extra in (((),) if name == 'split-policy' else (('natural',), ('shallow',))):
                run(build/'wb-rule-controls'/name/'unit', case, assertion, extra, prefix='wb-rule')
    (build/f'wbland-{group}-proofs.json').write_text(json.dumps(rows, indent=2)+'\n')
    if not all(r['passed'] for r in rows): raise SystemExit(1)
    print(f'PASS wbland {group}: {len(rows)}/{len(rows)} strict outcomes')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='action', required=True)
    e=sub.add_parser('emit'); e.add_argument('name', choices=MUTANTS); e.add_argument('output', type=Path)
    c=sub.add_parser('check'); c.add_argument('group', choices=('clauses', 'paths'))
    c.add_argument('--build', type=Path, default=ROOT/'build')
    sub.add_parser('source'); a=p.parse_args()
    if a.action == 'emit': emit(a.name, a.output)
    elif a.action == 'source': source()
    else: check(a.group, a.build.resolve())
