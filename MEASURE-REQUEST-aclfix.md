## aclfix

Round-4 ACL fixes CC4.8, CC4.9, CC4.10, CC4.24, AT4.4 and AT4.6. Worktree
`/home/user/Projects/cx-aclfix`, branch `cx-aclfix`, based on origin/cpp
`5146b78ee` (unchanged at the final proof). No push. PRE is `5146b78ee` built
into `build/aclfix/pre/` (sources verified identical to `5146b78ee` in
`build/aclfix/pre-source`); POST is `build/tomokv`.

Every row expectation is a Redis 7.4.10 reply, run against
`/tmp/claude-1000/redis74/src/redis-server`: all six rows pass on the oracle
([docs/aclfix/oracle](docs/aclfix/oracle)). Rows boot their own listener with
16 shards, 2s at 6:2 and 1s with read-local 1, on CPUs 112-119; clients on
121-127; ports 25042-25048 only.

### Findings

| Finding | PRE `5146b78ee` (both modes) | POST (both modes) | Files | Row |
|---|---|---|---|---|
| **CC4.8** SORT_RO skips the BY/GET check | `SORT_RO allowed:list BY nosort GET other:*` returns `secret`; `BY other:*` dereferences `other:a`. SORT answers the BY text for `BY nosort` (Redis allows it), the GET text before a denied source/STORE key (Redis: NOPERM), and logs every option error in ACL LOG (13 entries, `acl_access_denied_key` +13) | All 29 SORT/SORT_RO replies the row checks equal Redis. Option errors: ACL LOG 0, denial counter 0, counted as calls (6 SORT, 5 SORT_RO), as Redis. Key denials: NOPERM first, one ACL LOG record each, rejected 3/1 | `src/cmd/acl.inc` | `aclfix sort (1s/2s)` |
| **CC4.9** XREADGROUP group named STREAMS | **Already fixed**: NOPERM, no PEL entry (fixed by `6da4d7475`, generated key specs, aclkeys lane). Failing control: audited `6b50f447f` returns the secret entry and adds a PEL entry in both modes | NOPERM, PEL 0 | none | `aclfix streams-name (1s/2s)` |
| **CC4.10** whitespace patterns break SAVE/LOAD | All 14 `~`/`&` patterns with space, `\t`, `\n`, `\r`, `\v`, `\f` or NUL accepted; legal patterns `~a"b ~a'b ~a\b` (and `&`) save raw and ACL LOAD refuses the file (`unbalanced quotes in acl line`) | All 14 refused with Redis's exact `ERR Error in ACL SETUSER modifier '…': Syntax error` (NUL ends the modifier, CR/LF shown as spaces); selectors still refused atomically; quote/backslash patterns round-trip SAVE→LOAD; a broken file keeps the live image | `src/cmd/acl.inc` | `aclfix save-load (1s/2s)` |
| **CC4.24** user slots never reused; shutdown overrun | After 65535 create/delete pairs both creations answer `ERR out of memory`; SIGTERM exits **-11 (SIGSEGV)**; ASAN: `global-buffer-overflow`, 8-byte WRITE in `acl_shutdown` (acl.inc:1043) | Both creations OK; at the true live ceiling (65535 live non-default users) two creations answer `ERR out of memory` without consuming a slot; a deleted user's authenticated client is disconnected and its handle never names the replacement; SIGTERM exit 0; ASAN and LSan clean | `src/cmd/acl.inc` | `aclfix capacity (1s/2s)` |
| **AT4.4** woken pop denied after popping | 12/12 woken BLPOP/BRPOP/BZPOPMIN/BZPOPMAX/BLMPOP/BZMPOP denials (key and command revocation) answer NOPERM with the list/zset **empty** | NOPERM, element still there, exactly one ACL LOG record per denial | `src/cmd/blocking.inc`, `src/cmd/acl.inc`, `src/cmd/acl.h` | `aclfix wake-pop (1s/2s)` |
| **AT4.6** woken move/stream read denied after running | BLMOVE/BRPOPLPUSH: NOPERM with the element **moved** to the destination; XREADGROUP: NOPERM with a **PEL entry**. Audited `6b50f447f`: the move runs and replies `v` | NOPERM; source keeps the element, destination empty, PEL 0; XREAD NOPERM | `src/cmd/blocking.inc`, `tests/aclkeys_wake_unit.cc` | `aclfix wake-scatter (1s/2s)` |

Fixes, at the cause:

- **CC4.8** `acl_check_keys` checks the declared keys first (source and the
  final STORE target, sortGetKeys semantics, through the aclkeys metadata
  path), then walks SORT/SORT_RO options exactly as `sort.c` does (ASC/DESC/
  ALPHA, LIMIT with string2ll operands, STORE only for SORT, BY, GET, first
  syntax/integer error ends the walk). Without unrestricted key access, GET or a
  BY pattern containing `*` is denied. The option denial is carried as a key
  denial with a marker bit and answered with sort.c's own text, without an ACL
  LOG entry or denial counter, and counted as a call. The old SORT-only
  branches (admission and reply text) are deleted.
- **CC4.10** `~` and `&` patterns containing isspace() or NUL bytes are refused
  (`ACLStringHasSpaces`). The ACL file loader splits lines as Redis does:
  trim ` \t\r\n`, split on single spaces with no quoting, trim `\t\r\n` per
  rule; TomoKV's `#` comment lines stay accepted. SETUSER formats the failing
  modifier as `%s` does.
- **CC4.24** (preferred fix, closes CC25): a refused creation consumes no slot;
  a deleted user's slot is reused, oldest deletion first, once no never-used
  slot remains, under a new handle (slot + 65536 per reuse), so a stale handle
  held by a closing client resolves to no user and is denied; a slot whose next
  handle would wrap is never reused. Shutdown walks only the slot array and
  frees replaced tombstones. The default user keeps handle 0.
- **AT4.4/AT4.6** the live ACL check runs immediately before a woken command
  executes: on the owner in `blocking_run_direct` (pops, XREADGROUP) and on the
  owning IO in `blocking_resume_move_impl` before a resumed BLMOVE/BRPOPLPUSH/
  XREAD is prepared. A denial completes with NOPERM and touches nothing. Retire
  keeps an executed reply (`BlockingState::acl_checked`); the retire-time check
  remains only for completions that ran nothing (timeout, CLIENT UNBLOCK, probe
  errors), and `blocking_scatter_retire` no longer re-checks. No IO-side hook
  was needed outside blocking.inc/acl.inc; `io_loop.h` is untouched.

### Gate rows

New rows (all in `job_aclfix`, collected after `acl_recheck`, above the
quick-tier exit): `aclfix {sort,streams-name,save-load,capacity,wake-pop,wake-scatter} ({1s,2s})`.
Labels are in `tests/fixtures/nullrefresh-ledger-labels.json`;
`python3 tests/gate_ledger_fixture.py` passes (540 rows agree) and its
self-test passes 10/10.

**DQ = +12, DF = +12. EXPECT_QUICK 511 + 12 = 523; EXPECT_FULL 528 + 12 = 540**
(set in `tests/gate.sh` with that arithmetic comment).

Negative controls, kept under `docs/aclfix/`: PRE fails every row in both
modes except `streams-name` (`pre-2s/`, `pre-1s/`); the audited binary fails
`streams-name` and `wake-scatter` in both modes (`audited-2s/`,
`audited-1s/`). POST passes 12/12 (`post-2s/`, `post-1s/`); the slowest row is
`capacity` at 3.0-3.2 s (8.6 s at load 90).

### Proofs (CPUs 112-127 only, every command under `taskset -c 112-127`)

| Proof | Result |
|---|---|
| `make -j16 all` (POST) | exit 0, no warnings; also PRE `BUILD_ROOT=build/aclfix/pre` |
| `job_production_units`: 28 targets, `make -q` each, then `mdbqsbr-live-arms` | **28/28** targets built (exit 0) and fresh under the job's own `make -q`; `mdbqsbr-live-arms` exit 0 ([production-units.txt](docs/aclfix/production-units.txt), compressed logs beside it) |
| aclkeys units (`aclkeys-unit`, `aclkeys-wake-unit`, `aclkeys-wake-db0-unit`) | built and `make -q` fresh; `aclkeys-unit permissions` 142 + 18 assertions pass; its registry audit reports the same 27 mismatches (exit 1) as PRE, line for line; `tools/aclkeys3_verify.py --rounds 2` **176/176**, including the `-denied` schedules updated for the pre-execution check ([aclkeys-units.txt](docs/aclfix/aclkeys-units.txt)) |
| `python3 tests/gates_test.py` | 59/66 (60/66 on an earlier run); nested persistfix self-test 14/14. Every failure is a SchedulerWiring fixture exceeding its hard 45 s `timeout` (exit 124) at load 35-43, with no other assertion; PRE's own gate.sh fails the same fixtures under the same conditions (alternated runs: PRE 7 and 7, POST 6 and 3 - [gates-test-schedulerwiring.txt](docs/aclfix/gates-test-schedulerwiring.txt)). Needs a quieter box for a 66/66 receipt |
| `tests/gate_ledger_fixture.py` | 540 source-declared rows agree; `--self-test` 10/10 |
| Differential vs Redis 7.4.10 (`aclsel aclkeys ccfix sort stream streamgrp blocking`, seeds 7 19 20 23, atomic 0/1) | split 6:2/16 shards: **56/56**; armed-fused: **48 legs + 2 read-local witnesses**, 0 fail (SORT legs skip by design) ([differ.json](docs/aclfix/differ.json)) |
| POST `tests/acl.py` (nofile, atomic 0, atomic 1), `acl_categories.py`, `aclreply.py` (2s, 1s), `aclkeys_test.py`, `aclkeys_wake_state.py` (2s/1s x read-local 0/1 x atomic 0/1), `aclkeys_wake.py` (2s, 1s; 1000 wakes, 0 missed) | all pass ([posttests.txt](docs/aclfix/posttests.txt)) |
| New rows | 12/12 POST; PRE/audited controls fail as listed above |
| ASAN (`make asan`) | PRE: `capacity` reports `global-buffer-overflow` (8-byte WRITE in `acl_shutdown`) in 2s and 1s. POST (final, budget-tuned): all 12 rows pass with no AddressSanitizer or UBSan report; two 1s rows first hit the intermittent LeakSanitizer teardown report that PRE shows too (item 7 below) and passed on re-run |

### Hot-body identity, default build PRE vs POST

Method of `docs/ttlclean/` (GCC 13.3.0, normal Makefile flags/jemalloc):
`tools/lbstall_artifacts.py compare`, `tools/ccfix_audit.py`,
`docs/deadswitch/linked_bytes.py`, both namespaces.

| Check | PRE | POST | Result |
|---|---:|---:|---|
| Hot bodies (lbstall selection), `tomo` + `tomo_db0` | 1,204 | 1,204 | **1,204 raw-byte identical** |
| Full inventory's hot selection, incl. executor run bodies | 1,208 | 1,208 | 1,208 identical |
| Command handlers | 1,210 | 1,210 | 1,210 identical |
| All emitted bodies | 16,293 | 16,301 | 16,189 identical; 114 differ (102 changed, 10 added, 2 removed) |
| Linked `.text`, bytes | 7,582,188 | 7,596,108 | +13,920; hot bodies identical but placed differently |

| SHA-256 | |
|---|---|
| PRE `build/aclfix/pre/tomokv` | `da10047cfb69f3f6f0103ac43a25ecfd963d42ef4ef0b2c39ae73708494107bc` |
| POST `build/tomokv` | `19e49a0aae78c9037e02ad1dd70a7a4d71911d9c6c3feed15e17392c318c40cd` |

**No hot body changed.** All 114 changed bodies are cold and listed with
their reason in [changed-bodies.tsv](docs/aclfix/identity/changed-bodies.tsv):

| Object (both namespaces unless noted) | Bodies | Reason |
|---|---:|---|
| `acl.o` | 26 + 26 | Edited by this lane, or its new/removed helper (`acl_slot`, `acl_has_spaces`, SORT walk inside `acl_check_keys`, the three `acl_check_permission` instances, `acl_create_locked`, `acl_tombstone_user_locked`, `acl_shutdown`, `acl_parse_file`, `acl_reply_denied`, `acl_finish_dispatch_denial`, `acl_recheck_blocking`, `acl_command_entry`, static initializers, the new free-handle deque, `cfg_split_args`' local copy removed) |
| `acl.o` | 13 + 13 | Inline the new `acl_slot` handle check (CC4.24): `acl_username`, `acl_find_user`, `acl_authenticate`, `acl_default_nopass`, `acl_initialize`, `acl_sorted_users_locked`, `acl_commit_images_locked`, `acl_refresh_security_locked`, `acl_pubsub_channel_entry`, `acl_update_default_requirepass` |
| `acl.o` | 8 + 9 | Code-generation drift in acl.o-local cold ACL bodies: `acl_reply_log`, `acl_join_patterns`, `acl_describe_image`, (db0) `acl_describe_commands`, and the AclLogEntry/AclUser* sort/heap/swap helpers (ACL LOG, ACL LIST/GETUSER/SAVE) |
| `xshard.o` | 7 + 6 | Edited: `blocking_run_direct` (+ cold part), `blocking_retire`, `blocking_scatter_retire`, both `blocking_resume_move_impl` instances, `blocking_prepare` (BlockingState gained `acl_checked`) |
| `xshard.o` (`tomo` only) | 2 | Drift: `classify_keys` - one `add_write` to `append_key_span` site (the constant {first 1, count 1} STORE-family case; MGET's `add_read` and MSET/DEL sites are unchanged) is now a call instead of inlined; `normalize_multi_blocking_pop` (MULTI-only) |
| `acl.o`, `xshard.o` | 4 | Weak copies the linker discards: the linked bodies (from earlier objects) are unchanged |

Every changed weak body whose linked copy differs is this lane's own
(`blocking_resume_move_impl` instances, the new deque destructor). To get
here, the TUs' compile-time inlining budgets were re-tuned
(`large-unit-insns`: acl 34630 -> 35369, db0 acl 34550 -> 35300, xshard
127791 -> 127820, db0 xshard 126391 -> 126421; the measured GCC starting-unit
growth is +749/+765 and +30/+30). Without that, acl.o's copy of the shared
`reply_map_header<Op::Sink&>` (the one linked for every RESP3 map reply)
and several unrelated xshard bodies drifted. A scan of 48 budgets (20 for
xshard.o, 127811-128241) found none that also restores `classify_keys`;
larger budgets spread drift into `xshard_execute`/`xshard_plain_prepare`.

`acl_check_permission` stays out of the default dispatch: its instances are
internal to acl.o and are called only from `acl_dispatch_entry`,
`acl_check_queued` and `acl_recheck_blocking`
([callers](docs/aclfix/identity/acl_check_permission-callers.txt));
`acl_dispatch_entry` is called from the `parse_and_dispatch` variants only
behind the predicted-false `security_check` branch (AUTH/ACL armed), and those
dispatch bodies are byte-identical. Placement: all 544 linked hot symbols keep
their bytes and 16-byte alignment but move (single-database set mostly
+7,984 bytes, multi-database set mostly +13,920 bytes; offsets within the
64-byte line change) - [hot-placement.txt](docs/aclfix/identity/hot-placement.txt).
The performance null should allow for placement (the project's PAD practice).

### Open for the mainline

1. **Timeout / CLIENT UNBLOCK after revocation.** TomoKV still answers
   NOPERM at retire for a parked command that timed out or was unblocked after
   its permission was revoked; Redis 7.4.10 answers the null reply / UNBLOCKED
   error with no ACL check ([oracle-aclreply.log](docs/aclfix/oracle-aclreply.log):
   the four timeout rows of `tests/aclreply.py` fail on the oracle). Kept
   unchanged because `aclreply.py` pins it and it is outside these findings.
   Aligning it means deleting the remaining retire-time check and changing
   `aclreply.py` section 1.
2. **SORT/SORT_RO option denial inside MULTI.** TomoKV refuses at queue time
   (the option error replaces QUEUED and the transaction aborts); Redis queues
   and returns the error inside EXEC's reply. If permissions change between
   queue and EXEC, TomoKV answers "NOPERM ACLs rules changed ..." where Redis
   returns the SORT error. Pre-existing for SORT, now shared by SORT_RO.
3. **WAIT** is not rechecked after revocation while waiting (unchanged, as
   instructed; see MEASURE-REQUEST-aclkeys.md).
4. **Live user ceiling.** Creation/deletion churn never runs out now, but at
   most 65,535 non-default users can exist at once (Redis: unlimited); the
   refusal is `ERR out of memory`. Replaced tombstones, like retired permission
   images, are freed only at shutdown.
5. **Adjacent, unchanged:** SETUSER accepts usernames containing `\v` or
   `\f` (Redis refuses them with "Usernames can't contain spaces or null
   characters"); TomoKV's own SAVE/LOAD still round-trips them. A BY pattern
   with a NUL before `*` is denied by TomoKV (whole pattern, matching the bytes
   TomoKV's SORT dereferences) where Redis's `strchr` would allow it. TomoKV
   still accepts `#` comment lines in ACL files (Redis does not). TomoKV does
   not count SORT calls that fail in its own option parser (commandstats),
   independent of ACL.
6. **Sequencing with authfix.** authfix's two-line change to
   `acl_initialize` (requirepass byte length) does not overlap this lane's
   hunks: its patch applies cleanly over aclfix's acl.inc (offset +92 lines);
   the nearest aclfix hunk is in `acl_shutdown`. Whichever lands second should
   re-run the acl.o body audit, because both change acl.o's inlining budget.
7. **LeakSanitizer at SIGTERM.** An intermittent LSan report of one `Client`
   allocated in `IoLoop::admit_fd` occurs on PRE and POST alike (2/12 runs
   each, [asan-lsan-teardown.txt](docs/aclfix/asan-lsan-teardown.txt)); it is
   IO teardown, outside this lane.
8. **gates_test.py on a shared box.** The SchedulerWiring fixtures' hard 45 s
   deadline expires under load for PRE's own gate.sh as well
   ([gates-test-schedulerwiring.txt](docs/aclfix/gates-test-schedulerwiring.txt)).

No benchmark or full gate was run; the mainline runs the performance null.
