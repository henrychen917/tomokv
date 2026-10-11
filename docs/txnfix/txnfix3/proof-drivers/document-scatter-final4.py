import json,pathlib
root=pathlib.Path('docs/txnfix/txnfix3')
inventory=json.loads((root/'scatter-all-final4/inventory.json').read_text())
details={(r['object'],r['symbol']):r for r in json.loads((root/'scatter-all-final4/changed-details.json').read_text())}
reasons={(r['object'],r['symbol']):r['reason'] for r in json.loads((root/'identity-final4/full/changed-bodies-with-reasons.json').read_text())}
rows=[]
for original in inventory['functions']:
 r=dict(original);d=details.get((r['object'],r['symbol']),{})
 r['instruction_bytes_equal']=r['equal'] or d.get('canonical_instruction_bytes_equal',False)
 r['review']='Canonical instruction bytes and named relocations equal.' if r['equal'] else reasons.get((r['object'],r['symbol']),'Changed emitted body; universal ordinary-path sequence identity is not established.')
 rows.append(r)
(root/'scatter-all-final4/function-review.json').write_text(json.dumps(rows,indent=2)+'\n')
counts=json.loads((root/'final4-path-counts.json').read_text())
assert counts['cases']==264 and not counts['invalid'] and not counts['cases_with_increases'] and not counts['cases_entering_group_helpers']
text='''The null-attempt destructor tax is removed by design. Both namespaces have PRE-identical constructor, destructor and `xshard_destroy` bodies, including all branches. Dispatch-shard lookup is also identical. No new attempt-pointer load/test/branch executes there.

The broader literal requirement—identical executed sequences on **every** ordinary scatter path—is **not established**. Final production-object traces cover 264 matched cases with no per-function instruction increase and no group-helper entry. This is bounded evidence, not universal sequence identity. Compiler placement changes ordinary sequences; corrected atomic-0 movers intentionally differ from broken PRE.

PRE is `origin/cpp` 991d48f65, SHA-256 `5ba1240a65745fadec59d54551f9f1c1f25a6f9c8c3f9db5bba27c90031ceb20`. POST runtime source is `e904cd285`, SHA-256 `1c808efda63159b31e45e7e960053052b8ac6cd3345049dc23e857bd3da845cc`. Fixtures link optimized production objects without changing their compiler flags. Every final pair uses CPUs 112–119, giving both arms eight available CPUs, 16 shards, and 6:2 split geometry (or eight fused threads).

| Entry | Existing predicate containing the new work | Ordinary path |
|---|---|---|
| `ScatterState` construction/destruction | None needed: attempt pointer has no initializer/destructor action | Complete bodies match PRE |
| `xshard_prepare` | `atomic_group && !force_atomic`, already used for group AOF setup | False skips attempt setup; no new predicate |
| `xshard_task_should_defer` | `atomic_direct` | False skips group arrival |
| `xshard_execute` | `atomic_apply` / `atomic_write` | False skips group reads/intents; mover phase two intentionally changes |
| `xshard_complete_impl<false/true>` | `atomic_write || atomic_apply` | False skips attempt lookup and group completion |
| `xshard_retire` | `atomic_group` | False skips debug witness |
| `xshard_destroy` | Existing `record_refs || watch_refs` | Complete body matches PRE |
| `ScatterArenaPool::reap_deferred` | Existing nonzero `record_refs || watch_refs` | Zero-reference states skip attempt cleanup |

Attempt ownership is bit 31 of existing `watch_refs` at offset 0x18. Its uninitialized pointer occupies old padding at 0x310. Only a group sets these on preparation. Release requires zero record refs and exactly the ownership bit, so live intent/watch pins still prevent destruction. Ordinary zero-reference states never read the pointer. This repair introduces no reader retry, seqlock or ordinary allocation.

The MGET trace includes named scatter/state functions and selected outlined helpers; other callees are stepped over. These are **not instructions/op, cycles/op or rates**. Executed NOPs count. Each named function is checked separately; reductions elsewhere cannot hide an increase. Raw data is in `scatter-final4/`; `final4-path-counts.json` pairs every fixture and retains failures if any.

| MGET function (two-fragment missing-value operation) | Normal PRE / POST | DB0 PRE / POST |
|---|---:|---:|
'''
selectors=['ScatterState::ScatterState()','ScatterState::~ScatterState()','xshard_dispatch_shard(','xshard_task_should_defer(','xshard_prepare(','xshard_execute(','ScatterFinish ','xshard_retire(','xshard_destroy(']
for key in selectors:
 vals=[]
 for ns in ('normal','db0'):
  c=next(r for r in counts['rows'] if r['receipt'].endswith('/scatter-final4') and r['namespace']==ns and r['mode']=='2s' and r['shape']=='missing')
  funcs=[f for f in c['functions'] if key in f['name'] and 'lambda' not in f['name']]
  assert len(funcs)==1,(key,funcs)
  f=funcs[0];vals.append(f"{f['pre']} / {f['post']}")
 label='xshard_complete_impl<false/true>' if key=='ScatterFinish ' else key.rstrip('(')
 text+='| `'+label+'` | '+' | '.join(vals)+' |\n'
text+='''
Both mode instantiations agree in these fixtures. Named-function missing-value totals are 3027 → 2995 (normal), 3087 → 3017 (DB0); present totals are 3101 → 3069 and 3159 → 3089. No performance gain is inferred.

| Matched coverage | Pairs | Final result |
|---|---:|---|
| Complete missing/present MGET, both namespaces/modes | 8 | No per-function increase; no group helper |
| Preparation: 45 valid shapes, both namespaces/modes | 180 | No per-function increase; no group helper |
| Complete empty-input execution: 17 shapes, both namespaces/modes | 68 | No per-function increase; no group helper |
| KEYS/RANDOMKEY first-shard scan continuations, both namespaces/modes | 8 | No per-function increase; no group helper; full reply checked after tracing |

Preparation covers MSET/MSETNX, algebra and stores, movers, multi-pops, SORT/dereference, geo stores, streams, all-shard scans and flushes. The complete read matrix covers MGET, EXISTS, set/zset algebra, cardinalities, LCS, PFCOUNT, XREAD, TOUCH, DEL and UNLINK on empty input. It does not turn empty input into coverage of populated/error/large-value paths.

Broader execution tracing found a real counterexample after the preparation repair: normal set/zset algebra and LCS cost two extra instructions per two-fragment operation. `read-certified/` retains all 18 failing pairs. They were real jumps/register-placement changes, not ignored NOPs. The constructor-only read-epoch binding hint in `e904cd285` restores normal SINTER 450/450, ZUNION 468/468 and LCS 440/440; all nine affected forms pass both modes. DB0 also has no increase. The constructor-plus-destructor hint trial was rejected and remains in `read-bound-both/`. Its trial receipts are not substituted for the final paired eight-core results.

The scan fixture originally assumed one execute call completed KEYS/RANDOMKEY; that was false. The rejected fixture and 20,000-step exhaustion receipts remain under `read-certified/`. `probe-scan.cc` now accepts only actual cursor `Retry` continuations, requires at least one, and retains exact final empty-array/nil assertions after all 16 shards finish. Only first-shard execution is traced. The trace steps over `FlatStore::scan_home<xshard_execute...>` after verifying exact canonical PRE/POST equality in both namespaces; caller call instructions still count. `scan-final4/identical-skipped-helpers.json` records that check. Both arms have 1024-slot empty stores and identical scan arguments. No production-test assertion was changed for this fixture correction.

The scan's counted prefixes are KEYS 87192 → 86157 and RANDOMKEY 87148 → 86113 (normal); DB0 87196 → 86161 and 87152 → 86117. Those numbers exclude the identical scan helper and the untraced remaining shards; they are not whole-operation counts.

Earlier DB0 preparation counterexamples (SORT STORE, KEYS, FLUSHDB/ALL) remain in `prepare-release/`. Existing group-branch placement repaired those without changing any selected hot body. Invalid preparation fixtures for local-only INFO/DBSIZE and unsupported XREADGROUP forms also remain labelled as fixture failures. No production assertion was weakened.

The disassembly corpus contains **386 emitted scatter/state-helper bodies: 281 canonically equal, 105 changed**. The constructor and destructor each have complete canonical equality, including all emitted clones. `finish_phase1`, `assemble_final`, `xshard_aof_emit_local` and `notify_xshard_finished` have equal canonical instruction bytes but different unnamed read-only table relocations; the unchanged checker retains those differences. Exact targets are in `scatter-all-final4/changed-details.json`.

`scatter-all-final4/{pre,post,db0-pre,db0-post}.asm.gz` retains disassembly. `inventory.json` records object digests; `function-review.json` attributes every function, including unresolved compiler drift. Full-tree inventory is under `identity-final4`: 16656 bodies, 16077 equal, 579 changed. The checker and allowlist were not weakened. Compression manifests preserve the uncompressed trace digests.

Untraced error/exception, populated/large-value, snapshot/MVCC interactions and phase-two paths still prevent a universal proof. Preparation, execution and completion are not byte-identical. The quiet-box performance null remains unmeasured. The destructor fix and selected-hot restoration stand independently; **this report does not close goal 1's literal universal instruction-sequence bar**.

Every emitted scatter/state helper follows. Byte sizes do not substitute for executed instruction counts.

| Object | Function | PRE bytes | POST bytes | Canonically equal |
|---|---|---:|---:|---|
'''
for r in rows:text+='| `'+r['object']+'` | `'+r['name'].replace('|','\\|')+'` | '+str(r['pre_size'])+' | '+str(r['post_size'])+' | '+('yes' if r['equal'] else 'no; see attribution')+' |\n'
(root/'scatter-cost.md').write_text(text)
