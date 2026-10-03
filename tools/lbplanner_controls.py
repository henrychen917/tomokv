#!/usr/bin/env python3
"""Emit clause-deletion controls under build/. Never run a server."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('control', choices=['no-publish', 'stale-flip', 'stale-lb', 'duplicate', 'copy-on-io'])
p.add_argument('output', type=Path)
a = p.parse_args()
s = Path('src/core/lbplanner.cc').read_text()
changes = {
    'no-publish': ('lb_stage_.store(LbStage::PlanReady, std::memory_order_release);',
                   'lb_stage_.store(LbStage::Idle, std::memory_order_release);'),
    'stale-flip': ('flip_epoch() != plan.flip_epoch || ', ''),
    'stale-lb': ('lb_epoch() != plan.lb_epoch ||', 'false ||'),
    'duplicate': ('    auto& plan = *lb_plan_;\n    if (flip_dispatch_paused()',
                  '    auto& plan = *lb_plan_;\n    if (flip_dispatch_paused()'),
    'copy-on-io': ('lb_shard_moves_.swap(plan.shards);',
                   'std::vector<LbShardMove>(plan.shards).swap(lb_shard_moves_);'),
}
if a.control == 'duplicate':
    before = '    if (!lock || lb_stage() != LbStage::PlanReady || coordinator != lb_coordinator_) return false;'
    after = '    if (!lock || coordinator != lb_coordinator_) return false;\n    if (lb_stage() != LbStage::PlanReady) return true; // broken repeated consume receipt'
else:
    before, after = changes[a.control]
assert s.count(before) == 1, ('unique mutation anchor', a.control)
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(s.replace(before, after))
