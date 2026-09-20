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

IO = ('run_loop', 'sweep', 'flush_ready', 'admit_fd', 'adopt_client',
      'arm_tls_recv', 'drive_tls', 'epoll_accept', 'epoll_pass',
      'ifid_parse_hash', 'ifid_rx', 'on_accept', 'on_cqe', 'on_recv', 'on_tls_recv',
      'on_tls_socket_poll', 'parse_and_dispatch', 'fused_demote_local_read_batch')


def function(source, name, member=True):
    if not member:
        return base.function(source, name, False)
    match = re.search(r'^    (?:uint32_t|void|bool|DispatchResult) ' + re.escape(name) + r'\(', source, re.M)
    if not match:
        raise ValueError('missing source method ' + name)
    start = match.start()
    for line in reversed(source[:start].splitlines(keepends=True)[-8:]):
        if not (line.startswith('              ') or line.startswith('    template <') or
                line.startswith('    __attribute__')):
            break
        start -= len(line)
        if line.startswith('    template <'):
            break
    opening = source.index('{', match.end())
    depth = 0
    for token in re.finditer(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', source[opening:]):
        if token[0] == '{': depth += 1
        elif token[0] == '}': depth -= 1
        if depth == 0:
            return '\n'.join(line[4:] if line.startswith('    ') else line
                             for line in source[start:opening + token.end()].splitlines())
    raise ValueError('unclosed method ' + name)


def envelopes():
    ex = (ROOT / 'src/core/ex_loop.h').read_text()
    io = (ROOT / 'src/core/io_loop.h').read_text()
    boot = (ROOT / 'src/core/genthread.cc').read_text()
    start = io.index('    class ReadLocalDemotionPlan {')
    end = io.index('\npublic:\n    bool fused_demote_local_read_batch(', start)
    demotion = '\n'.join(line[4:] if line.startswith('    ') else line
                         for line in io[start:end].rstrip().splitlines())
    demotion = re.sub(r'\bReadLocalDemotionPlan\b', 'r7_ReadLocalDemotionPlan', demotion)
    demotion = demotion.replace('class r7_ReadLocalDemotionPlan {', 'class IoLoop::r7_ReadLocalDemotionPlan {')
    needle = 'Task{client_, storage_->ids[i], -1, nullptr}'
    assert demotion.count(needle) == 1
    demotion = demotion.replace(needle, 'r7::shadow_demoted_task(client_, storage_->ids[i])')
    bodies, declarations = [demotion], {}
    for owner, source, methods in (('ExLoopT<Fused>', ex, base.EX), ('IoLoop', io, IO)):
        names = {name: 'r7_' + name for name in methods}
        if owner.startswith('Ex'):
            names.update(drain_tasks='r7_drain_tasks', drain_tasks_with_filler='r7_drain_tasks_with_filler')
        else:
            names.update({name: 'r7_' + name for name in base.EX if name.startswith('fused_')})
        decls = []
        for method in methods:
            body = base.rename(function(source, method), names)
            opening = body.index('{') + 1
            body = body[:opening] + '\n    TOMO_R7_PATH();' + body[opening:]
            if method == 'run_loop':
                opening = body.index('{') + 1
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
        return parse_and_dispatch<NoBorrow, BatchOps, IoPipe, TargetedIfid,
            SuppressOrdinaryActiveMark, IofusedPrivateQueue, SplitLocal>(c);
    r7::ShadowDispatch shadow_dispatch(*c);
''' + body[opening:]
                needle = 'Task t{c, rob.dispatch_id(), -1, nullptr};'
                assert body.count(needle) == 1
                body = body.replace(needle, needle + '\n            shadow_dispatch.stamp(t);')
                body = body.replace('Fused, ReadLocalDemotionPlan,', 'Fused, r7_ReadLocalDemotionPlan,')
            signature, rest = body.split('{', 1)
            decls.append(signature.rstrip() + ';')
            signature = re.sub(r' = (?:false|true|void|nullptr|0|kGenthreadExBatchOps)', '', signature)
            signature = signature.replace(' r7_' + method + '(', ' ' + owner + '::r7_' + method + '(')
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
    return '\n\n'.join(bodies) + '\n', declarations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    bodies, declarations = envelopes()
    base.update(ROOT / 'src/core/reorder.cc', bodies, args.write)
    for owner, filename in [('ExLoopT<Fused>', 'ex_loop.h'), ('IoLoop', 'io_loop.h')]:
        base.update(ROOT / 'src/core' / filename,
                    ''.join('    ' + line + '\n' for line in declarations[owner].splitlines()), args.write)
    print('R7 shadow production envelopes: current')
