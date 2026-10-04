#!/usr/bin/env python3
"""Emit clause-deletion controls under build/. Never run a server."""
import argparse
from pathlib import Path
import shutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('control', choices=['no-publish', 'stale-flip', 'stale-lb', 'duplicate', 'copy-on-io', 'record-reuse',
                                   'timing-lock', 'timing-late-pause', 'timing-budget'])
p.add_argument('output', type=Path)
a = p.parse_args()
if a.control.startswith('timing-'):
    # A source overlay keeps every include of server.h/io_loop.h on the same copy.
    # Only the unit driver is compiled here; production objects are linked after it.
    overlay = a.output.parents[2]
    shutil.copytree('src', overlay / 'src', dirs_exist_ok=True)
    io = overlay / 'src/core/io_loop.h'
    server = overlay / 'src/core/server.h'
    s = io.read_text()
    if a.control == 'timing-lock':
        old = '    LbClientMove lb_client_move() const { return lb_client_move_; }'
        assert server.read_text().count(old) == 1
        server.write_text(server.read_text().replace(old, old + '''
    bool lb_client_move_contended(LbClientMove& move) {
        std::unique_lock lock(shape_transition_mu_, std::try_to_lock);
        if (!lock || lb_stage() != LbStage::ClientDrain) return false;
        move = lb_client_move_;
        return true;
    }'''))
        old = '        const LbClientMove move = srv_->lb_client_move();\n        auto wake_source'
        new = '        LbClientMove move;\n        if (!srv_->lb_client_move_contended(move)) return 1;\n        auto wake_source'
    elif a.control == 'timing-late-pause':
        s = s.replace('    void lb_pass_begin() {',
                      '    void lb_pass_begin() {}\n    void lb_pass_begin_late() {', 1)
        old = '    uint32_t lb_control_pass() {'
        new = old + '\n        lb_pass_begin_late();'
    else:
        start = s.index('                if (!srv_->lb_acked(move.destination)) {')
        end = s.index('                if (!srv_->lb_client_move_started', start)
        s = s[:start] + '                if (!srv_->lb_acked(move.destination)) return 1;\n' + s[end:]
        old = '        if (stage == LbStage::IoDrain) {'
        new = '''        if (srv_->lb_drain_pass_expired(self_->id(), stage)) {
            lb_schedule_wake_all();
            return 1;
        }
''' + old
    assert s.count(old) == 1, ('unique timing mutation', a.control)
    io.write_text(s.replace(old, new, 1))
    raise SystemExit(0)
s = Path('src/core/lbplanner.cc').read_text()
changes = {
    'no-publish': ('lb_stage_.store(LbStage::PlanReady, std::memory_order_seq_cst);',
                   'lb_stage_.store(LbStage::Idle, std::memory_order_release);'),
    'stale-flip': ('flip_epoch() != plan.flip_epoch || ', ''),
    'stale-lb': ('lb_epoch() != plan.lb_epoch ||', 'false ||'),
    'copy-on-io': ('lb_shard_moves_.swap(plan.shards);',
                   'std::vector<LbShardMove>(plan.shards).swap(lb_shard_moves_);'),
    'record-reuse': ('if (plan.client_readers.load(std::memory_order_seq_cst) != 0) return false;',
                     '/* broken: reuse the record while a cancelled drain still has a reader */'),
}
if a.control == 'duplicate':
    before = '    if (!lock || lb_stage() != LbStage::PlanReady || coordinator != lb_coordinator_) return false;'
    after = '    if (!lock || coordinator != lb_coordinator_) return false;\n    if (lb_stage() != LbStage::PlanReady) return true; // broken repeated consume receipt'
else:
    before, after = changes[a.control]
assert s.count(before) == 1, ('unique mutation anchor', a.control)
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(s.replace(before, after))
