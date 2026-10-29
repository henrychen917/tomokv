# Wave 10 landing request

## wave10 integration

Worktree `/home/user/Projects/cx-wave10`, branch `cx-wave10`, headline
`393d6ceb129d8c99dffd70959d6a19267c525fe0`. No push. Builds and authorized
correctness work use CPUs 64–95 and ports 20000–20099. Performance runs and the
full gate iteration remain with the maintainer. This is an in-progress record;
unrecorded verification is not a pass.

Merge order: snapfix2, blockfix3, scriptfix2, exec1s-d, pubtrackfix, infofix,
rlfix4. Every lane is merged with `--no-ff`. The committed blockfix3 report is
the `## blockfix3` section of `MEASURE-REQUEST-blockfix2.md`; the separately
named `MEASURE-REQUEST-blockfix3.md` does not exist on that branch.

LAT-HIST-2 is included under the maintainer's 2026-10-29 ruling, with exact
individual command timing. The global slowlog ring is excluded. Protected
EXPECT assignments remain unchanged; final declared rows and their collector
positions will determine the requested landing counts.

### Semantic interactions

Pending source audit and directed checks: prepared snapshot capacity with eager
EXEC reclamation; shutdown/script apply brackets and EXEC retirement; eviction
with prepared/capturing snapshots and pinned versions; script escalation and
wound publication; NOGROUP accounting; disabled EXEC latency timing; read-local
readers with X2; central CR/LF error framing; and the Tcl promotion union and
planted regression.

### harness

The named slowlog ordering assertion will use the existing one-fresh-server
ORDER_TESTS mechanism, under REGISTER item `SLOWLOG-EXEC-BLOCKED-ORDER`.

### owner-visible

rlfix4 retains `no_stack_protector` on `FlatStore::hash_key`. This is an explicit
hardening relaxation. Its integrated-layout merit remains for the maintainer.
exec1s-d's historical seed-22 SAVE rejection and X3 idle rotation's seven extra
instructions remain open evidence, not claimed fixes.

### Delivery and measurement

Required arms: PRE, POST, POST-minus-rlfix4, and PAD-A (kind A, PRE behaviour with
candidate layout control). Final hashes, control limitations, instruction/body
receipts, correctness results, NOT RUN items and exact maintainer cells will be
recorded here before delivery. No throughput claim is made.

Snapshot merge resolution: retain wave 9’s stronger at412 APPLY-window witness.
Retain the existing `xshard_complete_script_final` close, omitting snapfix’s
redundant `script_snapshot_done` close; every Final still closes owner-side.
Initial Makefile choices are provisional until the compile-only budget trials.

### Exact declaration inventory

All seven lane merges are complete: snapfix2 `f146fdbca`, blockfix3 `047ccf869`,
scriptfix2 `8fe881fa2`, exec1s-d `30a83e4d7`, pubtrackfix `87e964b71`, infofix
`d47af69b2`, rlfix4 `d53549aa4`. The commit immediately before rlfix4 is
`ba2130b37`; its production source is identical to the built slowlog-exclusion
commit `e98831c81` (the intervening commit changes only the Tcl harness).

The full source declaration inventory is 963, exactly matching the explicit
fixture including duplicates. Required landing counts are **946/963**, from
881/898 plus **65/65**: snapshot 4, restored blocking row 1, scripting 48,
EXEC 4, pubsub/tracking 4, retained INFO/latency 4, read-local 0. Blockfix3 adds
zero on its lane base but restores one row parked on this headline; infofix
loses its global slowlog row. Neither exec1s-d nor pubtrackfix supplied their
four labels in the merged fixture; those eight declarations are now explicitly
listed. The interaction checks extend existing rows and add no public row.
Collector positions and final receipts will be recorded after harness edits.

### Interaction source findings and new witnesses

- Snapshot preparation reserves at least the old table capacity. X2 calls the
  existing bounded cleanup with the commit cutoff read before the reader floor;
  collapse refuses an active capture. New `exec1s` subcases hold actual pending
  EXEC versions, prepare/mark around eager cleanup, complete a real capture,
  and check exact final values. Both modes and atomic settings run the same
  cases, with ordinary and armed read-local retirement.
- Eviction rejects candidates requiring versions and returns immediately during
  capture. The new subcases require zero eviction while pins/capture are live,
  then require actual eviction after their release. Prepared capacity and the
  capture stream must remain usable throughout.
- The X2 armed collapse still selects `atomic_free_entry_read_local` and QSBR
  object retirement. rlfix4 changes admission/hash code and does not touch that
  selection. The existing concurrent word/byte-wrap TSan falsifier remains in
  every complete exec1s job; new snapshot subcases require deferred retirements.
- scriptfix2's new invocation environment stays inside each optimistic attempt;
  at412c's claim/wound/handoff machinery is retained. `tests/wave10.py`, attached
  to the existing eight-leg execfair job, adds the witnessed nine-conflict
  escalation schedule for a shebang script, uppercase EVALSHA, and uppercase
  FCALL using restricted library initialization and numeric child arguments.
  The existing at412 owner check still covers the wound-publication interval.
- Blockfix3 owns the NOGROUP increment at the actual XREADGROUP reply. INFO reads
  that counter and its RESETSTAT baseline. Infofix contains no generic formatter
  accounting hook, so the merged tree does not introduce double accounting.
- The new error sites retain central CR/LF builders; the complete supplement is
  `docs/crlffix/wave10-added-sites.json` and the wave10 section of its audit.

Harness changes so far: add the single named slowlog assertion to ORDER_TESTS
under `SLOWLOG-EXEC-BLOCKED-ORDER`; expand the existing retry falsification test
over every named map entry. All ten Tcl harness tests pass. No blanket retry,
new timeout or assertion tolerance is introduced. New snapshot/eviction/script
interaction checks and the two Lua reply-API CR/LF checks extend existing jobs.

Global slowlog exclusion: restore `src/cmd/slowlog.cc` byte-for-byte from
headline, dropping only that part of `7c50db206`. Omit the new `infofix_compat-slowlog`
row (infofix contributes +4, not +5). Restore these seven named Tcl skips with
their headline reasons:

- `SLOWLOG - GET optional argument to limit output len works`
- `SLOWLOG - can clean older entries`
- `SLOWLOG - commands with too many arguments are trimmed`
- `SLOWLOG - get all slow logs`
- `SLOWLOG - logged entry sanity check`
- `SLOWLOG - max entries is correctly handled`
- `SLOWLOG - too long arguments are trimmed`

### Compile-only budget selection

All 31 budgeted translation units were compiled at the inherited value and the
headline budget plus the measured IPA-size delta, with ±8 trials. Linked-body
scoring selected one further change: DB0 `t_server.o`, 33883 → 33911. All other
provisional merged budgets won or tied their trials. Full compiler commands,
IPA sizes, digests and scores are in `docs/wave10/budgets/`.

The new snapshot fixture initially tore down its sidecar before draining its
private QSBR queue; those eight read-local subcases crashed during test cleanup.
The fixture now drains before disarming and releasing the sidecar, matching
production teardown. The complete `exec1s` gate job then passed all four public
rows and their internal subcases, including the concurrent X2 reader falsifier.
This was a fixture repair, with no production-path change.

Harness: extend the existing partial-only `GATE_PROOF_NO_RATES=1` to omit
`--release-build` timing ratios from stream and xmove batteries. Their data,
concurrency and mechanism checks remain present; full gate behavior is unchanged.
The flag now rejects a non-partial invocation at entry. Those timing ratios,
the atomic throughput floor, and the efficiency scaling benchmarks are NOT RUN
in this lane and remain in the maintainer's landing gate.

Real interaction found: scriptfix2 pre-sanitized the FUNCTION LOAD unknown-option
argument before crlffix's central error builder. Trailing CR/LF had already become
spaces, so the builder could no longer trim them as Redis does. The existing
CR/LF job rejected 32 exact comparisons (two suffix shapes × all 16 configurations).
Pass the raw length-bearing argument to the same central builder instead. The
new Lua error/status API checks passed; framing and following PING/ECHO remain
mandatory. This repair has its own commit and the whole CR/LF job will be rerun.

Harness interaction found in the complete Tcl receipts: excluding the global
ring also requires restoring headline slowlog `isolated_tests`. The zero-capacity
assertion otherwise leaves the rewritten-command check with capacity zero.
Restore its exact isolated setup and apply the named ORDER_TESTS retry to isolated
assertions too. This retains the original assertion and its one-retry bound.
Concurrent-build Tcl runs also timed out in the Lua GC assertion before reaching
the planted uppercase-SHA regression; those attempts do not prove falsification.
They are retained and Tcl will run again without concurrent compilation.

Harness: the lottery disposable-source builder rejected pubtrackfix’s new
`tracking_emit_invalidation(..., bool batched)` signature. Update its exact-count
anchor; the observation stays at the same entry point and no production hook
is introduced. The rejected build log is retained before the complete rebuild.

### Final serverless instruction evidence

`docs/wave10/instructions/comparison.md` contains all 116 PRE/POST cells.
GET and SET are exactly flat; INCR is flat in DB0 and -11 per operation in the
normal namespace. MGET/MSET have no positive total. EXEC totals fall by
1,924–4,044 instructions; read-local GET falls by 10/23 at batch 1 and 320/612
at batch 32 (normal/DB0). EVAL single-shard adds 686/637 and cross-shard adds
283/266 (normal/DB0), principally scriptfix2’s case-normalized SHA lookup and
protected invocation environment. These are instruction counts, not rate claims.

The 47 positive body subtotals in EXEC/EVAL/read-local all have lane/commit
attribution in `comparison.json`; both signs are retained, including changes
in outlined function signatures. The only integration production repair is the
FUNCTION LOAD error suffix, outside these scopes. Every counted body binds to
its same-arm server: PRE 547/547 and POST 551/551, zero mismatches. PRE binds
to the supplied frozen headline, not merely the local source rebuild.

The final normalizer resolves actual 10-byte x87 and 16-byte SIMD constants
and checked switch-table destinations. It preserves opcodes, registers,
immediates, member offsets, padding and branch destinations. Moving the fixture’s
preparsed EVAL hash before the scope removed a private fixture clone from counts;
the earlier counts and their mismatches remain marked as superseded evidence.

Harness: the real scheduler self-tests rejected a stale
`infofix_compat-slowlog` queue entry left after its collector was removed.
Remove that entry as part of the global-ring exclusion; the collector/fixture
inventory remains 946/963. The initial concurrent standalone/selftest attempts
also collided on reserved port 20098. Preserve those failures and rerun these
controls sequentially; no timeout or assertion is relaxed.

The repaired real-tree `python3 tests/gates_test.py` passes all **73 tests**.
The earlier 15 failures comprise the stale slowlog queue entry, scheduler
deadlines under concurrent selftests, and the shared-port collision; those logs
are retained. The final run is sequential with the other selftest campaign.

Both disposable lottery and publishfix schedule builds succeeded and are fresh
under `make -q`; hashes and exact commands are in `variant-builds.json`.
The separately delivered current-layout no-rlfix4 control removes only rlfix4’s
production diff from final POST. This supplements the requested literal
pre-rlfix4-merge arm, which predates the later cold CR/LF repair and DB0 budget
selection. It gives the maintainer a direct integrated-layout inclusion control.

All **56 production-unit freshness checks**, plus `make -q all`, pass.
An initial discovery probe also attempted three parbuild-only readiness marker
names as Makefile targets; they have no such rules. Those lookup errors remain
in `freshness-discovery.json`, separate from the required 56 checks.

Final Tcl positive attempt (`final-tcl`): both modes completed, with only
infofix’s documented promoted CLI-hint failure for unsupported MIGRATE. The
restored isolated slowlog assertion and all other required scripting/INFO/reload
assertions pass. This is **not a green Tcl job**. No skip was added for MIGRATE.

### Additional integration repairs and artifact equivalence

The source-identity gate rejected exec1s's telemetry field-name stringification.
Commit `9bacbe2d6` replaces it with explicit literal metric labels. The rebuild
has exactly identical executable bytes, function symbols, addresses and data
layouts. The only allocated-data changes are two eight-byte INFO build-commit
strings (`11f52599` to `9bacbe2d`); the GNU build ID and debug data also change.
`source-labels-identity.json` checks every other allocated byte, with no opcode
normalization. The frozen rebuild is `POST-source-labels`, SHA-256
`844cf188071bae335a80e8ae15c2acaec2d1f583f235edf4bf4496421299660e`.
The earlier `ed88bd...` correctness and instruction receipts remain valid evidence
for the identical command code; their original hashes are preserved.

The complete AUTH job exposed one stale DEBUG assertion: it still expected
`ERR appendonly is disabled`. Commit `75cb895ab` checks the accepted offline
LOADAOF behavior instead: Redis's exact missing-file error, destruction of a
seeded key, and appendonly remaining disabled. The existing infofix oracle row
independently compares this behavior with Redis. No row is removed.

The named Tcl planted-error proof is now explicit in `tcl-final-proof.json`.
`SCRIPT-ERROR-WORDING` makes the promoted no-arguments redis.call/pcall assertion
fail in both modes; final POST passes that assertion. The mutant's later Lua GC
timeout and known CLI-hint failure are recorded separately, and do not substitute
for the named failure.

### Maintainer measurement plan — NOT RUN

Use final arm hashes and the gate's existing instrument, load plans and acceptance
rules. Keep latency tracking off for the null and fixed-anchor races. Record the
actual geometry; do not substitute correctness geometry for a reviewed ABBA
geometry. Include contemporaneous byte-identical null controls. Rate at matched
offered load decides merit; cycles/op, instructions/op, IPC and latency explain it.
No failing cell may be averaged away.

1. Wave null: POST versus headline PRE, the unchanged 28 cells in
   `docs/wave10/cells/null28.txt`, with three blocks for `notify_exm`. Retain the
   TTL 20M-key expiry witnesses, split GET/SET and p8 MGET/MSET cells. Also compare
   POST-layout with PAD-A; PAD-A is **kind A: PRE behavior in the common candidate
   control image**, not a same-size twin of the smaller release POST.
2. EXEC merit: `/home/user/Projects/calib/exec-merit.py`, all eight
   `x{1,2}s_a{0,1}_{unc,hot}` cells, `--conns 64 --threads 16 --cells all
   --blocks 3 --secs 20`. Pipeline remains 4, with four plain INCR writers on hot
   cells; databases=1, 1s read-local=1/64 shards, 2s ratio=6:2/16 shards. Key/client
   balancing and automatic FLIP remain off as the driver specifies. Compare
   POST/PRE and POST-layout/PAD-A. Report EXEC and competing plain-write rates
   separately, plus retries, claim visits, eager collapses, extra passes,
   kernel entries, WB sends/retirements, cycles/op, instructions/op and IPC.
3. Depth sweep: `/home/user/Projects/calib/exec-depth-sweep.py`, PRE and POST; both
   modes, atomic 0/1, placements `cross,same-owner,same-shard`, depths
   `16x1,16x4,32x4,64x4,128x4`, `--blocks 3 --secs 10`. Retain cross/same-owner
   64x4/16x4 >=0.90 and 128x4/16x4 >=0.85, and X2's stricter same-shard
   64x4/16x4 >=0.95 in each mode. Exact order violations must remain zero.
4. Fixed-anchor race against `/home/user/Projects/bench-bins/tomokv-headline-991d48f65`
   (hash in `fixed-anchor.json`): `cells/generic14.txt`, the nine explicit
   `rl=1` cells in `cells/readlocal9.txt` with three blocks, and the EXEC matrix
   above. Retain this independently of the wave null. For rlfix4 inclusion, also
   compare POST against `POST-without-rlfix4-current` on those read-local cells
   and the null; this holds the other integrated code and selected budgets fixed.
   The required literal `POST-minus-rlfix4` is delivered too, with its older
   budget/cold-error difference documented.
5. Contended-script storm: `/home/user/Projects/calib/script-storm-merit.py`,
   POST/PRE, `--blocks 3 --secs 30`; its T6 shape is 2s ratio 6:2, 16 shards,
   atomic 0, databases=1, two keys on distinct owners, eight EVAL clients, four
   EXEC clients, four WATCH/EXEC clients and four plain writers. Require exact
   final data, zero POST script refusals and zero atomic order violations; report
   successful scripts, EXEC, plain writes and WATCH aborts separately.
6. Sixteen-save BGSAVE curve: PRE/POST, both modes and engines, atomic 1, 16
   shards, databases=16, read-local 1 in 1s/0 in 2s, balancing/automatic FLIP off,
   idle one-key fixture, save rules disabled. Use `tests/snapfix.py --case
   bgsave-loop --saves 16 --stall 300 --atomics 1 --no-oracle`, supplying each
   frozen `--binary`, the Redis `--oracle`, assigned `--cores`/`--port`, and
   distinct `--output` directories. Each `rss.json` must record all 16 saves
   even if PRE exits at the RSS assertion. Compare the full RSS and command-send
   to BGSAVE-acceptance latency curves; POST must meet the existing RSS bound.
7. Landing `tests/gate.sh iteration`, after the owner updates EXPECT to
   **946/963** and resolves the documented CLI-hint compatibility policy. The
   real worktree's protected assignments remain **881/898**.

For the external EXEC/depth/storm drivers, an explicitly scoped placement is
`--server-cores 64-71 --load-cores 72-95 --port 20000`; the maintainer schedules
the quiet box and may use its established wider instrument placement. Use
`/home/user/Projects/cx-exec1s-d/build/benchtxn` for EXEC/depth and record its hash.
Do not run the two snapshot arms concurrently. The measurement cell files and
fixed anchor are hashed; append results as MEASURE-RESULT.
