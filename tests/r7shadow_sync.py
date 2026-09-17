#!/usr/bin/env python3
"""Check/regenerate the isolated armed IO call graph; never execute a server.

This supersedes tools/reorder_sync.py for this lane: shadow dispatch must cover
split IO, fused IO, TLS, epoll, buffered reparsing, and split read-local IO.
The ordinary definitions stay unchanged except for cold role-entry selectors.
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import reorder_sync as base

IO = ('run_loop', 'sweep', 'flush_ready', 'run_split', 'admit_fd', 'adopt_client',
      'arm_tls_recv', 'collect_retire_work', 'drive_tls', 'epoll_accept', 'epoll_pass',
      'ifid_parse_hash', 'ifid_rx', 'on_accept', 'on_cqe', 'on_recv', 'on_tls_recv',
      'on_tls_socket_poll', 'parse_and_dispatch', 'pipeline_pass', 'pipeline_sweep',
      'wb_observe')


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
    bodies, declarations = [], {}
    for owner, source, methods in (('ExLoopT<Fused>', ex, base.EX), ('IoLoop', io, IO)):
        names = {name: 'r7_' + name for name in methods}
        if owner.startswith('Ex'):
            names.update(drain_tasks='r7_drain_tasks', drain_tasks_with_filler='r7_drain_tasks_with_filler',
                         exec_batch='r7_exec_batch')
        else:
            names.update({name: 'r7_' + name for name in base.EX if name.startswith('fused_')})
        decls = []
        for method in methods:
            body = base.rename(function(source, method), names)
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
    rl2s = (ROOT / 'src/core/rl2s.cc').read_text()
    split = function(rl2s, 'IoLoop::run_split_read_local_baseline', False)
    bodies.append(base.rename(split, {'run_split_read_local_baseline': 'run_split_read_local_reordered',
                                      'run_loop': 'r7_run_loop'}))
    bodies.append('template void ExLoopT<false>::r7_run();\ntemplate void ExLoopT<true>::r7_run();')
    bodies.append('namespace {\n' + function(boot, 'pin_fused_thread', False) + '\n}')
    bodies.append('static ' + base.rename(function(boot, 'run_fused_server', False),
                    {'run_fused_server': 'run_fused_server_reordered', 'run_fused': 'run_fused_reordered'}))
    bodies.append('void IoLoop::run_split_reordered() {\n'
                  '    if (srv_->cfg().overlap_enabled()) r7_run_split<1>();\n'
                  '    else r7_run_split<0>();\n}\n')
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
