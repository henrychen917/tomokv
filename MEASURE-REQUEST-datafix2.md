# Redis 7.4 data-type compatibility, part 2

## datafix2

Base: `ef5204b2e9650693228cc105b34625516898b82d`; worktree and branch `cx-datafix2`. No push. Correctness execution is restricted to CPUs 96–111 and listener ports 33800–33899. Builds use `-j16`. Performance measurements are reserved to the maintainer.

### Changes and oracle reproduction

The [commit map](docs/datafix2/commit-map.json) records one implementation commit per item; evidence is collected in a separate commit.

All five register items reproduced. The [oracle identity](docs/datafix2/oracle-identity.json) is pinned by SHA-256. The reference is the local Redis source at `/home/user/Projects/redis/src` and the Redis **7.4.10** oracle `/home/user/Projects/redis74/src/redis-server` requested by the owner. [Initial exact replies and boot arguments](docs/datafix2/reproductions.jsonl) cover CD4.9, CD4.14, CD4.15 and SO4.2; the CD4.7 PRE battery archive contains its oracle-first LFU witness. Reproductions used eight threads, sixteen shards, epoll, atomic 0, read-local 0, both 1s and split 6:2. The final batteries expand that geometry below.

| Item | Observed PRE mismatch | Implemented behavior |
| --- | --- | --- |
| CD4.7 | Inspection commands increased LFU frequency | Per-lookup no-touch scope for EXISTS, TTL/PTTL/EXPIRETIME/PEXPIRETIME, TYPE and all OBJECT forms; SCAN TYPE was already no-touch. Local, scatter, and EXEC paths are covered. TOUCH and GET retain their ordinary touch behavior. |
| CD4.9 | Missing DEL, failed SET NX and absent-member SREM aborted a watched transaction | Dirty WATCH from actual command effects at the key owner. Retain txnorder2 claims and decision lifetimes; publish dirtiness at the associated successful decision. Physical key expiry and eviction remain independent effects. |
| CD4.14 | INFO omitted expired_subkeys; immediate field expiry was uncounted | Add Redis expired_subkeys, including immediate, lazy and active removals, rebased by RESETSTAT. Retain and document expired_hash_fields as lifetime count and hash_field_expires as the expiry-attention gauge. |
| CD4.15 | APPEND, SETRANGE, SETBIT and writing BITFIELD retained embstr | Immutable raw-string replacement, including unchanged bit writes and overflow FAIL materialization. GET-only BITFIELD and empty SETRANGE keep their original representation. Preserve raw through TTL reheadering. |
| SO4.2 | Non-LRU/LFU policies reported a clock-derived 768 seconds for a one-second-old key | Separate 24-bit, one-second idle timestamps from eviction scores for every enabled policy. LFU returns Redis's exact error for a present key; all policies return nil for a missing key before policy errors. |

The no-touch list comes from every LOOKUP_NOTOUCH use in Redis db.c, expire.c and object.c. Module and cluster interfaces are outside this server's surface. [GET/SET/MGET/MSET source-body hashes](docs/datafix2/source-hot-bodies.json) are unchanged.

The existing 192-byte embedded-string threshold for ordinary SET is unchanged; CD4.15 changes the four mutators and preserves raw encoding through TTL reheadering. Missing-key APPEND retains Redis's new-string behavior.

[INFO field documentation](docs/INFO.md) explains both retained TomoKV fields. The existing CD4.13 difference in which hash commands physically reap expired fields is outside this item: expired_subkeys counts actual deadline removals, and does not claim those pre-existing reap triggers now match Redis.

The idle clock occupies reserved FlatStore padding without changing any locked layout. Published radix links are immutable; readers perform fixed traversal and at most one timestamp CAS, without retries or locks. The clock follows its store across owner migration and uses the existing QSBR retirement sink when disabled. Maxmemory 0 allocates no clock and retains the previous zero-idle behavior. Arming maxmemory initializes existing objects at that time, so idle history from the disabled interval is unavailable. Sidecar nodes retain their allocation high-water mark until disabled/destruction; their memory and enabled-policy cost have not been measured. This is an enabled-maxmemory policy fix, not a claim of full idle-history parity across policy/configuration changes.

### Verification status

The final directed matrix is complete: **POST 120/120 passed; PRE 0/120 passed**, with every oracle leg completed. [Per-leg inventory and hashes](docs/datafix2/directed-summary.json) link the gate archives. The final WATCH table covers 106 command names in database-1 and 108 in database-16, recording 786 ordinary/writer-EXEC outcomes per database-1 leg and 794 per database-16 leg, plus three physical expiry/eviction checks; PRE disagrees with 296–297 table outcomes per leg. One PRE eviction arm exhausted its three fresh cohorts without opening a window and failed explicitly; its complete command table still contains 296 mismatches. The other 23 PRE eviction arms observed eviction and failed the required invalidation.

All **73 selected POST jobs pass**, with 532 passing row verdicts in their latest complete runs. Every selected PRE job was also executed: 523 rows pass and nine fail as expected (the five new rows and the four existing edgeenc rows corrected to Redis). The [complete job and leg inventory](docs/datafix2/proof-summary.json) records the bindings, verdicts and archives; the [campaign history](docs/datafix2/campaign-summary.json) retains earlier failures.

| Check | POST | PRE |
| --- | --- | --- |
| New directed legs | 120/120 pass | 120/120 fail; details above |
| Differential, epoll | 938 suite/seed legs + 16 equivalence cells pass | Same, all pass |
| Differential, io_uring | 938 suite/seed legs + 16 equivalence cells pass | Same, all pass |
| Eviction jobs | 8/8 pass | 8/8 pass |
| Additional WATCH-related queue | 57/57 rows pass | 57/57 rows pass |

All four differential invocations exit 0. Their permanent seeds are 7, 19, 20 and 23; the gate allocated rotating seeds 21/22 for POST and 24/25 for PRE. The four seed-19 MULTI repeats, every declared mode/atomic part, lane-engagement checks, and mode-equivalence cells are present. These are partial gate diagnostics; aggregate full-gate folds and the full iteration were not run.

The corrected transaction/unit jobs passed **96/96 rows** on complete reruns, and storage passed **13/13**. Their first broad POST invocation had 14 fixture failures: 13 storage rows could not link the isolated command-boundary fixture, and one script unit expected the old internal access byte. The storage fixture aborts if either new WATCH callback is accidentally reached. The script assertion retains RESP `:2` and requires the exact mutation bit (POST 11, PRE 3). [Redis confirms the unchanged reply and value](docs/datafix2/script-apply-oracle.json).

One initial PRE snapshot row returned `Background save already in progress` for a SAVE, armed 2/3 required barriers, and observed zero torn snapshot groups or live reads. Repeating the complete, unchanged PRE snapshot job passed **16/16 rows**. [Both observations are retained](docs/datafix2/baseline-observations.json); this lane makes no snapshot fix claim.

The gate-harness self-test passes all 70 tests. The differential helper's 24 tests, eviction helper self-test and three EXEC-abort/WATCH wrapper tests also pass. Builds cover `make all`, all 42 targets in `job_production_units`, and both live control arms: 45/45 freshness checks pass on each arm. Final cleanup removes unit-binary debug data while checking every allocated section and protecting the merit binaries; [handoff build evidence](docs/datafix2/handoff-build-proof.json) records the final hashes and freshness results.

Each new row declares 24 legs: database image 1/16 × atomic 0/1 × epoll/uring × (1s read-local 1, 1s read-local 0, 2s read-local 0), with eight server threads, sixteen shards, split 6:2. Every leg runs an independent oracle probe before its target probe. A failed leg does not suppress subsequent legs.

The WATCH table requires coverage of every registered Redis write command, plus PFCOUNT/PFDEBUG, and compares watched source/destination keys against Redis. It additionally runs writer-inside-EXEC cases where supported. Existing unsupported FLUSHDB/FLUSHALL-in-EXEC and cross-key-script-in-writer-EXEC cases are excluded only from these extra writer-EXEC variants; the requested ordinary writer followed by the watching client's EXEC still runs for them. Expiry and eviction arms require an observed window, with bounded fresh-state rearming.

The existing edgeenc assertions were corrected only for raw mutation encodings. [Nine exact Redis oracle assertions](docs/datafix2/edgeenc-oracle.jsonl) support those changes. The test grep and [data-type job mapping](docs/datafix2/grep-job-map.json), plus the [WATCH grep mapping](docs/datafix2/watch-grep-job-map.json), record related existing assertions. The [standalone inventory](docs/datafix2/standalone-inventory.json) explicitly marks tests with no declared gate job as NOT RUN and records the separate harness self-test results. The atomic_batteries job is NOT RUN because it includes an explicit RYOW performance assertion; its correctness dependencies are exercised by the selected transaction and atomic-unit jobs. Full iteration, ABBA, efficiency and NIC measurements are NOT RUN because they remain with the maintainer.

The lane driver only invokes `tests/gate.sh iteration` with `GATE_ONLY_JOBS`; it does not reimplement job verdicts or run the full iteration. Each invocation is a partial diagnostic receipt. Gate ports are reserved with non-listening SO_REUSEADDR sockets to keep them out of the machine's overlapping ephemeral port range. Python bind-zero fixtures use [the lane port guard](docs/datafix2/port_guard/sitecustomize.py); assertions, deadlines and protocol comparisons are unchanged.

**Rows:** DQ=+5, DF=+5. All five collect_job lines precede the quick-tier exit. EXPECT_QUICK/EXPECT_FULL remain 739/756; the maintainer should set **744/761** and add the five exact labels. [The source/fixture check](docs/datafix2/label-fixture.log) reports exactly five missing labels and no extras. No constants or fixture labels were edited.

### Binaries, identity and merit

Binary hashes and PAD construction are recorded in [pad-a.json](docs/datafix2/pad-a.json). PRE is `build/tomokv-pre`, POST is `build/tomokv`, PAD-A is `build/tomokv-pad-a`.


| Arm | SHA-256 |
| --- | --- |
| PRE | `bd013c79ef74882664dc79f49c292c2930d42d2f2631dc18b1673675d8e8489f` |
| POST | `e04e787a192cd2ab0b3f9f0ef22df0e9ba3651843aeaa2802c697ef24ed37909` |
| PAD_A | `88221d10464fd62014ffba52e2b6e15c23d61ece794ba4ec95d5803046c5eb5c` |

PAD kind **A: behavior twin**: PRE behavior with unchanged locked layouts and 31,552 unreachable trailing NOP bytes, matching POST's total .text size of 8,156,535 bytes (PRE 8,124,983). This controls total text size, not individual POST symbol addresses or cache-line placement. No PAD-B is supplied.

The three requested identity tools ran against PRE. Strict audits return differences, not passes: 17,072/18,301 emitted bodies and 1,014/1,221 handler bodies match under ccfix normalization; 1,157/1,312 selected existing hot bodies match under lbstall's checker. Ordinary GET/SET bodies match in both database images. Notification variants and surrounding store/dispatch code have disclosed changes. [Full compressed inventory](docs/datafix2/identity/bodies.json.gz), [audit overview](docs/datafix2/identity/overview.json), [hot audit](docs/datafix2/identity-headline.json), and [linked-section comparison](docs/datafix2/linked-bytes.json) retain the evidence. Identity is a proxy; no rate conclusion is inferred from it.

Run the exact [generic 14 cells](docs/datafix2/merit-cells.txt): h05, h06, p8g, p8s, d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1, x9_32_l1, x9_32_l0. Use the gate's own ABBA instrument on the quiet box for PRE/POST and PRE/PAD-A comparisons at matched offered load and geometry. Record rate, cycles/op, instructions/op, IPC and depth-1 latency scores. Rate/latency under the instrument's null-control rules decides merit; instructions and IPC explain it. PRE/PAD-A movement limits behavioral attribution. All performance cells are **NOT RUN in this lane**; no throughput claims.

| Comparison | PRE | POST/PAD-A | Decision |
| --- | --- | --- | --- |
| Generic 14 cells, PRE vs POST | NOT RUN | NOT RUN | Maintainer merit pending |
| Generic 14 cells, PRE vs PAD-A | NOT RUN | NOT RUN | Text-size control pending |
