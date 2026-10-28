#!/usr/bin/env python3
"""Keep every signed executed-function delta and its source/lane attribution."""
import collections, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];D=ROOT/'docs/wave9'
rows=json.loads((D/'instructions/exec-results-pre,post.json').read_text())
identity={r['name']:r for r in json.loads((D/'identity/changed-bodies.json').read_text())}
keys=('namespace','command','mode','batch','atomic','threshold');pairs={}
for r in rows:pairs.setdefault(tuple(r[k] for k in keys),{})[r['arm']]=r
MULTI=['01fabda27','297868345','56407d844'];BLOCK=['1d861ed88']
def origin(name):
 if 'multi_slowlog_' in name:return MULTI[:2], 'Multifix EXEC slowlog accumulation. start/finish bodies exactly match multifix POST; disabled threshold returns without a clock read.'
 if 'prepare_write_key' in name:return MULTI[:1], 'Multifix repeated-key version reuse; exact multifix POST body. This caller absorbs atomic_link_entry/atomic_exchange_physical instructions that disappear from their callees; signed deltas must be added together.'
 if 'atomic_entry_key' in name:return MULTI[:1], 'Multifix reuses an earlier private version for repeated keys; existing unchanged helper is called by that added reuse path.'
 if 'allocate_state' in name:return MULTI[2:], 'Multifix frozen monotonic timeout field initialization adds one instruction.'
 if 'prepare_commands' in name:return MULTI[:2], 'Multifix initializes per-child slowlog accumulation/completion fields; two added executed instructions per child.'
 if 'multi_retire' in name:return MULTI[:2], 'Multifix logical slowlog retirement adds threshold checks for each child. The headline outer latency-enabled guard remains; no histogram/latency recording callee executes in these OFF cells.'
 if 'multi_execute_task' in name:return MULTI, 'Multifix start/finish calls and commit-time IoLocal/PAUSE scan are the added source paths. Deferral of plain publication and the participant registry scan already exist in headline multi_execute.inc (99bfa38792), so they are not charged as new blockfix2 work. The caller absorbs the old atomic_commit_publish call; compiler effects around these existing paths belong to the changed slowlog/PAUSE context.'
 if 'multi_handle_io' in name:return MULTI, 'Multifix RESET/PAUSE and frozen timeout propagation alter the existing control flow/register allocation; db0 executes one extra instruction (normal two fewer).'
 if 'string_snapshot_read' in name:return BLOCK, 'Blockfix2 value-reader compilation; exact blockfix2 POST body, three extra instructions per copied value.'
 if 'kvobj_external_bytes' in name or 'KvObj::val_ptr' in name:return BLOCK, 'Blockfix2 separates retiring destruction from byte-accounting observations. New non-retiring template and val_ptr calls replace the old kvobj_external_bytes function; use their combined signed cost.'
 raise AssertionError(name)
cases=[];positive=collections.defaultdict(list)
for key,arms in pairs.items():
 a,b=arms['pre'],arms['post'];changes=[]
 for name in sorted(a['functions'].keys()|b['functions'].keys()):
  pre=a['functions'].get(name,0);post=b['functions'].get(name,0);delta=post-pre
  if not delta:continue
  r=dict(function=name,pre=pre,post=post,delta=delta)
  if delta>0:
   commits,reason=origin(name);r.update(commits=commits,reason=reason,exact_lane_matches=identity.get(name,{}).get('matches',[]));positive[name].append(delta)
  changes.append(r)
 assert sum(r['delta'] for r in changes)==b['total']-a['total']
 assert a['clock_calls']==b['clock_calls']
 assert not any('latency_tracking' in n or 'histogram' in n.lower() for n in b['functions'])
 cases.append(dict(zip(keys,key),pre=a['total'],post=b['total'],delta=b['total']-a['total'],clock_calls=b['clock_calls'],changes=changes))
notes=['Scope counts are executed instructions in named production tomo/tomo_db0 routines, including NOPs; external libraries and fixture glue are excluded equally.',
 'Every positive function delta is attributed below. Inlined/caller compiler effects have joint source attribution where the lanes share a body; this is not a claim that compiler causality can be uniquely apportioned instruction by instruction.',
 'Integration preserved the headline timing-selected multi_execute body and outer retirement guard. Its only additional C++ API adaptation passes zero to the newer slowlog_record signature on the enabled slowlog path, absent from these OFF traces. No new integration-only runtime check was added.',
 'The 96 PC traces independently reproduce every EXEC total and function count exactly. Compressed executed-pcs and inline source maps are in instructions-pc; these support review of each executed address, beyond the function ledger.',
 'Read-local has zero added instructions and identical per-function counts in all four cells; there is no positive read-local delta to attribute.']
(D/'exec-attribution.json').write_text(json.dumps(dict(notes=notes,cases=cases),indent=2)+'\n')
lines=['# Executed EXEC instruction attribution','',*['- '+n for n in notes],'','| Function | Positive deltas across cells | Lane commits / reason |','|---|---:|---|']
for name,values in sorted(positive.items()):
 commits,reason=origin(name);lines.append(f"| `{name}` | {', '.join(map(str,sorted(set(values))))} | {', '.join(commits)}: {reason} |")
lines+=['','All signed contributions, including removed callees and reduced repeated-key work, sum exactly to each PRE/POST delta in [exec-attribution.json](exec-attribution.json). This is a command-scope cost proof, not a throughput result.']
(D/'exec-attribution.md').write_text('\n'.join(lines)+'\n')
print(len(cases),'cases;',len(positive),'positive functions; every signed sum checked')
