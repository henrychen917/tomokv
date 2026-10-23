import json,pathlib
root=pathlib.Path('docs/txnfix/txnfix3')
j=json.loads((root/'scatter-all-certified/inventory.json').read_text());detail=json.loads((root/'scatter-all-certified/changed-details.json').read_text());details={(r['object'],r['symbol']):r for r in detail}
reasons=json.loads((root/'identity-certified/full/changed-bodies-with-reasons.json').read_text());reasons={(r['object'],r['symbol']):r['reason'] for r in reasons}
rows=[]
for r in j['functions']:
 r=dict(r);d=details.get((r['object'],r['symbol']),{})
 r['instruction_bytes_equal']=r['equal'] or d.get('canonical_instruction_bytes_equal',False)
 r['review']='Canonical instruction bytes and named relocations equal.' if r['equal'] else reasons.get((r['object'],r['symbol']),'Changed emitted body; universal ordinary-path sequence identity is not established.')
 rows.append(r)
(root/'scatter-all-certified/function-review.json').write_text(json.dumps(rows,indent=2)+'\n')
text='''The null-attempt destructor tax is removed by design. Both namespaces have PRE-identical constructor, destructor and `xshard_destroy` bodies, including all branches in those bodies. Dispatch-shard lookup is also identical. No new attempt-pointer load/test/branch executes there.

The broader literal requirement—identical executed sequences on **every** ordinary scatter path—is **not established**. The evidence below is deliberately narrower. Compiler placement changes ordinary sequences; finite samples with fewer instructions do not prove all paths. Corrected atomic-0 mover paths intentionally do different work from broken PRE.

PRE is `origin/cpp` 991d48f65, binary SHA-256 `5ba1240a65745fadec59d54551f9f1c1f25a6f9c8c3f9db5bba27c90031ceb20`. Final POST SHA-256 is `c879e3f1e476b5f86232e47f863565d5b967905617b1dabf3ca1a961628e4916`. Both use the normal optimized production recipes. The fixtures link those production objects; no object is rebuilt with fixture-specific optimization flags.

| Entry | Existing predicate containing the new work | Ordinary path |
|---|---|---|
| `ScatterState` construction/destruction | None needed: attempt pointer has no initializer/destructor action | Complete bodies match PRE |
| `xshard_prepare` | `atomic_group && !force_atomic`, already used for group AOF setup | False skips attempt setup; no new predicate |
| `xshard_task_should_defer` | `atomic_direct` | False skips group arrival |
| `xshard_execute` | `atomic_apply` / `atomic_write` | False skips group read/intents; mover phase two is an explicit correctness change |
| `xshard_complete_impl<false/true>` | `atomic_write || atomic_apply` | False skips the attempt lookup and outlined group completion |
| `xshard_retire` | `atomic_group` | False skips the debug witness |
| `xshard_destroy` | Existing `record_refs || watch_refs` | Complete body matches PRE |
| `ScatterArenaPool::reap_deferred` | Existing nonzero `record_refs || watch_refs` | Zero-reference states skip attempt cleanup; the empty reaper and unchanged acquire path remain part of the ordinary path |

Attempt ownership is bit 31 of existing `watch_refs` at offset 0x18. The uninitialized pointer occupies pre-existing padding at 0x310. A real group sets both on its cold prepare path. Release requires zero record refs and exactly the ownership bit (no live watch/intent pins). The pointer is never read for an ordinary zero-reference state. No reader retry, seqlock, or new ordinary allocation was introduced by this lifetime repair.

The eight complete MGET fixtures cover both namespaces, both modes and missing/present values. Counts include only named scatter/state functions and their selected outlined helpers; calls outside that set are stepped over. They are **not instructions/op, cycles/op, or a rate measurement**. Executed NOPs are counted. Each function's PRE/POST count is retained in `scatter-certified/counts.json`; no total is used to hide a per-function increase.

| MGET function (two-fragment operation) | Normal PRE / POST | DB0 PRE / POST |
|---|---:|---:|
| `ScatterState::ScatterState` | 91 / 91 | 91 / 91 |
| `ScatterState::~ScatterState` | 42 / 42 | 42 / 42 |
| `xshard_dispatch_shard` | 22 / 22 | 22 / 22 |
| `xshard_task_should_defer` | 96 / 96 | 96 / 96 |
| `xshard_prepare` | 1218 / 1211 | 1270 / 1227 |
| `xshard_execute` (without separately counted gather helper) | 326 / 324 | 328 / 324 |
| `xshard_complete_impl<false/true>` (without its separately counted final lambda) | 125 / 119 | 125 / 119 |
| `xshard_retire` | 76 / 76 | 76 / 76 |
| `xshard_destroy` | 81 / 81 | 80 / 80 |

Both mode instantiations agree in these fixtures. Missing-value captured totals are 3027 → 2997 (normal), 3087 → 3019 (DB0); present-value totals are 3101 → 3071 and 3159 → 3091. These reductions do not establish a performance gain or universal sequence identity.

Preparation coverage adds 45 valid command shapes × two namespaces × two modes = **180 paired cases**, including MSET/MSETNX, the set/zset algebra and stores, movers, multi-pops, SORT/dereference, geo stores, streams, all-shard scans and flushes. Every named function is non-increasing and no group helper is entered. `certified-path-counts.json` combines these with the eight complete MGET pairs (188 total). The first broader probe incorrectly expected local INFO/DBSIZE and an unsupported two-stream XREADGROUP form to produce scatter state. Those invalid fixture receipts remain under `prepare-release`/`prepare-corrected`; corrected single-stream blocking XREADGROUP has its own final eight runs. No production-test assertion was altered for these serverless fixture corrections.

The first final-cost candidate still added two instructions for DB0 SORT STORE, KEYS, FLUSHDB and FLUSHALL. The receipt is retained in `prepare-release`. The final existing-branch hint changes their preparation counts to 1278 → 1246, 1294 → 1267, and 1324 → 1297 (both flush forms). It preserves every selected hot body. Other rejected source-placement and local-alignment trials remain separate and were never adopted.

The disassembly corpus includes **386 emitted scatter/state-helper bodies: 281 canonically equal and 105 changed**. The narrower public/lifetime corpus has 222 bodies (173 equal). `finish_phase1`, `assemble_final`, `xshard_aof_emit_local` and `notify_xshard_finished` have equal canonical instruction bytes but relocated unnamed read-only tables; the unchanged canonical checker retains those as different. The exact relocation differences are retained in `scatter-all-certified/changed-details.json`. This is not an excuse to mark every changed body equal.

`scatter-all-certified/{pre,post,db0-pre,db0-post}.asm.gz` retains the complete selected disassembly. `inventory.json` records object digests. `function-review.json` gives every function its exact result and attribution, including unresolved compiler changes. The full tree inventory is separate under `identity-certified` (16656 bodies, 579 changes). The checker and allowed-handler list were not weakened.

The final ordinary-path evidence remains incomplete for untraced error/exception, large-value, snapshot/MVCC interaction and phase-two paths. In particular, byte differences in preparation, execution, completion and cold clones mean that this report cannot certify the user's literal universal identity bar. Mainline's quiet-box null is also still unmeasured. The destructor fix and selected hot equality are proven independently of that open requirement.

Every emitted scatter/state helper is listed below; byte sizes are not substituted for executed instruction counts.

| Object | Function | PRE bytes | POST bytes | Canonically equal |
|---|---|---:|---:|---|
'''
for r in rows:text+='| `'+r['object']+'` | `'+r['name'].replace('|','\\|')+'` | '+str(r['pre_size'])+' | '+str(r['post_size'])+' | '+('yes' if r['equal'] else 'no; see attribution')+' |\n'
(root/'scatter-cost.md').write_text(text)
