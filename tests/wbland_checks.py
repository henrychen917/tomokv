#!/usr/bin/env python3
"""Serverless adaptive writeback witnesses and strict production mutation controls."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import wb_rule_checks as legacy

ROOT = Path(__file__).resolve().parents[1]
POLICY = 'src/core/wb_rule.h'
CASES = ('endpoints', 'trickle', 'saturated', 'ramp', 'window', 'fixed', 'exits', 'grammar', 'publication')
# Change actual production code, keep the oracle. Exact assertion + exit 1 required.
MUTANTS = {
    'per-pass': ('ramp', 'ramp holds dial between full block boundaries',
                 'window.due()', 'true'),
    'always-busy': ('trickle', 'trickle fraction stays near zero',
                    'fraction = window.busy;', 'fraction = scale;'),
    'always-idle': ('saturated', 'two busy blocks reach one',
                    'fraction = window.busy;', 'fraction = 0;'),
    'switch': ('ramp', 'ramp uses two completed weighted blocks',
                'fraction = window.busy;', 'fraction = window.busy == scale ? 128 : 0;'),
    'reversed': ('ramp', 'ramp uses two completed weighted blocks',
                'fraction = window.busy;', 'fraction = scale - window.busy;'),
    'one-block': ('ramp', 'ramp uses two completed weighted blocks',
                  'busy = unsigned((total - rest) * scale / total);',
                  'busy = unsigned((unsigned __int128)(elapsed - asleep) * scale / elapsed);'),
    'window-one': ('window', 'ownership cannot shorten current block',
                   'width = std::max<size_t>(1, owned);', 'width = 1;'),
    'unweighted': ('window', 'two blocks weighted by duration rather than mean of fractions',
                   'busy = unsigned((total - rest) * scale / total);',
                   'busy = unsigned(((unsigned __int128)(elapsed-asleep)*scale/elapsed + '
                   '(unsigned __int128)(previous_wall-previous_idle)*scale/previous_wall)/2);'),
    'flushall': ('endpoints', 'zero serves every prefix',
                 'if (fraction == 0) return false;', 'if (fraction == 0) fraction = 128;'),
    'half': ('endpoints', 'policy one is exact landed half',
             ': dynamic || policy == 0 ? 0 : 128)', ': dynamic || policy == 0 ? 0 : 256)'),
    'whole': ('endpoints', 'saturated AUTO uses whole contiguous pipe',
              '(n * fraction + scale - 1) / scale', '(n + 1) / 2'),
    'finished': ('exits', 'finished pipe exits at busy endpoint',
                 'if (prefix >= threshold) return false;', 'if (prefix >= threshold && prefix < n) return false;'),
    'empty': ('exits', 'nothing in flight exits at busy endpoint',
              'if (n <= 1) return false;', 'if (n == 0) return true; if (n == 1) return false;'),
    'split-auto': ('fixed', 'split AUTO retains measured half rule',
                   '(fused || (arm & (1u << 8)))', 'true'),
    'byte-limit': ('exits', '512 bytes open busy pipe',
                   'kWbufInline', '(8 * kWbufInline)'),
}


def emit(name, output):
    _, _, old, new = MUTANTS[name]
    # The existing safe overlay builder handles every include transitively.
    if name != 'byte-limit':
        legacy.MUTANTS[name] = ('detector', POLICY, old, new, '', '')
        legacy.emit(name, output)
    else:
        text = (ROOT/POLICY).read_text()
        assert text.count(old) == 2
        legacy.MUTANTS[name] = ('detector', POLICY, text, text.replace(old, new), '', '')
        legacy.emit(name, output)


def source():
    import r7shadow_sync as sync
    from signalacct_source_checks import idle_tokens
    before = subprocess.check_output(['git', 'show', '9c4717da0:src/core/io_loop.h'], cwd=ROOT, text=True)
    after = (ROOT/'src/core/io_loop.h').read_text()
    assert idle_tokens(before) == idle_tokens(after), 'existing idle definition changed'
    for path, name in (('src/core/io_loop.h', 'run_loop'), ('src/core/reorder.cc', 'IoLoop::r7_run_loop')):
        code = sync.function((ROOT/path).read_text(), name, name == 'run_loop')
        assert code.count('wb_policy.pass(pass_ns, sig.idle_ns, self_->clients().size());') == 1
        assert 'wb_rule::State wb_policy(srv_->cfg().wb_policy, Fused && !SplitLocal);' in code
        assert code.count('tenure.pass()') == 1
        assert code.split('if (self_->sample_depth(pass_ns / 1000)) {', 1)[1].lstrip().startswith('wb_policy.publish(wb_signal);')
        assert 'wb_policy.publish(wb_signal, false);\n' in code
        assert 'wb_policy_ = nullptr;' in code
    code = (ROOT/POLICY).read_text()
    assert 'kPolicyFraction' not in code
    assert not any(x in code for x in ('now_ns(', 'clock_gettime', 'std::vector', 'std::sort', 'std::ratio'))
    assert 'std::make_unique<wb_rule::Published[]>' in (ROOT/'src/core/server.h').read_text()
    subprocess.run(['python3', 'tests/r7shadow_sync.py'], cwd=ROOT, check=True)
    print('PASS wbland source: same signal, owner stack, beat publication, generated R7 parity')


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
        if group == 'detector':
            for case in CASES: run(build/f'wbland-{ns}unit', case)
        elif group == 'clauses':
            for case in ('fastpath', 'fraction', 'staged', 'submitted', 'bytes', 'holes', 'markers', 'codes', 'acquire'):
                run(build/f'wbland-{ns}clause-unit', case, prefix='wb-rule')
        else:
            binary = build/f'wb-rule-{ns}phase-unit'
            for extra in ((), ('r7',)): run(binary, 'wbland-fused', extra=extra, prefix='wb-rule')
            for extra in ((), ('natural',), ('shallow',)):
                for case in ('wbland-split', 'wbland-local', 'wbland-split-probe', 'wbland-local-probe'):
                    run(binary, case, extra=extra, prefix='wb-rule')
    if group == 'detector':
        for name, (case, assertion, _, _) in MUTANTS.items():
            run(build/'wbland-controls'/name/'unit', case, assertion)
        source()
    elif group == 'clauses':
        # Same original clause deletions compiled through the runtime AUTO dial.
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
    c=sub.add_parser('check'); c.add_argument('group', choices=('detector', 'clauses', 'paths'))
    c.add_argument('--build', type=Path, default=ROOT/'build')
    sub.add_parser('source'); a=p.parse_args()
    if a.action == 'emit': emit(a.name, a.output)
    elif a.action == 'source': source()
    else: check(a.group, a.build.resolve())
