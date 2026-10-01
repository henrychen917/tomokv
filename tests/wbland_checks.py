#!/usr/bin/env python3
"""Serverless fixed writeback witnesses and strict production mutation controls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import wb_rule_checks as legacy

ROOT = Path(__file__).resolve().parents[1]
POLICY = 'src/core/wb_rule.h'
CASES = ('endpoints', 'exits', 'grammar', 'info')
# Structural witnesses, not snapshots of a historical tree. The clause/path
# tables and their production mutants are the behavioural oracle for defer().
IO = 'src/core/io_loop.h'
R7 = 'src/core/reorder.cc'
WB = 'src/net/wb.h'
DETECTOR_TOKENS = (
    'wb_policy_signals_', 'wb_policy_signal(', 'wb_rule::State', 'wb_policy.pass(',
    'wb_policy.publish(', 'wb_adaptive', 'wb_thread_', 'struct Window', 'struct Published')
RULE_TOKENS = ('now_ns(', 'clock_gettime', 'new ', 'malloc(', 'make_unique', 'build_arm')
SERVE = 'wb_rule::Phase2::serve<HasTls, kEp, IoLoop, Fused>(*this)'
GATHER = 'wb_rule::Phase2::gather(*this, batch, captured_left)'
SERVE_GUARD = '''
    if (!pending_serve_.empty()) {
        AofManager& aof = srv_->aof();
        if (__builtin_expect(aof.configured(), false)) {
            if (!aof_gate_target_) aof_gate_target_ = aof.posted_sequence();
            if (!aof.reply_gate_ready(aof_gate_target_)) {
                aof.register_send_gate_wait(self_->id());
                return work;
            }
        }
        aof_gate_target_ = 0;
    } else {
        aof_gate_target_ = 0;
    }
    return work + ''' + SERVE + ';'
GATHER_GUARD = '''
    if (batch.count) std::abort();
    if (pending_serve_.empty()) {
        aof_gate_target_ = 0;
        return 0;
    }
    AofManager& aof = srv_->aof();
    if (__builtin_expect(aof.configured(), false)) {
        if (!aof_gate_target_) aof_gate_target_ = aof.posted_sequence();
        if (!aof.reply_gate_ready(aof_gate_target_)) {
            aof.register_send_gate_wait(self_->id());
            return 0;
        }
    }
    aof_gate_target_ = 0;
    return ''' + GATHER + ';'
BACKSTOP = 'if (backstop_pass_ && !c->serve_pending()) enqueue_serve(c);'
IDLE = '''const bool done = c->rob().quiesced() && !more_input && !stuck &&
                        !c->serve_pending() && c->nothing_to_write() && !tls_output;'''
BUFFER = 'SmallBuf<kWbufInline>& fb = c->fill_buf();'
# Every other occurrence of a watched name is existing non-policy plumbing.
# Scope each small fragment to its owning method and require its exact count;
# never exempt an entire method from the remaining-reference scan.
PLUMBING = (
    ('', 'friend struct wb_rule::Phase2;', 1),
    ('', 'std::deque<Client*> pending_serve_;', 1),
    ('flip_io_drained', '''if (!pending_serve_.empty() || !pending_releases_.empty() ||
        !pending_handoffs_.empty() || !deferred_timers_.empty() ||
        !client_migrations_.empty() || !epoll_closes_.empty() ||
        !dead_next_.empty() || !dead_ready_.empty() ||
        !multi_deferred_.empty() || !pending_multi_cleanups_.empty() ||
        !pubsub_notification_chains_.empty() || !self_->io_inbound_quiesced() ||
        srv_->pubsub_inflight() != 0 || srv_->pubsub_pending() != 0) return false;''', 1),
    ('flip_io_drained', '''if (client->rob().in_flight() != 1 || client->send_inflight() ||
        client->serve_pending() || !client->nothing_to_write() ||
        !wb_.migration_ready(*client)) return false;''', 1),
    ('parse_and_dispatch', BUFFER, 2),
    ('ifid_parse_hash', BACKSTOP, 1), ('ifid_parse_hash', IDLE, 1),
    ('flush_ready', BACKSTOP, 1), ('flush_ready', IDLE, 1),
    ('pipeline_pass', '''while (captured_left != SIZE_MAX && captured_left &&
        !pending_serve_.empty()) {''', 1),
    ('pipeline_pass', 'if (!pending_serve_.empty() && captured_left != SIZE_MAX) ++work;', 1),
    ('enqueue_serve', '''if (c->serve_pending()) return;
        c->set_serve_pending(true); pending_serve_.push_back(c);''', 1),
    ('reap_dead', '''if (c->serve_pending() || c->send_inflight() || c->recv_armed()) {
        dead_ready_[keep++] = c; continue; }''', 1),
)
R7_PLUMBING = (
    ('r7_parse_and_dispatch', BUFFER, 2),
    ('r7_ifid_parse_hash', BACKSTOP, 1), ('r7_ifid_parse_hash', IDLE, 1),
    ('r7_flush_ready', BACKSTOP, 1), ('r7_flush_ready', IDLE, 1),
)


def cpp_tokens(text):
    # Comments and literals cannot be policy references. Keep lexical boundaries
    # ("new Thing" must not become "newThing") while ignoring whitespace.
    lexer = r'//[^\n]*|/\*[\s\S]*?\*/|R"([^\s()\\]*)\([\s\S]*?\)\1"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[a-zA-Z_]\w*|\d+|::|->|&&|\|\||[^\s]'
    return tuple(m[0] for m in re.finditer(lexer, text)
                 if not m[0].startswith(('//', '/*')))


def occurrences(code, part):
    return [i for i in range(len(code) - len(part) + 1) if code[i:i+len(part)] == part]


def method_span(code, name):
    # Only definitions: calls/declarations have no opening brace after their
    # parameter list. Current witnesses have no constructor/initializer syntax.
    starts = []
    for i in occurrences(code, (name, '(')):
        j, depth = i + 2, 1
        while j < len(code) and depth:
            depth += (code[j] == '(') - (code[j] == ')')
            j += 1
        if j < len(code) and code[j] == 'const': j += 1
        if j < len(code) and code[j] == '{': starts.append(j)
    assert len(starts) == 1, f'{name}: expected one method definition'
    start, depth = starts[0] + 1, 1
    for end in range(start, len(code)):
        depth += (code[end] == '{') - (code[end] == '}')
        if not depth: return start, end
    raise AssertionError(f'{name}: unclosed method')


def no_tokens(path, text, banned):
    code = cpp_tokens(text)
    for token in banned:
        assert token not in text and not occurrences(code, cpp_tokens(token)), f'{path}: banned token {token.strip()}'


def envelope(path, expected_calls, plumbing, guarded):
    text = (ROOT/path).read_text()
    code = cpp_tokens(text)
    calls = []
    for i in occurrences(code, cpp_tokens('wb_rule::Phase2::')):
        j = i + 4
        while j < len(code) and code[j] not in ('(', ';', '{', '}'): j += 1
        assert j < len(code) and code[j] == '(', f'{path}: malformed Phase2 call'
        depth, end = 1, j + 1
        while end < len(code) and depth:
            depth += (code[end] == '(') - (code[end] == ')')
            end += 1
        assert not depth, f'{path}: unclosed Phase2 call'
        calls.append(code[i:end])
    assert sorted(calls) == sorted(cpp_tokens(c) for c in expected_calls), f'{path}: Phase2 call set (count/arguments)'
    covered = set()

    def claim(method, fragment, count=1, tail=False):
        start, end = method_span(code, method) if method else (0, len(code))
        part = cpp_tokens(fragment)
        hits = occurrences(code[start:end], part)
        assert len(hits) == count, f'{path}: {method or "declaration"} anchored writeback site'
        if tail:
            assert start + hits[0] + len(part) == end, f'{path}: {method} writeback guard/call tail'
        for hit in hits:
            covered.update(range(start + hit, start + hit + len(part)))

    for method, guard in guarded: claim(method, guard, tail=True)
    for method, fragment, count in plumbing: claim(method, fragment, count)
    for i, token in enumerate(code):
        watched = (any(name in token for name in ('pending_serve_', 'serve_pending', 'kWbufInline', 'kPolicyFraction'))
                   if re.fullmatch(r'\w+', token) else False)
        watched |= code[i:i+2] in (('wb_rule', '::'), ('defer', '('))
        assert not watched or i in covered, f'{path}: unanchored writeback reference {token}'
    # IO has legitimate clocks/allocation in accept, TLS, slowlog and timers.
    # Ban them throughout the WB methods, not those unrelated owner duties.
    methods = ('wb_gather', 'wb_observe', 'wb_prefetch', 'wb_retire_prepare',
               'wb_submit_reclaim', 'wb_serve_natural', 'pipeline_pass',
               'flush_ready', 'enqueue_serve') if path == IO else ('r7_flush_ready',) if path == R7 else ()
    for method in methods:
        start, end = method_span(code, method)
        no_tokens(f'{path}:{method}', ' '.join(code[start:end]), RULE_TOKENS)
    if path == WB: no_tokens(path, ' '.join(code), RULE_TOKENS)
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
    for path in (POLICY, 'src/core/server.h', WB, IO, R7):
        no_tokens(path, (ROOT/path).read_text(), DETECTOR_TOKENS)
    no_tokens(POLICY, (ROOT/POLICY).read_text(), RULE_TOKENS)
    envelope(WB, (), (), ())
    envelope(IO, (GATHER, SERVE), PLUMBING, (('wb_gather', GATHER_GUARD), ('flush_ready', SERVE_GUARD)))
    envelope(R7, (SERVE,), R7_PLUMBING, (('r7_flush_ready', SERVE_GUARD),))
    subprocess.run([sys.executable, '-B', 'tests/r7shadow_sync.py'], cwd=ROOT, check=True)
    print('PASS wbland source: anchored calls/guards, no stray policy references or detector, R7 parity')


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
