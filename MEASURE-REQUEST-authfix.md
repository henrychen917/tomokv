## authfix (original run)

**Authfix2 completes the ACL fix and required build, row, differential, and hot-body
checks; final results are in [authfix2](#authfix2).** Its scheduler rerun remains
deadline-failing for the mainline quiet-box landing gate.

This section retains the original run at `711cc96dc`, before the ACL integration
approval. Its POST and preview references describe those historical binaries.
Branch `cx-authfix` was based on
`5146b78ee89b64748dd46db970efa8086f653fa0`. No push, benchmark, performance
measurement, or full gate. All work and correctness processes use CPUs 112–127;
database listeners use ports 25028–25041.

The original source fixed config-line arity, carried decoded requirepass lengths
through startup CONFIG metadata/publication, and redacted SLOWLOG at capture time.
At that handoff, one bootstrap read in **acl.inc still truncated the password**
after publication. The file was reserved for aclfix, so the first run left it
untouched. The exact [two-line integration patch](docs/authfix/acl-integration.patch)
was prepared and checked with `git apply --check`; the shared-file exception was
then unanswered. Its temporary review build passed **all five new rows**, while
the original default POST still failed the two bootstrap-dependent rows.

| Finding / new gate row | PRE 5146b78ee | Original POST before ACL integration | ACL patch review arm |
|---|---|---|---|
| CG4.1 — `authfix CG4.1 binary config requirepass` | Fails: embedded NUL accepts the prefix; leading NUL permits unauthenticated SET | Fails at ACL bootstrap; CONFIG metadata now retains the bytes | Pass, both modes and both NUL positions; prefix refused, full AUTH/GET preserved |
| CG4.2 — `authfix CG4.2 missing config value refuses boot` | Fails: final missing requirepass boots without authentication; following-line arity also lost | Pass: exit 1, no listener, `wrong number of arguments` | Pass |
| SV4.2 — `authfix SV4.2 binary requirepass rewrite restart` | Fails after restart in both modes; live SET/GET/AUTH and escaped rewrite witnesses pass | Fails at the same ACL bootstrap read after restart | Pass: both NUL positions, both modes, fresh unauthenticated sockets refused before and after restart |
| SV4.1 — `authfix SV4.1 slowlog credential redaction (1s)` | Fails: 8 credential argv cases expose fixture values | Pass | Pass |
| SV4.1 — `authfix SV4.1 slowlog credential redaction (2s)` | Fails: the same 8 credential argv cases expose fixture values, including CONFIG SET | Pass | Pass |

The reproductions were run against PRE **before production edits**. Valid negative
receipts are [pre-verified/rows.json](docs/authfix/pre-verified/rows.json) and its
five failing logs. [POST receipts](docs/authfix/post/rows.json) retain both the
candidate and Redis oracle checks, including the two still-failing rows.
[Review-arm receipts](docs/authfix/acl-preview/rows.json) prove the prepared ACL
patch closes those remaining failures. Each row completes well below 60 seconds.

`tests/authfix.py` adapts the in-scope witnesses from config-gate T5/T9 and
cmd-server T1/T2/T5. It keeps positive AUTH, CONFIG GET, persistence, execution,
capture-presence and oracle checks; it does not claim to rerun the unrelated
parts of the original 117-assertion audit verifier. Missing slowlog entries fail
after bounded retries on a freshly reset log. Ordinary SET arguments containing
the fixture password stay visible, so value-based blanket masking cannot pass.
Redis 7.4.10 also hides the **user name** in ACL SETUSER; the test and capture
follow that observed rule. MIGRATE has no registered TomoKV handler.

Files: [config.h](src/core/config.h) retains per-line boundaries and token lengths,
rejects omitted values, and uses four reserved tail bytes for the boot length;
[main.cc](src/main.cc) changes only config-token handling;
[t_server.cc](src/cmd/t_server.cc) uses the full boot Slice for CONFIG metadata and
auth publication; [slowlog.cc](src/cmd/slowlog.cc) masks the diagnostic copy before
truncation, without changing execution argv. Parser assertions are in
[config_parser_test.cc](tests/config_parser_test.cc); the live rows, labels and
collection are in [authfix.py](tests/authfix.py), [gate.sh](tests/gate.sh) and the
[ledger fixture](tests/fixtures/nullrefresh-ledger-labels.json).

Other `next("")` directives and Redis 7.4 outcomes, each actually probed with a
value-less config line:

| Directives | Redis 7.4 result |
|---|---|
| `tls-cert-file`, `tls-key-file`, `tls-ca-cert-file`, `tls-ca-cert-dir`, `tls-protocols`, `tls-ciphers`, `tls-ciphersuites`, `unixsocket`, `aclfile`, `latency-monitor-threshold` | Exit 1, no listener, `wrong number of arguments` |
| `ratio`, `shard-home`, `place` | Exit 1, no listener, `Bad directive or wrong number of arguments`; these are Tomo-only names |

[Per-directive PRE/POST/oracle outcomes](docs/authfix/empty-defaults.json) distinguish
PRE settings that silently defaulted from those already rejected later by value
validation. The row also covers the nonempty default paths `dir`, `dbfilename`,
`appendfilename`, and `appenddirname`. The parser unit checks missing values both
at EOF and before another directive, repeated save clauses, binary passwords,
CLI overrides, explicit empty passwords, and a missing CLI requirepass value.

**Gate accounting:** DQ **+5**, DF **+5**. `collect_job authfix` is at
`tests/gate.sh:3378`, before the quick exit beginning at line 3445. Required owner
values are **511 + 5 = 516 quick**, **528 + 5 = 533 full**. The arithmetic comment
is above the existing assignments; neither EXPECT constant was edited.
`python3 tests/gate_ledger_fixture.py` currently **refuses** the unchanged 528
count, with no missing or extra labels: fixture and source both have 533 rows.
The unmodified checker passes when supplied an in-memory copy with the proposed
owner count; that is a projected check, not a passing receipt for the current
file. [Current refusal](docs/authfix/ledger-current.log),
[count accounting](docs/authfix/ledger.json).

| Binary | SHA-256 |
|---|---|
| PRE `build/authfix/pre/tomokv` | `4661985986b2f31f08bd62f146ba21d5133e0a3288b042920ae7fba5684414d4` |
| Default POST `build/tomokv` | `3b689290c66d46797da49c1ef0d11568528b63ab611d5580e89cb367a8e9fc1d` |
| Unapplied ACL patch review `build/authfix/acl-preview/tomokv` | `cdbd4f1c7d7b3f4b7277e74138bba3334fbddf0c750f15abc0a256e0f6785492` |

The review arm copies acl.cc/acl.inc under build/, applies only the two proposed
changes, retains source line names, compiles both namespaces with the ordinary
ACL Makefile flags, and substitutes those two objects in the default link order.
[Exact compiler/link commands](docs/authfix/acl-preview-build.json).

**Default PRE versus default POST byte inventory** (unmodified project checkers):

| Check | PRE | POST / result |
|---|---:|---:|
| Production object inventory | 100 | 100 |
| Selected hot bodies, `tomo` | 601 | 601 identical |
| Selected hot bodies, `tomo_db0` | 603 | 603 identical |
| Full inventory's hot selection, including executor run bodies | 1,208 | 1,208 identical |
| Command-handler entries | 1,210 | 1,206 identical; CONFIG in both namespaces and DB0 INFO/its cold clone differ |
| Full body comparison entries, union of symbols | 16,304 | 16,252 identical; 52 added/removed/changed entries |
| Linked `.text`, bytes | 7,582,188 | 7,590,060 (+7,872) |

There are **no changed bodies in either checker's hot selection**. The broader
inventory also records code-generation changes in unchanged command helpers,
which must remain visible to the performance review:

| Additional emitted command helper | PRE bytes | POST bytes | Reason |
|---|---:|---:|---|
| `tomo::classify_keys` in xshard | 990 | 945 | Unchanged helper source; compiler output changed after the Config definition changed |
| `tomo::normalize_multi_blocking_pop` | 3,308 | 3,326 | Same |
| `tomo::prepare_sort_deref` lambda | 3,702 | 3,686 | Same; its cold clone also has a relocation difference |
| `tomo::FlatStore::random_live` emitted by t_server | 3,413 | 3,269 | Unchanged helper source; compiler output changed in the edited translation unit |

The complete 52-entry list also identifies client metadata/migration helpers,
memory-accounting helpers, pubsub NUMSUB helpers, startup/parser/Config bodies,
CONFIG/INFO bodies and the two slowlog functions. These are recorded differences,
not an assertion that every request-path helper is identical or that every weak
definition wins the final link. [Full changed-body list](docs/authfix/full/changed-bodies.json),
[full summary](docs/authfix/full/summary.json),
[hot inventory](docs/authfix/hot.json), [linked sections](docs/authfix/linked.json).
The linked-image checker exits 1 because runtime sections differ; no complete
runtime-image identity is claimed. No compiler budgets were changed.

All eight layout locks pass in both namespaces: Op 336, Client 1984, ThreadCtx
1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. Existing
non-padding field offsets remain fixed. Config's reserved tail starts at byte
584 instead of 580, leaving 40 spare bytes after the new length word.
[Full layout receipt](docs/authfix/layouts.json).

Proof on the committed default POST:

- PRE and POST `make -j16 all`: pass. All 28 `job_production_units` targets:
  build pass and **28/28 make -q freshness checks pass**, including netcmd-unit.
  Both `mdbqsbr-live-arms` binaries also built successfully.
- Config parser unit and `tests/docs_drift.py --self-test`: pass.
- POST `tests/auth.py` and `tests/slowlog.py`: pass in both modes. The latter's
  successful replay uses its required `--enable-debug-command yes` boot option.
- Differential split: **40/40 pass**, five requested suites, four requested
  seeds, atomics 0/1, 6:2 and 16 shards. Armed-fused: **40/40 pass**, plus
  both read-local execution witnesses. Combined: **80/80 differential legs**,
  zero differences, and **2/2 armed witnesses**. Both servers stopped after
  each geometry; all assigned ports are closed. [Matrix receipt](docs/authfix/differ.json).
- `tests/gates_test.py`: **not passing**. The first all-16-CPU run finished
  66 tests with nine scheduler deadline failures. A repeat limited to one
  four-CPU fixture group finished with 14 failures. Both use unchanged
  assertions and the 45-second fixture deadline; neither is promoted to a pass.
  [Initial log](docs/authfix/gates-initial.log.gz),
  [repeat log](docs/authfix/gates-serial-fixtures.log).

The initial harness setup attempts under `oracle-initial/` and `pre/`, and the
DEBUG-disabled slowlog attempts under `standard/`, are retained as setup failures.
They are not the negative controls or passing slowlog proof. The authoritative
paths are `pre-verified/`, `post/`, `acl-preview/`, and `slowlog-debug/`.

The original handoff required applying the ACL change after approval, rebuilding
the default POST and required unit/live-arm targets, and repeating the proof.
The review arm covered only the five new rows; the matrix above covered the
original default POST. Authfix2 below supplies the approved integration and final
reruns. Mainline still owns the quiet-box gate, scheduler rerun, count update,
and ordinary PRE/POST performance null using the existing cells and verdict
rules. The helper/text changes above are the reason a performance null remains
needed. No PAD arm or performance result is supplied by this correctness lane.

Reproduce any new row (substitute `config-nul`, `arity`, `rewrite`, `slowlog-1s`,
or `slowlog-2s`, and use a fresh output directory):

```sh
taskset -c 112-127 python3 tests/authfix.py \
  --binary "$PWD/build/tomokv" --port 25028 --cores 112-119 --ratio 6:2 \
  --case config-nul --output "$PWD/build/authfix/recheck-config" \
  --oracle /tmp/claude-1000/redis74/src/redis-server
```

Identity commands and binary/source identities are retained in
[proof.json](docs/authfix/proof.json). The full byte comparison uses
`tools/lbstall_artifacts.py compare`, `tools/ccfix_audit.py` and
`docs/deadswitch/linked_bytes.py`, as requested.

Final upstream check: `git fetch origin cpp` still resolves to
`5146b78ee89b64748dd46db970efa8086f653fa0`; no merge was needed.
Default `make -q all`, patch applicability, and `git diff --check` pass.

## authfix2

Continuation of `cx-authfix` at `711cc96dc`, using the owner-approved shared-file
exception. Commit `488bcdaa9` applies exactly the prepared two-line ACL bootstrap
change; nothing else in `src/cmd/acl.inc` changed. `cfg_requirepass(config)` now
supplies both the nonempty check and the digest input, retaining leading and
embedded NUL bytes. Commit `6976bcc53` extends the existing arity row to both
thread modes, preserving its assertions and adding no gate row.

All builds and correctness processes use CPUs **112–127**. Live authfix rows use
ports **25028–25032**, 16 shards, cores **112–119**, and split ratio **6:2**.
The final executable is the ordinary **`build/tomokv`**, with the applied ACL
change; the old preview executable is not used in this rerun.

| Final authfix row | Mode coverage | PRE negative control | Final default POST |
|---|---|---|---|
| `config-nul` | 1s and 2s | FAIL, 18 failed checks | PASS, 38/38 checks |
| `arity` | 1s and 2s | FAIL, 96 failed checks | PASS, 114/114 checks |
| `rewrite` | 1s and 2s | FAIL, 18 failed checks | PASS, 68/68 checks |
| `slowlog-1s` | 1s | FAIL, 8 failed checks | PASS, 28/28 checks |
| `slowlog-2s` | 2s | FAIL, 8 failed checks | PASS, 28/28 checks |

All **five POST rows / 276 checks pass**. Every row's Redis 7.4.10 oracle checks
also pass. All five rerun PRE controls exit 1 with assertion failures recorded
in `results.json`; none is credited for a traceback or setup failure. The PRE
binary still matches the original digest. Each row completes within 16 seconds.
Receipts: [POST rows](docs/authfix/authfix2/post/rows.json),
[PRE rows](docs/authfix/authfix2/pre/rows.json), and the per-case results, logs,
configuration files, and process lifecycles beneath those directories.

| Build or freshness check | Result |
|---|---|
| Default `taskset -c 112-127 make -j16 all` | PASS |
| All 28 targets named by `job_production_units` | PASS |
| `make -j16 mdbqsbr-live-arms`, both binaries | PASS |
| `make -q all`, 28 individual targets, and live arms | 30/30 PASS |

The target list was extracted from the current gate function, not copied from an
older receipt. [Build commands, exits and freshness](docs/authfix/authfix2/builds.json)
link to the compressed compiler logs. No compiler budgets or build flags changed.

| Default PRE versus final default POST identity | Result |
|---|---|
| Production object inventory | 100 PRE / 100 POST |
| Selected hot bodies, `tomo` | 601/601 identical |
| Selected hot bodies, `tomo_db0` | 603/603 identical |
| Full inventory hot selection, including executor run bodies | 1,208/1,208 identical |
| Changed hot bodies | **None (`[]`)** in both checkers |
| Command-handler entries | 1,206/1,210 identical |
| Full function inventory | 16,234/16,304 identical; 70 changed entries |
| Linked `.text` | 7,582,188 → 7,590,380 bytes (**+8,192**) |

Body identity uses the unchanged checkers' relocation normalization, retaining
instructions and target identities; it does not require equal load addresses.
All 1,208 selected hot bodies also have identical raw object-body bytes.
The 70-entry list includes the original 52 differences plus 18 ACL-object entries
in the two namespaces. These include `acl_initialize`, `acl_command_entry`, and
emitted ACL/pubsub/reply helpers outside the selected hot set. This does not claim
complete request-path or linked-image identity. The hot and full inventory
checkers exit 0; the linked-image checker exits 1 because runtime sections differ.
[Identity summary](docs/authfix/authfix2/identity-summary.json),
[changed function list](docs/authfix/authfix2/full/changed-bodies.json),
[hot inventory](docs/authfix/authfix2/hot.json),
[linked sections](docs/authfix/authfix2/linked.json). Exact commands and exits are
retained alongside each artifact; the checkers are unchanged.

| Binary | SHA-256 |
|---|---|
| PRE `build/authfix/pre/tomokv` | `4661985986b2f31f08bd62f146ba21d5133e0a3288b042920ae7fba5684414d4` |
| Final default POST `build/tomokv` | `2b57bd798786221bdb06ae3f061c7777bd6ef7cd719c05cc48d3f55f524ac6f2` |

Final differential rerun on the same default POST:

| Geometry | Comparison legs | Read-local witnesses | Differences | Runtime |
|---|---:|---:|---:|---|
| Split, 6:2, 16 shards | 40/40 PASS | N/A | 0 | 11m49s |
| Armed-fused, read-local 1, 16 shards | 40/40 PASS | 2/2 PASS | 0 | 10m49s |

Combined: **80/80 comparison legs, zero differences, 2/2 read-local witnesses**.
The unchanged matrix uses `servertail`, `compatintro`, `ccfix`, `aclsel`, and
`climon`; seeds **7, 19, 20, 23**; atomics **0/1**. Target cores are **112–119**,
oracle core **120**, driver cores **121–127**, and ports **25038/25039**. Both
armed witnesses observed **736 hits at peak** and **734 final hits**; counter
resets are handled by the existing sampler, with no added synthetic reads.
This repeats the original focused 80-leg matrix, not every differential suite.
[Commands, environment, binary hashes, and outcomes](docs/authfix/authfix2/differ.json),
[split log](docs/authfix/authfix2/differ-split.log),
[armed-fused log](docs/authfix/authfix2/differ-armed-fused.log).

All matrix listeners stopped cleanly. Every assigned port **25028–25041** is
closed after the final run. All 141 authfix PRE/POST/oracle lifecycle records
also show closed ports and no forced kills.
[Final port check](docs/authfix/authfix2/closed-ports.json),
[row lifecycle summary](docs/authfix/authfix2/row-summary.json). The final default
binary still matches the SHA-256 above, and final `make -q all` passes.

`tests/gates_test.py` was run **once** as `taskset -c 112-127 python3
tests/gates_test.py -v`: **FAIL**, 66 tests in 232.525 seconds, **13 failure entries
across 12 test methods**. Every failure is rooted in the unchanged 45-second
fixture deadline (timeout exit **124**). Twelve entries directly assert on 124;
`test_missing_helper_witness_stays_red_and_keeps_its_explanation` instead reports
that the expected helper name is absent from that timeout diagnostic. No other
failure cause was observed. Assertions, deadlines, and the entire scheduler test
source remain unchanged; its SHA-256 is recorded in
[the outcome receipt](docs/authfix/authfix2/gates-test.json).
[Full single-run log](docs/authfix/authfix2/gates-test.log.gz).

The failing `SchedulerWiring` methods are:

- `test_atomic_boot_waits_for_all_other_families_and_their_cleanup`
- `test_completion_is_not_visible_before_its_record_is_written`
- `test_empty_fragment_and_explicit_failure_cannot_turn_green` (both `empty` and `red` subtests)
- `test_failed_prerequisite_cannot_leave_the_queue_waiting_forever`
- `test_limited_workers_reuse_slots_without_losing_or_repeating_jobs`
- `test_missing_helper_witness_stays_red_and_keeps_its_explanation`
- `test_nonzero_worker_return_cannot_be_hidden_by_a_pass_fragment`
- `test_one_slot_uses_the_same_queue_without_losing_coverage`
- `test_opposite_completion_orders_have_byte_identical_canonical_ledgers`
- `test_release_boots_do_not_wait_for_independent_asan_build`
- `test_removing_atomic_exclusivity_fails_before_its_boot`
- `test_worker_exit_before_done_is_a_failure`

This is a failed scheduler receipt, not a passing gate. Per the owner's ruling,
mainline reruns it on the quiet box in the landing gate.

**Gate accounting remains DQ +5 / DF +5.** `collect_job authfix` is at line 3378,
before the quick-tier exit at line 3445. `tests/gate.sh`, its EXPECT constants,
and the row inventory are unchanged by authfix2. [Line accounting](docs/authfix/authfix2/ledger.json).
The landing computes EXPECT
from `origin/cpp`; the earlier section's absolute counts belong to its old base.

The maintainer runs the landing gate and ordinary PRE/POST performance null on
the quiet box. This lane supplies correctness and byte inventories, with no
performance claim or PAD arm. No push or full gate was run.

Items 1–2 are complete, so the WIP banner is removed. The failed scheduler
receipt above remains explicit. [Final proof summary](docs/authfix/authfix2/proof.json).
