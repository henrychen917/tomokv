## racefix

WIP on `cx-racefix`; no push. Both findings reproduced on PRE before any
production change. Candidate correctness and hot-body validation are in progress.
The owner's hot-body stop condition remains binding; this is not a merge verdict.

PRE: `5146b78ee89b64748dd46db970efa8086f653fa0`. Both requested fetch/merges
reported already up to date. All commands use CPUs 112–127; live targets use
112–119, with ports 25175–25176. Compiler: GCC 13.3.0.

| PRE arm | SHA-256 |
|---|---|
| `build/racefix/pre/tomokv` | `3542d37f28967ea9fc0084ce1425d700b67bbd8deb3ce35fc65708ce17b449ed` |
| `build/racefix/pre/tomokv-tsan` | `64e88def88e7e40f9286b661e5134b3d6d6fd9cf25bbb824627f6b9526e27ae9` |
| `build/racefix/pre/climon` | `ec426b34da4257fe6dc8807076725affa8dc3a3e5af583cd77f0966b1f76b31c` |

SV4.9: the exact 64 SET/GET T6 client observed sampler rates 75 (split) and
80 (fused). Both runs failed on the intended counters: 5 counter reports in
split, 6 in fused, with 4 cron/writer pairs in each. TSan paired
`info_stats_tick:113–115` with the command increment at `thread.h:436`, receive
bytes at `io_loop.h:2318`, and send bytes at `wb.h:587`. Some large-template
frames had missing inline source locations; `addr2line` against the exact
hashed PRE ELF recovered them. Raw and symbolized logs are retained separately.
The runs also reported other INFO races (accept counters and writeback stats);
those are not evidence for SV4.9 and are not hidden or called fixed.

SV4.10: both modes witnessed A parked holding zero, B publishing its armed word,
then A publishing zero last, with `monitor_clients=1`. The exact SET marker was
absent for 1 second and `monitor_feed_lines` stayed at 4. Suppressing only A's
stale publication delivered the marker in both modes and advanced the feed
counter to 7. Witness serials were park=2, B arm=3, A final action=4.
The hook and DEBUG parser are inserted only into a copied witness source tree;
the default build contains neither.

Evidence: [builds](docs/racefix/pre-builds.json),
[split counters](docs/racefix/pre-counters-2s/result.json),
[fused counters](docs/racefix/pre-counters-1s-retry/result.json),
[split stale store](docs/racefix/pre-climon-2s-retry/result.json),
[fused stale store](docs/racefix/pre-climon-1s-retry/result.json),
[split suppression](docs/racefix/pre-climon-suppress-2s-retry/result.json),
[fused suppression](docs/racefix/pre-climon-suppress-1s-retry/result.json).
Initial fused attempts incorrectly supplied `--ratio`; the parser rejected
them before boot. Those failures remain recorded. Completed fused runs omit
that split-only argument. The implemented INFO field is `monitor_feed_lines`.

Candidate SV4.9 changes use relaxed atomic owner loads/stores for total commands,
the three command-count arrays, and socket byte counters. All INFO/cron readers
use relaxed loads. Files: `thread.h`, `signal.h`, `io_loop.h`, `reorder.cc`,
`wb.h`, `info_stats.cc`, and INFO aggregation in `t_server.cc`.
Candidate SV4.10 changes only `refresh_climon_armed` in `server.h`: a cold
acquire/release exchange followed by a fresh counter snapshot repairs a stale
publication. The exchange acquires preceding refreshes' mutations; only this
cold writer can retry. The per-batch reader and CLIENT PAUSE mutators are unchanged.

Two gate rows are collected before the quick-tier exit: **DQ +2 / DF +2**.
Labels: `INFO command/socket counters (TSan, both modes)` and
`Climon armed refresh + stale-store suppression control`. The TSan build has
its own readiness job; `build/racefix-climon` joins `job_production_units` and
its `make -q` list. Both labels are in the ledger fixture.

Required counts: **511 + 2 = 513 quick; 528 + 2 = 530 full**. The arithmetic
comment is above the untouched EXPECT constants. The actual fixture command
currently refuses **only** the count mismatch: source=530, fixture=530,
EXPECT_FULL=528. Its unmodified checker passes with 530 in an in-memory copy;
that projected check is not represented as a passing check of the current gate.
See [ledger projection](docs/racefix/ledger-projection.json).

Default PRE's emitted `note_command` uses two memory `incq` instructions;
[disassembly](docs/racefix/pre/note-command.txt). Candidate byte identity is
required before this fix can land. No performance claim, benchmark, or full
gate result is claimed.
