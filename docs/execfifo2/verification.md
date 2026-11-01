# execfifo2 correctness record

All **42/42 selected-job groups passed** on the frozen POST image. The retained partial ledgers contain **1,375 passing public row executions and zero failures**. These include repeated release rows and repeated mode/engine executions; this is not a full-tier row count or an iteration receipt. There are 43 retained attempts: the 42 final groups and one earlier directed pass before the compiler-budget adjustment. No selected-job attempt failed.

Commands, environments, image digests, job plans, ledgers and raw leg results are retained in [runs.json](validation/runs.json), [evidence.json](validation/evidence.json) and the folders linked below. The [coverage check](validation/coverage.json) requires every selected group on the final POST SHA and exact inventories for the new FIFO/chaining/progress witnesses, AT4.12 and both differential matrices.

| Group | Passing public rows | Retained evidence |
| --- | ---: | --- |
| `aof-extra-epoll-0` | 60 | [ledger](validation/40-aof-extra-epoll-0/ledger.partial), [output](validation/40-aof-extra-epoll-0/output.log) |
| `aof-extra-epoll-1` | 60 | [ledger](validation/41-aof-extra-epoll-1/ledger.partial), [output](validation/41-aof-extra-epoll-1/output.log) |
| `aof-extra-uring-0` | 60 | [ledger](validation/34-aof-extra-uring-0/ledger.partial), [output](validation/34-aof-extra-uring-0/output.log) |
| `aof-extra-uring-1` | 60 | [ledger](validation/35-aof-extra-uring-1/ledger.partial), [output](validation/35-aof-extra-uring-1/output.log) |
| `asan-epoll-0` | 6 | [ledger](validation/25-asan-epoll-0/ledger.partial), [output](validation/25-asan-epoll-0/output.log) |
| `asan-epoll-1` | 6 | [ledger](validation/26-asan-epoll-1/ledger.partial), [output](validation/26-asan-epoll-1/output.log) |
| `asan-uring-0` | 6 | [ledger](validation/23-asan-uring-0/ledger.partial), [output](validation/23-asan-uring-0/output.log) |
| `asan-uring-1` | 6 | [ledger](validation/24-asan-uring-1/ledger.partial), [output](validation/24-asan-uring-1/output.log) |
| `at412` | 18 | [ledger](validation/03-at412/ledger.partial), [output](validation/03-at412/output.log) |
| `atomic-controls-epoll` | 3 | [ledger](validation/37-atomic-controls-epoll/ledger.partial), [output](validation/37-atomic-controls-epoll/output.log) |
| `atomic-controls-uring` | 3 | [ledger](validation/31-atomic-controls-uring/ledger.partial), [output](validation/31-atomic-controls-uring/output.log) |
| `batteries-epoll-0` | 47 | [ledger](validation/14-batteries-epoll-0/ledger.partial), [output](validation/14-batteries-epoll-0/output.log) |
| `batteries-epoll-1` | 47 | [ledger](validation/15-batteries-epoll-1/ledger.partial), [output](validation/15-batteries-epoll-1/output.log) |
| `batteries-uring-0` | 47 | [ledger](validation/12-batteries-uring-0/ledger.partial), [output](validation/12-batteries-uring-0/output.log) |
| `batteries-uring-1` | 47 | [ledger](validation/13-batteries-uring-1/ledger.partial), [output](validation/13-batteries-uring-1/output.log) |
| `boundary-extra` | 21 | [ledger](validation/29-boundary-extra/ledger.partial), [output](validation/29-boundary-extra/output.log) |
| `broad-epoll` | 209 | [ledger](validation/11-broad-epoll/ledger.partial), [output](validation/11-broad-epoll/output.log) |
| `broad-uring` | 209 | [ledger](validation/10-broad-uring/ledger.partial), [output](validation/10-broad-uring/output.log) |
| `core` | 45 | [ledger](validation/02-core/ledger.partial), [output](validation/02-core/output.log) |
| `differ-epoll` | 6 | [ledger](validation/21-differ-epoll/ledger.partial), [output](validation/21-differ-epoll/output.log) |
| `differ-uring` | 6 | [ledger](validation/20-differ-uring/ledger.partial), [output](validation/20-differ-uring/output.log) |
| `directed` | 43 | [ledger](validation/01-directed/ledger.partial), [output](validation/01-directed/output.log) |
| `fairness` | 3 | [ledger](validation/42-fairness/ledger.partial), [output](validation/42-fairness/output.log) |
| `features` | 36 | [ledger](validation/06-features/ledger.partial), [output](validation/06-features/output.log) |
| `fifo-contract` | 11 | [ledger](validation/27-fifo-contract/ledger.partial), [output](validation/27-fifo-contract/output.log) |
| `flip` | 16 | [ledger](validation/07-flip/ledger.partial), [output](validation/07-flip/output.log) |
| `headline` | 84 | [ledger](validation/05-headline/ledger.partial), [output](validation/05-headline/output.log) |
| `notify-fused-epoll` | 7 | [ledger](validation/39-notify-fused-epoll/ledger.partial), [output](validation/39-notify-fused-epoll/output.log) |
| `notify-fused-uring` | 7 | [ledger](validation/33-notify-fused-uring/ledger.partial), [output](validation/33-notify-fused-uring/output.log) |
| `ownership-extra-epoll` | 33 | [ledger](validation/36-ownership-extra-epoll/ledger.partial), [output](validation/36-ownership-extra-epoll/output.log) |
| `ownership-extra-uring` | 33 | [ledger](validation/30-ownership-extra-uring/ledger.partial), [output](validation/30-ownership-extra-uring/output.log) |
| `readlocal` | 5 | [ledger](validation/22-readlocal/ledger.partial), [output](validation/22-readlocal/output.log) |
| `readlocal-extra-epoll` | 15 | [ledger](validation/38-readlocal-extra-epoll/ledger.partial), [output](validation/38-readlocal-extra-epoll/output.log) |
| `readlocal-extra-uring` | 15 | [ledger](validation/32-readlocal-extra-uring/ledger.partial), [output](validation/32-readlocal-extra-uring/output.log) |
| `script-blocking-extra` | 15 | [ledger](validation/28-script-blocking-extra/ledger.partial), [output](validation/28-script-blocking-extra/output.log) |
| `scriptbounds-epoll-0-a0` | 3 | [ledger](validation/18-scriptbounds-epoll-0-a0/ledger.partial), [output](validation/18-scriptbounds-epoll-0-a0/output.log) |
| `scriptbounds-epoll-1-a0` | 3 | [ledger](validation/19-scriptbounds-epoll-1-a0/ledger.partial), [output](validation/19-scriptbounds-epoll-1-a0/output.log) |
| `scriptbounds-uring-0-a0` | 3 | [ledger](validation/16-scriptbounds-uring-0-a0/ledger.partial), [output](validation/16-scriptbounds-uring-0-a0/output.log) |
| `scriptbounds-uring-1-a0` | 3 | [ledger](validation/17-scriptbounds-uring-1-a0/ledger.partial), [output](validation/17-scriptbounds-uring-1-a0/output.log) |
| `scripts` | 58 | [ledger](validation/04-scripts/ledger.partial), [output](validation/04-scripts/output.log) |
| `txn-epoll` | 5 | [ledger](validation/09-txn-epoll/ledger.partial), [output](validation/09-txn-epoll/output.log) |
| `txn-uring` | 5 | [ledger](validation/08-txn-uring/ledger.partial), [output](validation/08-txn-uring/output.log) |

The directed FIFO proof has **160/160 legs**, including the final F4 waiting-to-unstarted transition. C1 has **16/16 legs**. Sustained fairness has **16/16 full 60-second legs** across db1/db16, 1s/2s, atomic 0/1 and io_uring/epoll. Every one of the 68 clients made progress in all 60 one-second windows of every leg; all legs observed FIFO waiting and passed exact final-data, counter, writer-share and inherited latency assertions. These are bounded correctness witnesses, not throughput claims.

AT4.12 has **423/423 live/oracle legs** across T1–T16 (including T11a/T11b), plus the separate owner witness in the directed group. The group records also retain execindex oracle/complexity, woundfix, exec1s, scriptfix3, multifix, climonfix4/5, FLIP/flip_stage_owed, WATCH, blocking, notifications, read-local ownership and sanitizer witnesses.

Both standard `tests/differ_gate.sh` matrices passed **938 suite legs per engine**, plus mode equivalence. Permanent seeds are 7, 19, 20 and 23; the frozen rotating seed is 21 for io_uring and 22 for epoll. Each matrix uses 47 suites in split mode and the standard armed-mode inventory excluding SORT. Each atomic=1 lifetime retains the four additional accumulated-state MULTI repeats at seed 19. The exact suite/atomic/seed/repeat tuples are checked, not merely the total.

`python3 tests/gates_test.py` passed **76/76** in the [quiet rerun](selftests/gates-test-quiet.log), with unchanged deadlines and fixture port 20199. Its first run had five scheduler-fixture timeouts during concurrent builds/traces; [both attempts](selftests/results.json) are retained. The initial PAD smoke used an unsupported Lua MGET fixture; the corrected two-GET fixture passed **16/16** image/mode/engine/namespace legs. That initial driver error remains in [pad-smoke.json](pad-smoke.json).

`make all` and every `job_production_units` target were built. Final [freshness checks](freshness.json) passed **60/60** queries: `all`, all 55 direct production-unit targets, both recursive MDB/QSBR arms, and the two blockfix makefile target groups. The phony MDB arm target is checked through its two real recursive `all` builds. All eight locked structure sizes remain enforced by compiled assertions. [Final integrity](final-integrity.json) verifies the five published image hashes, production/source identity, fresh unit identities and no listeners on ports 20100–20199. Build storage is 28,425,889,407 bytes (about 27 GiB as displayed by `du -sh`).

All **12/12 mechanism controls** in [negative/results.json](negative/results.json) detected the intended break: FIFO admission, same-turn chaining and H3 boundary service, each in both modes and namespaces. Every control requires a fired GDB breakpoint, the exact assertion and inferior exit 1. The final controls were rerun after rebuilding F4. No broken source or binary is published.

The [instruction record](instructions.md) has **48/48 ordinary-command comparisons with zero delta** and exact per-function attribution for all **96 EXEC comparisons**. Initial compiler-spill trials and the bounded IPA-budget adjustment remain recorded. No instruction count is used as a throughput verdict.

The runner pins all work to CPUs 0–31 and exports `LC_ALL=C` for server boots. Gate slots use server CPUs 0–15 and clients 16–31, eight server threads and 16 shards at ratio 6:2 unless a job specifies its own geometry. The retained-banner audit found 3,389 logs with allocation information, using only server CPUs 0–15 and ports 20100–20105. Tcl clients decode UTF-8 test names separately; their server processes inherit `LC_ALL=C`.

**NOT RUN:** the full `tests/gate.sh iteration`, all merit/depth/storm/Redis performance comparisons, the 14 generic cells and four GET/SET null cells remain maintainer work. `flip_saturated` was not run because it invokes memtier. `GATE_PROOF_NO_RATES=1` leaves the atomic throughput floor, atomic RYOW rate assertions and stream/xmove rate checks unrun while retaining their finite correctness checks. No performance or Redis-parity claim is made.

**Contract limit:** approved D-F3=no allows a previously refused writer to pass after the older EXEC places but before it starts on that shard. F4 now explicitly proves this exception. The implemented FIFO guarantee covers a live waiting EXEC and the existing started-claim predicates; an unconditional arrival-to-completion no-overtaking guarantee is not established. The fixed writer stamp prevents later EXECs from enlarging its predecessor set; progress still assumes the existing scheduler and predecessor progress.
