import pathlib,json,gzip,collections
root=pathlib.Path('docs/txnfix/txnfix3');out=root/'identity-final4'
old=json.loads(pathlib.Path('docs/txnfix/txnfix2/identity-group-park/full/changed-bodies-with-reasons.json').read_text());prior={(r['object'],r['symbol']):r for r in old}
rows=json.loads((out/'full/changed-bodies.json').read_text())
for r in rows:
 n=r['name'];key=r['object'],r['symbol']
 if any(t in n for t in ['execute_plain_element_mover','execute_live_pop','finish_phase2']):
  reason='Atomic-0 mover fix: source owners claim the current value before destination publication; multi-pops use the current owner view. This intentional correctness path differs from PRE.'
 elif any(t in n for t in ['txn_group_', 'ScatterState::group_attempt', 'txn_barrier_witness']):
  reason='Stage B group-only lifetime, dependency, completion, retry, barrier witness, or exclusive fallback helper. Group attempt ownership is tested only behind an existing group/lifetime predicate.'
 elif 'atomic_free_unit_intent' in n:
  reason='One cold cleanup call replaces the old free call; group reservation/intent pins are released before freeing. This restores the three IO-template hot bodies.'
 elif 'xshard_prepare(' in n:
  reason='Group-only preparation under the existing atomic_group predicate, plus immutable parsed-kind placement. Ordinary MGET sampled instruction counts do not increase; whole-function bytes and universal ordinary-path sequence identity are not claimed.'
 elif 'xshard_execute(' in n:
  reason='Group read setup sits under the existing atomic_apply arm. Atomic-0 element movers and multi-pops use separate corrected helpers. Register allocation and placement also differ; Matched MGET, set/zset algebra, LCS, other reads and scan continuations cover both modes and namespaces; no sampled function increases. The full universal claim remains unresolved.'
 elif 'xshard_complete_impl<' in n:
  reason='Stage B completion is outlined under existing atomic flags. Ordinary MGET completion loses six captured instructions. It is not byte-identical.'
 elif 'ScatterArenaPool::reap_deferred' in n:
  reason='Cold attempt destruction is reached only after the existing nonzero record_refs/watch_refs predicate. Ordinary scatter states have neither attempt ownership nor group pins.'
 elif 'xshard_retire(' in n:
  reason='The debug-armed MSETNX barrier witness runs inside the existing atomic_group arm. Ordinary MGET retirement has the same captured count as PRE.'
 elif 'cmd_debug_impl' in n or 'cmd_info(' in n:
  reason='Intentional cold DEBUG barrier arming and INFO transaction-counter reporting; both namespaces and cold clones are included.'
 elif key in prior:
  reason=prior[key]['reason'];r['attribution_from']='txnfix2; retained classification, not an instruction-identity waiver'
 else:
  reason='No separate behavior change is intended in this body. Shared definitions, inlining, constant propagation, or callee selection changed its emitted code. Exact ordinary executed-path identity is unresolved; this inventory does not accept it as zero-cost.'
 r['reason']=reason
(out/'full/changed-bodies-with-reasons.json').write_text(json.dumps(rows,indent=2)+'\n')
allrows=json.loads(gzip.open(out/'full/bodies.json.gz','rt').read());index={(r['object'],r['symbol']):r for r in allrows}
oldhot=json.loads(pathlib.Path('docs/txnfix/txnfix2/identity-group-park/full/summary.json').read_text())['changed_hot'];fixed=[]
for r in oldhot:
 new=index[r['object'],r['symbol']];assert new['equal'];fixed.append(dict(object=r['object'],name=r['name'],pre_size=r['pre_size'],rejected_stage_b_size=r['post_size'],post_size=new['post_size'],equal=True))
(out/'restored-hot.json').write_text(json.dumps(fixed,indent=2)+'\n')
s=json.loads((out/'full/summary.json').read_text())
readme='''The final build restores every one of the twelve selected hot drifts.
`ccfix_audit`: **1208/1208** selected hot bodies equal. `lbstall`: **601/601 +
603/603** equal. The full ccfix command still exits 1 because its narrow
non-hot-handler allowlist does not include the deliberately changed DEBUG
handler. It is retained unchanged. The only six changed handler bodies are
DEBUG and INFO (including INFO cold clones), in both namespaces.

The full inventory compares {total} emitted bodies: {equal} equal and {changed}
changed. Every changed body has an attribution in
`full/changed-bodies-with-reasons.json`. An unresolved attribution remains
unresolved; selected-hot equality does not imply whole-binary identity or
performance acceptance. No rate, IPC, or cycles/op was measured.

| Object | Function | PRE bytes | Rejected Stage B | Final bytes |
|---|---|---:|---:|---:|
'''.format(**s)
for r in fixed:readme+='| `'+r['object']+'` | `'+r['name']+'` | '+str(r['pre_size'])+' | '+str(r['rejected_stage_b_size'])+' | '+str(r['post_size'])+' |\n'
readme+='''
The three IO-template repairs retain their established compiler budgets and
restore one cleanup call by folding intent release into `atomic_free_unit_intent`.
The nine storage repairs use xshard large-unit-insns 138200 / 136800, with the
ordinary gather lambda and key-anchor cleanup kept at PRE's outlining boundary.
The final DB0 t_server budget is 31850: SCAN, RANDOMKEY, CONFIG, and all other
unrelated handlers match PRE. The rejected 31800 trial perturbed RANDOMKEY;
its separate inventory remains under `identity-placement-31800/`.

The ordinary scatter constructor, destructor and xshard_destroy are canonically
identical. The complete 386-function scatter inventory and both disassemblies
are in `../scatter-all-final4/`. MGET traces are in `../scatter-final4/`; they
execute production objects directly without workers, listeners, or a timing
instrument. Trace counts include the named scatter functions; calls into other
families are stepped over. They are not whole-operation performance counts.
The complete ordinary-path *identical sequence* claim remains unproven: a
sampled count and branch placement argument cannot establish that universal claim.
'''
(out/'README.md').write_text(readme)
