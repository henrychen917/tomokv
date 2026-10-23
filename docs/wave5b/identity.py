#!/usr/bin/env python3
"""Strict linked-body inventories against integrated POST and headline."""
import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('wave5_identity', ROOT/'docs/wave5/identity.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
audit.OUT = ROOT/'build/wave5b/identity-cache'
out = ROOT/'docs/wave5b/identity'
out.mkdir(parents=True, exist_ok=True)
post = audit.inventory(ROOT/'build/tomokv')
summary = {}
for label, path in [('wave5-post', ROOT/'build/tomokv-wave5b-BASE'),
                    ('headline', ROOT/'build/tomokv-wave5-PRE')]:
    before = audit.inventory(path)
    rows = audit.compare(post, {'headline': before})
    changed = [r for r in rows if not r['equal']]
    for row in changed:
        name = row['name']
        if 'flush_ready' in name:
            reason = 'WB4.1 fallback: every remaining deferred FIFO reports work; remove the previous-deferrals comparison.'
        elif 'run_loop' in name or 'Phase2' in name:
            reason = 'WB4.1 fallback propagated through the inlined writeback/pass code.'
        else:
            reason = ('Compiler/link propagation from the WB4.1 revert; no source change to this body.'
                      if label == 'wave5-post' else
                      'Wave-5 integration retained; see docs/wave5/identity-landing/changed-bodies.md for lane attribution.')
        row['reason'] = reason
    with gzip.open(out/(label+'-all-bodies.json.gz'), 'wt') as f: json.dump(rows, f, indent=2)
    (out/(label+'-changed-bodies.json')).write_text(json.dumps(changed, indent=2)+'\n')
    (out/(label+'-changed-bodies.md')).write_text('\n'.join([
        '| Body | Before sizes | After sizes | Reason |', '|---|---|---|---|',
        *[f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in changed]])+'\n')
    summary[label] = dict(before_sha256=before['sha256'], after_sha256=post['sha256'],
                         groups=len(rows), changed=len(changed),
                         main_groups=sum(r['command_hot'] for r in rows),
                         main_groups_equal=sum(r['command_hot'] and r['equal'] for r in rows),
                         main_differences=[r for r in changed if r['command_hot']])
(out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps(summary, indent=2))
