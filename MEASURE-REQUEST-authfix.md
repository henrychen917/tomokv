## authfix

**WIP; not ready to merge.** Branch `cx-authfix`, based on
`5146b78ee89b64748dd46db970efa8086f653fa0`. No push, benchmark, performance
measurement, or full gate. All work and correctness processes use CPUs 112–127;
database listeners use ports 25028–25041.

The committed source fixes config-line arity, carries decoded requirepass lengths
through startup CONFIG metadata/publication, and redacts SLOWLOG at capture time.
One additional bootstrap read in **acl.inc still truncates the password** after
that publication. The task reserves that file for aclfix, so it is untouched.
The exact [two-line integration patch](docs/authfix/acl-integration.patch) is
prepared and checked with `git apply --check`; the shared-file exception was
requested and remains unanswered. Its temporary build copy passes **all five
new rows**. It is a review arm, not the default POST executable.

| Finding / new gate row | PRE 5146b78ee | Committed-source POST | ACL patch review arm |
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

Proof completed so far:

- PRE and POST `make -j16 all`: pass. All 28 `job_production_units` targets:
  build pass and **28/28 make -q freshness checks pass**, including netcmd-unit.
  The two `mdbqsbr-live-arms` binaries are still building.
- Config parser unit and `tests/docs_drift.py --self-test`: pass.
- POST `tests/auth.py` and `tests/slowlog.py`: pass in both modes. The latter's
  successful replay uses its required `--enable-debug-command yes` boot option.
- Differential split: **40/40 pass**, five requested suites, four requested
  seeds, atomics 0/1, 6:2 and 16 shards. Armed-fused is still running.
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

After the ACL ownership decision and count update, mainline must run the gate
and its ordinary performance null on the quiet box, comparing the fixed default
POST to PRE using the existing cells and verdict rules. The helper/text changes
above are the reason a performance null is still needed. No PAD arm or performance
result is supplied by this correctness lane.

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
