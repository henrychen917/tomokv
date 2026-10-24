#!/usr/bin/env python3
"""Use the existing strict linked-body checker against this lane's frozen PRE."""
import importlib.util
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('wave4_identity', ROOT / 'docs/wave4/identity.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
audit.OUT = ROOT / 'build/dispatchfix-identity'
pre = audit.inventory(ROOT / 'build/tomokv-PRE')
post = audit.inventory(ROOT / 'build/tomokv')
rows = audit.compare(post, {'headline': pre})
changed = [r for r in rows if not r['equal']]
for r in changed:
    name = r['name'].lower()
    if any(x in name for x in ('acl_', 'aclselector', 'aclpermimage', 'acluser', 'cmd_acl', 'command_metadata_index', 'command_metadata_subcommand')):
        reason = 'ACL subcommand/first-argument grants, DRYRUN, immutable image copies, and rule rendering/replay.'
    elif any(x in name for x in ('xgroup', 'xinfo', 'stream_subcommand', 'cmd_client', 'object_impl', 'cmd_latency', 'command_reply_subcommand', 'command_validate_subcommand', 'auth_arity_reply', 'cmd_script', 'cmd_function', 'pubsub_reply_bad_subcommand')):
        reason = 'Assigned dispatch/container compatibility behavior and its inlined handler helpers.'
    elif any(x in name for x in ('snapshot_load', 'snapshot_read', 'snapshotmanager::write_header', 'snapshotmanager::submit_header', 'aof_load', 'aof_read', 'aofmanager::init', 'aofmanager::bind_writer', 'aofmanager::write_header', 'seed_from_snapshot', 'recoverysections', 'legacy_recovery', 'server::init')):
        reason = 'Balanced routing and versioned legacy persistence recovery/upgrade on the cold boot/load path.'
    elif any(x in name for x in ('ioloop', 'exloopt')):
        reason = 'Compiler/inlined-callee propagation from the shared PUBSUB error formatter; changed hot instructions remain visible for merit. No claim of byte identity.'
    else:
        reason = 'Unedited body: compiler propagation or link/layout change from the changed translation units; retained for merit review, not claimed identical.'
    r['reason'] = reason
out = ROOT / 'docs/dispatchfix/identity'
out.mkdir(parents=True, exist_ok=True)
with gzip.open(out / 'all-bodies.json.gz', 'wt') as f:
    json.dump(rows, f, indent=2)
(out / 'changed-bodies.json').write_text(json.dumps(changed, indent=2) + '\n')
(out / 'changed-bodies.md').write_text('\n'.join([
    '# PRE to POST body inventory', '',
    'Existing reorder_noop strict normalization, including literal pools; clone multiplicity retained.', '',
    '| Body | PRE bytes | POST bytes | Reason |', '|---|---|---|---|',
    *[f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in changed]]) + '\n')
summary = dict(total=len(rows), equal=sum(r['equal'] for r in rows), changed=len(changed),
               hot=sum(r['hot'] for r in rows), hot_equal=sum(r['hot'] and r['equal'] for r in rows),
               command_hot=sum(r['command_hot'] for r in rows),
               command_hot_equal=sum(r['command_hot'] and r['equal'] for r in rows),
               changed_hot=[r for r in changed if r['hot']],
               changed_command_hot=[r for r in changed if r['command_hot']],
               pre_sha256=pre['sha256'], post_sha256=post['sha256'])
(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, list)}), flush=True)
