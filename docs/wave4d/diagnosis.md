# wave4d: call-site diagnosis and selected source change

The incoming merge is the frozen ELF with SHA-256
`3dfe9e510917cc12e320e6e31ca9f22f8ac498c2e5353ce162ff273b2f01f8e5`.
POST is `766c7d5ec868836fba7dba00f1f52722b763db6bb16539773c1bb2daeca7aa04`.
Only `Server::lb_forget_client` gains `[[gnu::noinline]]` in production source.
No source behavior, struct field, lane fix or compiler budget changes.

## Every residual command group

`call-sites.json.gz` records every direct/indirect call and external tail site,
with offsets and multiplicity, for all ten groups against both frozen references.
`call-differences.json` records all changed targets. `call-frames.json` adds the
DWARF inline chains and source locations for the differing direct calls.
These use the gate normalizer unchanged; they do not normalize away opcodes,
branch predicates, registers, source-line constants or clone multiplicity.

| Incoming residual | Headline / moverfix call-site result | Attribution / POST result |
|---|---|---|
| Normal `cmd_xshard_only_impl<false>` | No callee or instruction-encoding difference | Compiler switch-table serial / anonymous reference only; unchanged |
| Normal `cmd_xshard_only_impl<true>` | No callee or instruction-encoding difference | Same; unchanged |
| DB0 `cmd_xshard_only_impl<false>` | No callee or instruction-encoding difference | Same; unchanged |
| DB0 `cmd_xshard_only_impl<true>` | No callee or instruction-encoding difference | Same; unchanged |
| Normal `store_xstring_selected` | No callee or instruction-encoding difference | Anonymous scalar reference only; unchanged |
| DB0 `store_xstring_selected` | No callee or instruction-encoding difference | Same; unchanged |
| DB0 `xshard_execute` | Mutex outline versus moverfix; intentional mover extraction and rename inline versus headline | Whole POST body strictly equals moverfix, 23,221 bytes |
| DB0 `xshard_execute.cold` | Same callees as moverfix; changed landing-pad shape; headline additionally has the old mover guard destructor | Whole POST fragment strictly equals moverfix, 383 bytes |
| Normal armed `cmd_set_prebuilt<true>` | One `FlatStore::deadline(...)[.isra.0]` call becomes inline | Already in compat2; clockcut adds seven branch changes; both fixes retained |
| DB0 armed `cmd_set_prebuilt<true>` | Two `KvObj::key()` calls become outlined | Already in compat2's inlined `FlatStore::erase_notify`; clockcut adds seven branch changes; both fixes retained |

The six encoding-identical groups remain **strict residuals**. Wave4c's retained
literal-byte proof applies because these bodies were not changed here. Restoring
compiler label serials is not an absent inline optimization. The two armed SET
bodies cannot equal either old reference without removing a correctness change:
compat2's overwrite-expiry observation guard (`03587ed8d` / `6226f7216`) changes
`FlatStore::find_notify` and the inlined armed SET/erase context, while clockcut
changes the absolute-deadline comparisons. Neither body executes MGET.

## Complete DB0 scatter call differences

Relative to moverfix, the only changed inline decision is
`std::mutex::lock()` in SWAPDB's shape-transition lock. The merged body calls it;
moverfix inlines it and directly calls `pthread_mutex_lock` and
`std::__throw_system_error`. The merged layout also has one fewer direct
`__stack_chk_fail` site. Exception branches target different offsets in the cold
fragment, whose call targets are otherwise unchanged. The incoming sizes are
23,183 / 380 bytes versus moverfix's 23,221 / 383.

Relative to headline, all remaining call differences are already present in
moverfix POST. Moverfix (`65897a111`, following `f7f3ce7a5`) extracts the source
claim paths into `xshard_movers.inc`: `execute_live_pop` and
`execute_plain_element_mover` are now outlined `.isra.0` calls. The headline's
inline mover/pop paths had the following direct calls, which consequently leave
the parent body (counts are net differences):

| Callee leaving the parent | Count | New location / source cause |
|---|---:|---|
| `ensure_result` | 2 | Live pop and element mover helpers |
| `FlatStore::atomic_needs_version` | 1 | Element mover source-claim/version path |
| `begin_plain_version[.constprop.0]` | 1 | Same |
| `xshard_remove_list_element` | 1 | Element mover helper |
| `xshard_remove_set_element` | 1 | Same |
| `xshard_push_list_element` | 1 | Same |
| `xshard_insert_set_element` | 1 | Same |
| `FlatStore::ForeignReadKeyGuard` constructor | 1 | Same |
| `FlatStore::ForeignReadKeyGuard` destructor | 1 main + 1 cold | Same, including exception cleanup |
| `xshard_pop_zset` | 1 | Live pop helper |
| `xshard_pop_list` | 1 | Same |

That extraction changes the parent/inliner budget. The unchanged
`execute_atomic_direct_rename` body is now inlined rather than called, exposing
these direct callees in `xshard_execute`:

| Callee exposed by rename inline | Count |
|---|---:|
| `group_for` | 1 |
| `FlatStore::find` | 1 |
| `KvObj::str_value` (through `kvobj_string_value`) | 1 |
| `xshard_make_string` | 1 |
| `execute_atomic_apply[.isra.0]` | 2 |
| `serialize_object` | 1 |
| `kvobj_free[.part.0]` | 1 |
| `load_object_image` | 1 |
| `mallocx` (through `kvobj_new_int` / `alloc_raw`) | 1 |
| `kvobj_init_int[.isra.0]` | 1 |

The two extra apply sites are calls exposed by the inlined rename helper, not
additional MGET work. The call inventory also retains every changed main/cold
branch destination; these are landing-pad references, not missing callees.

## Why notification source changes the mutex decision

`notify.inc` is part of the same `xshard.cc` translation unit. Notifyorder commit
`f026db036` grows physical-event routing (`notify_record_physical_slow`,
`notify_keep_physical`, and their callers). In the merged DB0 final IPA graph,
`std::mutex::lock` has two callers: `xshard_execute` (estimated frequency 0.00,
SWAPDB) and `Server::lb_forget_client` (0.03, connection teardown). GCC considers
but does not perform the latter late inline, leaving two callers and preventing
the called-once inline into SWAPDB. This is a transitive inliner decision, not
an outline of MGET's group read or completion helper.

`notify-attribution.json` retains a compile-only counterfactual using
`notify.inc` before `f026db036`, at the same budgets: the mutex becomes an inline
copy in `xshard_execute` again. That counterfactual is not executed or delivered.
The frozen moverfix body and DWARF chains distinguish its intended mover changes
from this additional merge decision.

Eleven source trials and twelve subsequent cold-helper budget trials are retained
in `source-trials.json`, `source-trial-scores.json`, and `cold-budgets.json`.
Notification-only `noinline` trials did not restore the target; cold attributes
changed other decisions without matching it. `noinline,flatten`, `flatten` alone,
and `noinline` alone on teardown restore both DB0 targets. The selected change is
`noinline` alone: one attribute, no new hot work, existing budgets. The full
production rebuild confirms both complete bodies in `restoration.json`.

## MGET reachability and propagated output

For MGET, the local command lookup/reply loop has no changed calls. The scatter
path performs its group read via the existing gather specializations and existing
completion paths. The SWAPDB lock, mover/pop helpers, rename path and armed SET
are not executed by this command. POST's DB0 gather `<true,false>` has a
register-allocation change that exactly matches notifyorder; this does not add a
call or an instruction to the ordinary gather scope. Full gather/completion bodies
are retained in `identity/command-bodies.json.gz`.

The restored whole scatter body can change placement and instruction-cache
behavior of MGET. This is a candidate explanation to measure, not proof that the
reported throughput loss has disappeared. The bounded diagnostic observes ordinary
per-command gather counts of 3724 on headline and 3700 on moverfix, merge and POST;
ordinary completion is 446. Tiny observed per-batch variants are retained, not
rounded into an identity claim. Preparation and retirement include allocator and
scheduling-dependent branches. No rate is inferred from these counts.

The whole-program consequence is explicitly broader than the two target bodies:
full strict residuals rise 113 to 177, while command residuals drop 10 to 8 and
historical hot residuals stay 17. Of 98 changed groups, 69 retain every instruction
encoding and change references, 27 change instruction encodings, and two are the
new out-of-line teardown symbols. Among previously matched groups, 64 become
residual (51 reference-only, 13 instruction changes). The two restored DB0 groups
and two new teardown groups account for the residual-total balance. No previously
matched historical hot group loses its reference match. Real propagation includes
ACL/notification/cold helper changes and three already-residual parser groups;
these are not hidden or declared harmless by the hot inventory. Exact diffs,
names and old/new reference matches are in `identity/propagation.json` and its
compressed diff companion. Maintainer controls must cover single-key commands,
notification-enabled work, and both thread modes as well as the target MGET cells.
