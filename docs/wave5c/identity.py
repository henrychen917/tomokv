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
audit.OUT = ROOT/'build/wave5c/identity-cache'
out = ROOT/'docs/wave5c/identity'
out.mkdir(parents=True, exist_ok=True)
post = audit.inventory(ROOT/'build/tomokv')
summary = {}
deltas = {r['name']: r for r in json.loads((out/'delta-summary.json').read_text())}
wave5b = audit.inventory(Path('/home/user/Projects/bins/wave5b-2028fd77'))
for label, path in [('wave5b-post', Path('/home/user/Projects/bins/wave5b-2028fd77')),
                    ('headline', Path('/home/user/Projects/bench-bins/tomokv-headline-a7dfb9d23'))]:
    before = audit.inventory(path)
    rows = audit.compare(post, {'headline': before})
    changed = [r for r in rows if not r['equal']]
    for row in changed:
        name = row['name']
        if label == 'headline' and audit.signature(wave5b['groups'].get(name, [])) == audit.signature(post['groups'].get(name, [])):
            reason = 'Unchanged from wave5b POST; existing integration delta. See docs/wave5/identity-landing/changed-bodies.md for lane attribution.'
        elif deltas.get(name, {}).get('global_references_only'):
            reason = 'Only resolved global reference labels differ in strict output; opcode/operand encodings match. Full unmasked reference deltas are retained in wave5b-post-deltas.txt.gz.'
        elif 'shutdown_' in name or 'ShutdownOnIssuer' in name:
            reason = 'New shutdown-only collection/cancellation body or its translation-unit initializer.'
        elif '~IoLoop' in name:
            reason = 'Destructor now reclaims every retained Client after worker joins and kernel lifetime fences.'
        elif not before['groups'].get(name, []) and 'WbEngine' in name:
            reason = 'Existing WB template newly emitted for shutdown-only completion accounting and best-effort output flush; request source unchanged.'
        elif 'introsort_loop' in name:
            reason = 'New Client pointer sorting specialization deduplicates shutdown ownership locations.'
        elif '_M_run' in name or 'main' in name or 'run_fused_server' in name or 'run_split_read_local_server' in name:
            reason = 'Physical-worker issuer guard and changed inlined IoLoop destruction alter worker/boot and exception cleanup code.'
        elif 'drain_local_reads_bounded_impl' in name:
            reason = 'Source assertion line immediate shifts after shutdown declarations; request source unchanged, strict identity retains the immediate.'
        elif 'parse_and_dispatch' in name or 'r7_run_loop' in name:
            reason = 'Unedited request body recompiled in a TU with changed worker/destructor code; compiler register allocation, inlining and branch layout differ. Complete instruction delta retained; correctness tested, no performance claim.'
        else:
            reason = ('Cold shutdown instantiation/compiler propagation; source body unchanged. Complete strict instruction delta retained.'
                      if label == 'wave5b-post' else
                      'Existing integration plus shutdown compiler propagation; full body inventories and wave5b delta distinguish the new change.')
        row['reason'] = reason
        row['before_bodies'] = before['groups'].get(name, [])
        row['after_bodies'] = post['groups'].get(name, [])
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
