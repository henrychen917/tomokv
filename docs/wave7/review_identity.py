#!/usr/bin/env python3
"""Combine fixed-hot and actually-entered body reviews, retaining strict mismatches."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];base=ROOT/'docs/wave7'
old={r['name']:r for r in json.load(open(base/'identity/changed-bodies.json'))}
rows=json.load(open(base/'identity-expanded/changed-bodies.json'))
calls={r['name']:r for r in json.load(open(base/'callsites-expanded/summary.json'))}
for r in rows:
 n=r['name'];previous=old.get(n,r)
 r['reason']=previous['reason'];r['local_clone_files']=previous.get('local_clone_files',[])
 if r['hot'] and not r['matches']:
  r['callsite_reference']='docs/wave7/callsites-expanded/summary.json'
  r['headline_callsite_delta']=calls[n]['callsites']['headline']
 if '::l4prebuild_notify_spec(' in n or '::l4prebuild_prepare_set(' in n:
  r['reason']='Integration fix: both prebuilt SET specifications initialize handler_notify to cmd_set_prebuilt<true>, so WATCH dispatch consumes the prebuilt sidecar before recording effects. Only cold specification initialization changes; the ordinary SET handler and dispatch path add no work.'
 if r['matches']:continue
 if '::cmd_set<true>' in n:
  r['reason']='Intentional composition: the three headline notify_record calls use CD4.9 actual-effect metadata; the older datafix2 POST lacks wave 6 notify_elapsed_set and instead calls Op::key plus erase_notify. The merged body retains that wave 6 elapsed-SET behavior. All other named call sites agree with headline; no plain unarmed SET body changes.'
 elif '::xshard_execute(' in n and r['counted_command_scope']:
  r['reason']='CD4.7 no-touch collection reads and CD4.9 actual-effect WATCH dispatch compose with wave 6 unique-key scans and scheduling. The shared notification-selection predicate now includes shard watches: +5/+6 instructions per ordinary fragment (normal/db0); atomic MSET has the reported additional code-generation/admission delta. Handler/expiry/script cold inlining differences remain fully listed in call-site receipts.'
 elif '::classify_keys(' in n and r['counted_command_scope']:
  r['reason']='Unchanged key-classification semantics in enlarged scatter TU. Normal runtime inlines one append_key_span call; both runtimes have changed constant-pool/branch placement. All counted paths retain the same instruction count here; actual eight-byte loads in probes are proved separately.'
 elif '::store_xstring_selected(' in n and r['counted_command_scope']:
  r['reason']='Same body size and call sites; merged constant-pool reference context differs. Every strict difference is retained; ordinary MSET instruction changes occur in xshard_execute and atomic_admit, not this selector.'
 elif '::FlatStore::hash_key(' in n and r['counted_command_scope']:
  r['reason']='All 21 local-clone occurrences retained. The db0 t_stream.cc clone changes 756 to 749 bytes by inlining its hash lambda as the other command TUs already do; the entered plain/MGET/MSET hash paths add no instructions. Stream/buffering merit remains a measurement input.'
 elif '::kvobj_external_bytes(' in n or '::kvobj_free_with_capacity(' in n:
  if r['counted_command_scope']:
   r['reason']='Unchanged instruction encodings and call targets; an unnamed relative switch-table reference is resolved against a different surrounding rodata symbol. The supplementary provenance proof checks every destination, bound branch and instruction, with mutated-table/opcode controls. Strict inventory still records the difference.'
 elif 'prepare_local_read' in n:
  r['reason']='Same instruction encodings, call sites and size. One eight-byte RIP load is named relative to cfg_shutdown_flags::values at a different offset; constant-proof.json verifies identical 0000000001000000 bytes and all other instructions. Strict inventory still records the difference.'
(base/'identity-expanded/changed-bodies.json').write_text(json.dumps(rows,indent=2)+'\n')
(base/'identity-expanded/changed-bodies.md').write_text('\n'.join(['# All changed linked-body groups','','The final selection includes every function actually entered by the 80-cell command matrix as well as the historical hot inventory. Strict opcode/register/member-offset comparison is unchanged.','','| Function | Headline bytes | POST bytes | Reason |','|---|---|---|---|',*[f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in rows]])+'\n')
(base/'identity-expanded/hot-review.md').write_text('\n'.join(['# Residual hot-body review','',f"All {sum(r['hot'] and not r['matches'] for r in rows)} residual groups and every clone occurrence are compared against all frozen references; these are not equality passes.",'','| Function | Review |','|---|---|',*[f"| `{r['name']}` | {r['reason']} |" for r in rows if r['hot'] and not r['matches']]])+'\n')
print('all changed',len(rows),'hot residual',sum(r['hot'] and not r['matches'] for r in rows))
