#!/usr/bin/env python3
"""Check/regenerate the isolated armed IO call graph; never execute a server.

This supersedes tools/reorder_sync.py for this lane: shadow dispatch must cover
fused IO, TLS, epoll, buffered reparsing, and fused read-local demotion.
The ordinary definitions stay unchanged except for cold role-entry selectors.
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import reorder_sync as base
import source_tokens as cpp

IO = ('run_loop', 'sweep', 'flush_ready', 'admit_fd', 'admit_retained_fd', 'adopt_client',
      'arm_tls_recv', 'drive_tls', 'epoll_accept', 'epoll_pass',
      'on_accept', 'on_cqe', 'on_recv', 'on_tls_recv',
      'on_tls_socket_poll', 'parse_and_dispatch', 'fused_demote_local_read_batch')


def removal_inventory(root):
    root = Path(root)
    removed = ('Targeted' + 'Ifid', 'SuppressOrdinary' + 'ActiveMark',
               'mark_active_' + 'known', 'multi_dispatch_entry_' + 'iofused',
               'multi_owner_pass_entry_' + 'iofused')
    hits, calls = [], 0
    for directory in ('src', 'tests'):
        for path in sorted((root / directory).rglob('*')):
            if path.suffix not in ('.h', '.cc', '.inc'):
                continue
            source = cpp.read(path)
            code = cpp.tokens(source)
            if directory == 'src':
                hits.extend((str(path.relative_to(root)), token) for token in code if token in removed)
            for i, token in enumerate(code):
                if token not in ('parse_and_dispatch', 'r7_parse_and_dispatch') or code[i+1:i+2] != ('<',):
                    continue
                depth, arity, j = 1, 1, i + 2
                while j < len(code) and depth:
                    if code[j] == '<': depth += 1
                    elif code[j] == '>': depth -= 1
                    elif code[j] == ',' and depth == 1: arity += 1
                    j += 1
                if not depth and code[j:j+1] == ('(',):
                    calls += 1
                    assert arity <= 3, ('obsolete IO call arity', str(path), arity)
    assert not hits, ('removed IO interface reintroduced', hits)
    assert calls, 'missing parser call inventory'
    for filename, name in (('io_loop.h', 'parse_and_dispatch'), ('reorder.cc', 'r7_parse_and_dispatch')):
        parser = cpp.function(cpp.read(root / 'src/core' / filename), name)
        assert 'IofusedPrivateQueue' not in cpp.tokens(parser), 'removed private-queue IO interface/body'

    return dict(okay=True, removed=list(removed), scope='all production C++ source')


def function(source, name, member=True):
    return cpp.Source(base.function(source, name, member))


def envelopes():
    ex = cpp.read(ROOT / 'src/core/ex_loop.h')
    io = cpp.read(ROOT / 'src/core/io_loop.h')
    boot = cpp.read(ROOT / 'src/core/genthread.cc')
    start = io.index('    class ReadLocalDemotionPlan {')
    end = io.index('\npublic:\n    bool fused_demote_local_read_batch(', start)
    demotion = cpp.Source(base.rename(io[start:end].rstrip(), {'ReadLocalDemotionPlan': 'r7_ReadLocalDemotionPlan'}))
    demotion = demotion.replace('class r7_ReadLocalDemotionPlan {', 'class IoLoop::r7_ReadLocalDemotionPlan {')
    needle = 'Task{client_, storage_->ids[i], -1, nullptr}'
    assert demotion.count(needle) == 1
    demotion = demotion.replace(needle, 'shadow_dispatch.task(client_, storage_->ids[i])')
    needle = '        bool completed_locally = false;'
    assert demotion.count(needle) == 1
    demotion = demotion.replace(needle, '''        r7::ShadowDemotionDispatch shadow_dispatch(
            *client_, count_ ? storage_->ids[count_ - 1] : rob.flush_id());
''' + needle)
    bodies, declarations = [demotion], {}
    for owner, source, methods in (('ExLoopT<Fused>', ex, base.EX), ('IoLoop', io, IO)):
        names = {name: 'r7_' + name for name in methods}
        if owner.startswith('Ex'):
            names.update(drain_tasks='r7_drain_tasks')
        else:
            names.update({name: 'r7_' + name for name in base.EX if name.startswith('fused_')})
        decls = []
        for method in methods:
            body = cpp.Source(base.rename(function(source, method), names))
            opening = body.index('{') + 1
            body = body[:opening] + '\n    TOMO_R7_PATH();' + body[opening:]
            if method == 'run_loop':
                # Extra owner opportunities must use the same guarded R7 pass
                # as the ordinary owner opportunity in this envelope.
                needle = 'fused_executor_->fused_owner_turn()'
                assert body.count(needle) == 2
                body = body.replace(needle, 'fused_executor_->fused_owner_turn<true>()', 2)
                # Accounting belongs to the ordinary envelope. Copy its current
                # clock/sample sites too, including later accounting fixes.
                body = body.replace('DatabaseMapTestHooks::loop_pass(*srv_, *self_, 0);',
                                    'DatabaseMapTestHooks::loop_pass(*srv_, *self_, 1);')
                # Include the cold armed-role binding in the same IO tenure.
                opening = body.spans('IoTenure tenure(sig);')[0][1]
                body = body[:opening] + '''
    // Bind once at armed fused IO role entry.
    if constexpr (Fused) if (srv_->read_local_enabled() && r7::shadow_available())
        fused_executor_->bind_read_local_demotion(this,
            [](void* p, Client* client, const uint64_t* probed,
               const ReadLocalFallbackReason* fallbacks, uint32_t count, uint32_t& demoted) {
                return static_cast<IoLoop*>(p)->r7_fused_demote_local_read_batch(
                    client, probed, fallbacks, count, demoted);
            });
''' + body[opening:]
            if method == 'fused_demote_local_read_batch':
                opening = body.index('{') + 1
                body = body[:opening] + '''
    if (!r7::shadow_available())
        return fused_demote_local_read_batch(client, probed, fallbacks, probed_count, demoted);
''' + body[opening:]
                body = body.replace('ReadLocalDemotionPlan plan;', 'r7_ReadLocalDemotionPlan plan;')
            if method == 'parse_and_dispatch':
                opening = body.index('{') + 1
                body = body[:opening] + '''
    // PAD A delegates to the inherited parser before any shadow scratch or scan.
    if (!r7::shadow_available())
        return parse_and_dispatch<NoBorrow, BatchOps, SplitLocal>(c);
    // Only R7 touches the otherwise uninitialized Client padding. The first
    // parser entry precedes every publication; migration retains Client + ROB.
    if (c->rob().dispatch_id() == 0) r7::ShadowLongIndex::initialize(*c);
    r7::LazyShadowDispatch shadow_dispatch(c->rob().dispatch_id());
''' + body[opening:]
                needle = 'Task t{c, rob.dispatch_id(), -1, nullptr};'
                assert body.count(needle) == 1
                body = body.replace(needle, needle + '\n        shadow_dispatch.stamp(t);')
                # Include scatter publications: a Long can precede an ordinary
                # task without itself passing the ordinary stamp site. Locally
                # completed Longs are harmless; pending_before prunes Done.
                # IO7 moved atomic scatter's publication into the shared helper.
                # Keep its index entry IO-private before delegation, and remove
                # it on refusal (the helper leaves dispatch_id unchanged).
                atomic = function(io, 'dispatch_atomic_scatter')
                assert atomic.count('c->rob().publish();') == 1
                needle = 'if (!dispatch_atomic_scatter(c, *op, scatter_dispatch)) break;'
                assert body.count(needle) == 1
                assert body.count('rob.publish();') == 11
                body = body.replace('rob.publish();', 'r7::ShadowLongIndex::record(*c, *op); rob.publish();', 11)
                body = body.replace(needle, '''r7::ShadowLongIndex::record(*c, *op);
            if (!dispatch_atomic_scatter(c, *op, scatter_dispatch)) {
                r7::ShadowLongIndex::unpublish(*c);
                break;
            }''')
                assert body.count('rob.unpublish();') == 1
                body = body.replace('rob.unpublish();', 'rob.unpublish(); r7::ShadowLongIndex::unpublish(*c);', 1)
                body = body.replace('Fused, ReadLocalDemotionPlan,', 'Fused, r7_ReadLocalDemotionPlan,')
            signature, rest = body.split('{', 1)
            decls.append(signature.rstrip() + ';')
            signature = re.sub(r'\s*=\s*(?:false|true|void|nullptr|0|kGenthreadExBatchOps)\b', '', signature)
            signature = cpp.Source(signature).replace('r7_' + method + '(', owner + '::r7_' + method + '(', 1)
            if method == 'parse_and_dispatch':
                signature = signature.replace('DispatchResult ', 'IoLoop::DispatchResult ')
            if owner.startswith('Ex'):
                signature = 'template <bool Fused>\n' + signature
            bodies.append(signature + '{' + rest)
        declarations[owner] = '\n'.join(decls)
    bodies.append(base.rename(function(boot, 'IoLoop::run_fused', False),
                             {'run_fused': 'run_fused_reordered', 'run_loop': 'r7_run_loop'}))
    bodies.append('namespace {\n' + function(boot, 'pin_fused_thread', False) + '\n}')
    bodies.append('static ' + base.rename(function(boot, 'run_fused_server', False),
                    {'run_fused_server': 'run_fused_server_reordered', 'run_fused': 'run_fused_reordered'}))
    generated = '\n\n'.join(bodies) + '\n'
    names = {'r7_' + name for name in (*IO, *base.EX)}
    for name in sorted(names):
        spans = [token for token in cpp.lex(generated) if token.text == name]
        if not spans: raise ValueError('missing generated binding: ' + name)
        at = spans[0].start
        generated = generated[:at] + '/* TOMO_TOOL_BIND ' + name + ' */' + generated[at:]
    return generated, declarations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    bodies, declarations = envelopes()
    base.update(ROOT / 'src/core/reorder.cc', bodies, args.write)
    for owner, filename in [('ExLoopT<Fused>', 'ex_loop.h'), ('IoLoop', 'io_loop.h')]:
        base.update(ROOT / 'src/core' / filename,
                    ''.join('    ' + line + '\n' for line in declarations[owner].splitlines()), args.write)
    removal_inventory(ROOT)
    print('R7 shadow production envelopes: current')
