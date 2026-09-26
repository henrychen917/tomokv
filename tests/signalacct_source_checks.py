#!/usr/bin/env python3
"""Serverless IO scope/idle/R7 source proofs against the frozen launch reference."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import r7shadow_sync as sync
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/signalacct-proof'


def idle_tokens(source):
    start = source.index('            Span idle(sig.idle_ns);')
    end = source.index('            self_->clear_blocked();', start) + len('            self_->clear_blocked();')
    span = re.sub(r'#ifdef TOMO_SIGNALACCT_WITNESS.*?#endif', '', source[start:end], flags=re.S)
    span = re.sub(r'//[^\n]*', '', span)
    return re.findall(r'[A-Za-z0-9_]+|[^\s{}]', span)


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    pre = ROOT / 'build/signalacct-pre'
    before = (pre / 'src/core/io_loop.h').read_text()
    after = (ROOT / 'src/core/io_loop.h').read_text()
    assert idle_tokens(before) == idle_tokens(after), 'IO idle boundaries/callback ordering changed'
    assert idle_tokens(before) != idle_tokens(after.replace('epoll_pass<HasUnix, HasTls, !SplitLocal, Pipeline>(50)',
                                                         'epoll_pass<HasUnix, HasTls, !SplitLocal, Pipeline>(0)', 1)), 'idle classification checker missed control'
    old_ex = (pre / 'src/core/ex_loop.h').read_bytes()
    new_ex = (ROOT / 'src/core/ex_loop.h').read_bytes()
    assert old_ex == new_ex, 'EX source changed'
    # The merged wbrule policy and its entire dispatch/execute/serve envelope are
    # common to PRE and POST. Accounting wraps the pass, independent of how many
    # connections Phase2 serves or defers; no cut belongs inside that walk.
    wb = (ROOT / 'src/core/wb_rule.h').read_bytes()
    assert wb == (pre / 'src/core/wb_rule.h').read_bytes(), 'merged writeback policy changed'
    assert sync.function(before, 'flush_ready') == sync.function(after, 'flush_ready')
    loop = sync.function(after, 'run_loop')
    assert loop.count('tenure.pass()') == 1 and loop.count('tenure.finish(') == 1
    assert loop.index('tenure.pass()') < loop.index('Server::DatabaseWorkScope')
    assert loop.index('tenure.finish(') > loop.index('self_->clear_blocked();')
    assert 'sweep<HasUnix, HasTls, kEp, Fused, SplitLocal>()' in loop
    assert b'kGenthreadWbBatchConns' not in (ROOT / 'src/core/genthread_pipeline.h').read_bytes()
    old_r7, new_r7 = ((root / 'src/core/reorder.cc').read_text() for root in (pre, ROOT))
    for name in sync.base.EX:
        qualified = 'ExLoopT<Fused>::r7_' + name
        def body(source):
            assert source.count('uint32_t ' + qualified + '(') == 1
            return sync.base.function(source.replace('uint32_t ' + qualified, 'void ' + qualified), qualified, False)
        assert body(old_r7) == body(new_r7), name
    subprocess.run([sys.executable, 'tests/r7shadow_sync.py'], cwd=ROOT, check=True)
    dest = OUT / 'r7-stale-control'
    for relative in ('src/core/io_loop.h', 'src/core/ex_loop.h', 'src/core/reorder.cc',
                     'src/core/genthread.cc', 'tests/r7shadow_sync.py', 'tools/reorder_sync.py'):
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    p = dest / 'src/core/reorder.cc'
    s = p.read_text()
    assert s.count('self_->sample_depth(pass_ns / 1000)') == 1
    p.write_text(s.replace('self_->sample_depth(pass_ns / 1000)', 'self_->sample_depth(pass_ns / 1001)', 1))
    r = subprocess.run([sys.executable, 'tests/r7shadow_sync.py'], cwd=dest, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert r.returncode != 0 and 'stale R7 envelope' in r.stdout, r.stdout
    (dest / 'check.log').write_text(r.stdout)
    rows = dict(idle_tokens_equal=True, idle_timeout_control='REJECTED',
                wb_policy_sha256=hashlib.sha256(wb).hexdigest(), wb_phase2_envelope_equal=True,
                consecutive_cuts='entry, pass before DatabaseWorkScope, final before teardown; unchanged by wbrule',
                sweep_dispatch='SplitLocal propagated; only physical fused threads use wb_rule',
                ex_source_sha256=hashlib.sha256(new_ex).hexdigest(), generated_ex_methods_equal=len(sync.base.EX),
                r7_parity=True, stale_sampling_control='REJECTED',
                sampling_site='self_->sample_depth(pass_ns / 1000)', auto='retired at 63117343f, absent at launch')
    (OUT / 'source-proof.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
