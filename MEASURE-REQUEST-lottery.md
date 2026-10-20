## lottery

Branch `cx-lottery`, worktree `/home/user/Projects/cx-lottery`, based on
`origin/cpp` 991d48f65. Nothing was pushed.

**There are no production source changes.** `src/` and `third_party/` are
byte-identical to 991d48f65. The only change to a shared file is two opt-in
Makefile targets: `build/lottery/tomokv` and `build/lottery/tomokv-asan`.
`tests/gate.sh` is unchanged.

**Gate row delta: DQ +0, DF +0.** EXPECT_QUICK stays 625 and EXPECT_FULL stays 642.
The lottery tier sits outside the landing gate and no landing row changes.

### What a hit is

Every one of the 58 class-B row occurrences in
[remaining-v2.md](docs/flakeaudit2/remaining-v2.md) is listed in
[tests/lottery_rows.json](tests/lottery_rows.json) with the witnesses it
requires. That set equals the B rows of `triage.json`, and a unit test checks
this. An attempt is a **hit** only when every required witness is observed
within that attempt. Rows that depend on the same moment share one witness.

Witnesses come from two sources. Existing observables are used first.

* **Existing observables, unmodified production binary (11 rows).** The s6
  rows read the battery's own `A4 ... missing=0` coverage line (W3). Row 122
  reads spinprobe's `mechanism=fired` line. The four snapshot capture/reload
  rows read the INFO `snapshot_preimages` delta (W8: a write landed on an
  uncaptured key during capture). These rows run `build/tomokv` unarmed.
* **Isolated DEBUG witness build (47 rows).** This follows the
  `racefix_build.py` precedent. `tools/lottery_build.py` copies `src/` into
  `build/lottery/source` and applies 60 reviewed anchors; each must match
  exactly once or the build refuses. They are the forced include, the cold
  `DEBUG LOTTERY` subcommand, one const accessor, and observation records.
  The result is built as `build/lottery/tomokv`.
  * Nothing records until `DEBUG LOTTERY ARM <mask> <path>`, and
    `DEBUG LOTTERY STOP` writes the trace.
  * There are no holds, sleeps, clock changes or release gates, and no
    pause points.
  * Each record goes into a per-thread buffer. It is stamped by one global
    call-site counter, so "before X" and "after X" records order exactly.
  * `tests/lottery_evidence.py` reduces the records offline, in stamp order.
  * The default build never includes `tests/lottery_hooks.h`.

### Counters added: rows, moment, where

| Witness | Rows (public ordinals) | Moment that makes an attempt a hit | Where it is observed |
|---|---|---|---|
| W1 | blocking 132, 166, 215, 250, 358; servertail 149, 183, 232, 267; slowlog 300, 314 | After the battery's own propagation sleep (>= 50 ms, single sample, no retry), **every** IO and executor owner has applied the coordinator's live-config version | Owner applies in `ExLoop` (`live_config_version_` store) and `IoLoop::refresh_notify_config`; check = cold `DEBUG LOTTERY CONFIG` |
| W2.fanout | atomic_torn 126, 503; execatomic 303, 317; execiso 304, 318 | A foreign writer's group is decided **between** two fragments of one pinned multi-owner read: one fragment finished before the decision store, another began after the commit, and the writer touched keys on both sides | Read-fragment scope (`scatter_engine.inc`, MULTI MGET/EXISTS fragments), decision stores (`server.h`, `scatter_engine.inc`), commit batch |
| W2.pin_flush, W2.ryow | atomic_hazards 128 | FLUSH lands after one fragment of a pinned read finished and before another began; a RYOW dispatch holds on an own undecided predecessor | `cmd_flush` entry; `atomics_glue.inc` own-undecided defer |
| W3 | s6 130, 164, 199, 206, 213, 248; differential 515, 516 (s6fix legs) | All 200 keys drawn (`A4 ... missing=0`, both peers for s6fix) | **Existing** battery log lines |
| W4 | expwide 159, 193, 242, 277 | In each of the fanout, EXEC and script sections, a lookup whose pinned cut precedes the key's deadline while wall time has already passed it | TTL lookups in `flatstore.h`; section markers from the battery driver |
| W5 | blocking (timeout) as W1 rows; limits 139, 173, 222, 257 (idle, soft, exempt) | A finite blocker retired by its deadline; an idle close past its timeout; a soft output-limit close after its period; a blocked/subscriber client exempt past the idle timeout | `blocking.inc` timeout reply; `IoLoop` cron idle and output-buffer paths |
| W6 | xmove 310, 324 | A push to the source list's selected edge between LMOVE phase one and phase two, for both the left and right edge | `scatter_engine.inc` move phases; `push_generic` |
| W7 | DEBUG 339 | Another client's PING progresses on the same owner while the DEBUG SLEEP timer is live; the timer is cancelled before its deadline | `IoLoop` deferred timers; `cmd_ping` |
| W8 | snapshot capture/reload 341, 342, 349, 350 | A write lands on an uncaptured key during capture and is preserved as a pre-image | **Existing** INFO `snapshot_preimages` delta |
| W9 | snapshot groups 343, 344, 351, 352 | The snapshot's apply drain meets a group with some but not all of its keys installed | Group open (EXEC/MSET dispatch), per-key installs (`flatstore_atomic.inc`), drain (`snapshot.cc`) |
| W10 | spinprobe 203, 210, 366 (122: **existing** `mechanism=fired`) | A client's partial frame stays parked across both LBSIGNALS samples of the measured window | Parser Incomplete/complete (`io_loop.h`, `reorder.cc`); `DEBUG LBSIGNALS` entry |
| W11 | flip saturated 368 | Every applied FLIP met admitted work at its request (an executor inside client work, or queued executor inbox tasks) and client work completed inside its window | **Existing** per-thread ClientWorkScope epochs and inbox lane depth, read in the cold FLIP begin/complete bodies |
| W12 | TLS 443 | A connection reset mid-handshake after the server consumed part of its flight; a TLS record reassembled across reads; a TLS connection retired holding a partial parser frame | `SSL_accept`/`SSL_read`; TLS identity/retire in `IoLoop`; parser |
| W13 | differential 515, 516 (climon legs) | When each tracking comparison's collector stopped, no posted invalidation was undelivered, and no zero drain missed an emission | `pubsub_post`, tracking handle/emit (`tracking.cc`); comparison markers from the battery driver |
| W14 | differential 515, 516 (psfix legs) | The SAVE is admitted (not Busy) in every psfix leg | Snapshot admission (`snapshot.cc`) |
| W15 | differential 515, 516 (stream legs) | Every auto stream ID derives from its owner's clock cut (max of owner now and last ms, or a sequence carry) | `resolve_add_id` (`t_stream.cc`) |
| W16 | multi_exec 131, 165, 200, 207, 214, 249, 357 | A foreign reader loaded an EXEC's decision word **after the last owner joined and before the decision store** (stamp before the load, entry seen undecided) | EXEC dispatch/finalizer (`multi.inc`), resolver (`flatstore_atomic.inc`), decision (`server.h`) |

### Runner, unit tests and nightly tier

* **`tests/lottery_runner.py ROW|--all`** runs each attempt in its own process
  group, on fresh servers. CPUs are 112-119 for servers and 120-127 for
  clients; ports are 25300-25302.
  * A row stops at K hits (`DEFAULT_HITS = 20`, ledger row `LOTTERY-K`) or at
    `--cap` seconds (default 600). After the cap no new attempt starts. One
    attempt is bounded by `--attempt-timeout` (default 1800 s).
  * **PASS** needs K hits and no failed attempt. Any failure, on a hit or a
    miss, is FAIL. Evidence errors and incomplete traces are ERROR, never a
    hit.
  * Each row reports attempts, hits, hit rate, per-witness attempt counts, and
    the exact one-sided 95% Clopper-Pearson bound. With 0 failures in 20 hits
    that bound is 13.9%; the rule-of-three estimate is 3/K = 15%.
  * The bound is labelled fixed-K only on a PASS. It assumes independent,
    stationary attempts and is not a simultaneous bound over the 58 rows.
* **`tests/lottery_attempt.py`** applies the gate's boot shape for each job
  and the gate's battery arguments. It parks its harness connection while a
  battery runs, and the battery driver uses one short-lived connection per
  marker, so no extra idle client sits beside a battery.
  * The differential rows 515 and 516 run `differ_gate.sh`'s focused mode on
    their four class-B suites (s6fix, climon, psfix, stream). Each attempt
    uses every permanent seed plus one fresh seed, both atomics, the row's
    geometry and a private seed history. flakeaudit2 classes the other 40
    suites as deterministic.
* **Unit tests: 34/34 pass**
  ([log](docs/lottery/unit-tests.log), serverless).
  * Fake rows with known hit rates give the expected verdicts and bounds: a
    25% row stops at exactly 80 attempts, and the bounds match the exact
    values.
  * Other runner controls: a failure on a hit or a miss is FAIL, never-open
    rows are INSUFFICIENT, malformed or missing counters are ERROR, and an
    attempt that outlives the cap still completes.
  * Every witness reducer has negative controls: the moment is removed,
    reordered or attributed to the wrong key, connection or incarnation, and
    the hit must disappear.
  * Battery-driver controls check marker order, short-lived connections and
    refusal when an anchor changes. The calibration's own classification is
    also tested.
* **Nightly tier: `tests/lottery_nightly.sh`.** It builds `all`, the witness
  build and its ASAN twin, then runs `--all`. It is not reachable from
  `tests/gate.sh`.

```sh
tests/lottery_nightly.sh                    # every class-B row, K=20, 600 s per row
taskset -c 112-127 python3 tests/lottery_runner.py 131 --hits 20 --cap 600   # one row
python3 tests/lottery_calibration.py build/lottery/runs/<stamp>/results.json  # table
```

### Calibration

The calibration was one `--all` campaign under `taskset -c 112-127`: K=20,
**`--cap 120`** (a short cap; a row starts no new attempt after 120 s),
`--attempt-timeout 1800`, servers on 112-119, clients on 120-127, ports
25300-25302. The CPUs were shared, as described under Caveats below.

* Campaign `20261011T111536Z` ran from 19:15 to 20:59 CST: 946 attempts in
  1.7 h. Row 159 was rerun after the driver fix; its row shows the rerun.
* Generated by `tests/lottery_calibration.py --budget 600`. Machine-readable
  output: [calibration.json](docs/lottery/calibration.json), which includes
  per-witness attempt counts.
* Raw results: [main](docs/lottery/calibration/results-main.json) and
  [159 rerun](docs/lottery/calibration/results-rerun159.json).
* **Attempts for K=20** is K divided by the measured hit rate.
  **Minutes** multiplies that by the measured seconds per attempt.
* **NO (rate)** marks pause-point candidates: K attempts would fit in
  10 minutes if every attempt were a hit, so the hit rate is what falls short.
  The limiting witness and the W-primitive that would serve the row are given.
* **NO (attempt length)** marks rows where one attempt is too long for K
  attempts in 10 minutes at any hit rate. A pause point would not help those
  rows; they need a longer nightly budget.

**Outcome:**

* 31 rows reached PASS: 20 witnessed hits, every attempt passed, and
  the 95% upper bound per hit is 13.9%.
* 48 of the 58 rows can reach K=20 within 10 minutes at the measured
  rates. One of them, row 310, failed; it is analysed below.
* The other 10 cannot:
  * 6 rows are rate-limited (pause-point candidates).
  * 4 rows are attempt-length-limited.

| Row | Name | Witness | Verdict | Attempts | Hits | Hit rate | s/attempt | Attempts for K=20 | Minutes for K=20 | K within 10 min? |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 122 | idle loop ceiling (LBSIGNALS, 1s) | W10.idle | PASS | 20 | 20 | 100% | 1.2 | 20 | 0.4 | yes |
| 126 | atomic torn/window battery | W2.fanout | INSUFFICIENT | 4 | 4 | 100% | 37.7 | 20 | 12.6 | NO (attempt length) |
| 128 | atomic owner-local hazard battery | W2.pin_flush, W2.ryow | PASS | 20 | 20 | 100% | 5.6 | 20 | 1.9 | yes |
| 130 | s6 battery (atomic 0) | W3 | INSUFFICIENT | 15 | 15 | 100% | 8.2 | 20 | 2.7 | yes |
| 131 | multi_exec battery (atomic 0) | W16 | PASS | 20 | 20 | 100% | 2.5 | 20 | 0.8 | yes |
| 132 | blocking battery (atomic 0) | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.7 | 20 | 0.6 | yes |
| 139 | limits battery (atomic 0) | W5.idle, W5.soft, W5.exempt | INSUFFICIENT | 8 | 8 | 100% | 15.2 | 20 | 5.1 | yes |
| 149 | servertail battery (atomic 0) | W1 | PASS | 20 | 20 | 100% | 2.8 | 20 | 0.9 | yes |
| 159 | expwide battery (atomic 0) | W4 | INSUFFICIENT | 2 | 0 | 0 (95% < 78%) | 67.8 | - | - | NO (rate; limiting W4) - W4 held command expiry cut |
| 164 | s6 battery (atomic 1) | W3 | PASS | 20 | 20 | 100% | 5.5 | 20 | 1.8 | yes |
| 165 | multi_exec battery (atomic 1) | W16 | PASS | 20 | 20 | 100% | 2.6 | 20 | 0.9 | yes |
| 166 | blocking battery (atomic 1) | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.7 | 20 | 0.6 | yes |
| 173 | limits battery (atomic 1) | W5.idle, W5.soft, W5.exempt | INSUFFICIENT | 8 | 8 | 100% | 15.1 | 20 | 5.0 | yes |
| 183 | servertail battery (atomic 1) | W1 | PASS | 20 | 20 | 100% | 3.2 | 20 | 1.1 | yes |
| 193 | expwide battery (atomic 1) | W4 | INSUFFICIENT | 3 | 0 | 0 (95% < 63%) | 53.7 | - | - | NO (rate; limiting W4) - W4 held command expiry cut |
| 199 | fused s6 battery (atomic 0) | W3 | INSUFFICIENT | 17 | 17 | 100% | 7.2 | 20 | 2.4 | yes |
| 200 | fused multi_exec battery (atomic 0) | W16 | PASS | 21 | 20 | 95% | 2.9 | 21 | 1.0 | yes |
| 203 | fused spinprobe battery (atomic 0) | W10 | PASS | 20 | 20 | 100% | 2.5 | 20 | 0.8 | yes |
| 206 | fused s6 battery (atomic 1) | W3 | PASS | 20 | 20 | 100% | 6.0 | 20 | 2.0 | yes |
| 207 | fused multi_exec battery (atomic 1) | W16 | PASS | 21 | 20 | 95% | 2.6 | 21 | 0.9 | yes |
| 210 | fused spinprobe battery (atomic 1) | W10 | PASS | 20 | 20 | 100% | 2.4 | 20 | 0.8 | yes |
| 213 | fused+armed s6 battery (atomic 0) | W3 | PASS | 20 | 20 | 100% | 2.1 | 20 | 0.7 | yes |
| 214 | fused+armed multi_exec battery (atomic 0) | W16 | PASS | 20 | 20 | 100% | 2.4 | 20 | 0.8 | yes |
| 215 | fused+armed blocking battery (atomic 0) | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.6 | 20 | 0.5 | yes |
| 222 | fused+armed limits battery (atomic 0) | W5.idle, W5.soft, W5.exempt | INSUFFICIENT | 8 | 8 | 100% | 15.0 | 20 | 5.0 | yes |
| 232 | fused+armed servertail battery (atomic 0) | W1 | PASS | 21 | 20 | 95% | 2.7 | 21 | 1.0 | yes |
| 242 | fused+armed expwide battery (atomic 0) | W4 | INSUFFICIENT | 3 | 0 | 0 (95% < 63%) | 43.2 | - | - | NO (rate; limiting W4) - W4 held command expiry cut |
| 248 | fused+armed s6 battery (atomic 1) | W3 | INSUFFICIENT | 10 | 10 | 100% | 12.0 | 20 | 4.0 | yes |
| 249 | fused+armed multi_exec battery (atomic 1) | W16 | PASS | 21 | 20 | 95% | 2.8 | 21 | 1.0 | yes |
| 250 | fused+armed blocking battery (atomic 1) | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.8 | 20 | 0.6 | yes |
| 257 | fused+armed limits battery (atomic 1) | W5.idle, W5.soft, W5.exempt | INSUFFICIENT | 8 | 8 | 100% | 15.0 | 20 | 5.0 | yes |
| 267 | fused+armed servertail battery (atomic 1) | W1 | PASS | 21 | 20 | 95% | 3.1 | 21 | 1.1 | yes |
| 277 | fused+armed expwide battery (atomic 1) | W4 | INSUFFICIENT | 3 | 0 | 0 (95% < 63%) | 44.4 | - | - | NO (rate; limiting W4) - W4 held command expiry cut |
| 300 | slowlog battery (atomic 0) | W1 | PASS | 20 | 20 | 100% | 1.8 | 20 | 0.6 | yes |
| 303 | execatomic battery (atomic 0) | W2.fanout | INSUFFICIENT | 6 | 6 | 100% | 22.3 | 20 | 7.4 | yes |
| 304 | execiso battery (atomic 0) | W2.fanout | INSUFFICIENT | 8 | 8 | 100% | 16.5 | 20 | 5.5 | yes |
| 310 | xmove battery (atomic 0) | W6.left, W6.right | FAIL | 6 | 5 | 83% | 1.7 | 24 | 0.7 | yes |
| 314 | slowlog battery (atomic 1) | W1 | PASS | 20 | 20 | 100% | 2.1 | 20 | 0.7 | yes |
| 317 | execatomic battery (atomic 1) | W2.fanout | INSUFFICIENT | 6 | 6 | 100% | 20.4 | 20 | 6.8 | yes |
| 318 | execiso battery (atomic 1) | W2.fanout | INSUFFICIENT | 9 | 9 | 100% | 14.0 | 20 | 4.7 | yes |
| 324 | xmove battery (atomic 1) | W6.left, W6.right | INSUFFICIENT | 102 | 0 | 0 (95% < 3%) | 1.2 | - | - | NO (rate; limiting W6.left) - W6 LMOVE phase-one hold |
| 339 | DEBUG toggle/reload battery | W7.progress, W7.cancel | PASS | 20 | 20 | 100% | 1.7 | 20 | 0.6 | yes |
| 341 | snapshot concurrent cut (epoll) | W8 | PASS | 20 | 20 | 100% | 3.6 | 20 | 1.2 | yes |
| 342 | snapshot cut reload (epoll) | W8 | PASS | 20 | 20 | 100% | 2.4 | 20 | 0.8 | yes |
| 343 | snapshot never tears a cross-shard MSET group (epoll, atomic 1) | W9 | INSUFFICIENT | 18 | 18 | 100% | 7.0 | 20 | 2.3 | yes |
| 344 | snapshot never tears a MULTI/EXEC group (epoll, default atomic 0) | W9 | INSUFFICIENT | 13 | 11 | 85% | 9.4 | 24 | 3.7 | yes |
| 349 | snapshot concurrent cut (uring) | W8 | PASS | 20 | 20 | 100% | 2.3 | 20 | 0.8 | yes |
| 350 | snapshot cut reload (uring) | W8 | PASS | 20 | 20 | 100% | 1.5 | 20 | 0.5 | yes |
| 351 | snapshot never tears a cross-shard MSET group (uring, atomic 1) | W9 | INSUFFICIENT | 17 | 17 | 100% | 7.1 | 20 | 2.4 | yes |
| 352 | snapshot never tears a MULTI/EXEC group (uring, default atomic 0) | W9 | INSUFFICIENT | 13 | 10 | 77% | 9.3 | 26 | 4.0 | yes |
| 357 | MULTI feature battery | W16 | PASS | 21 | 20 | 95% | 2.7 | 21 | 0.9 | yes |
| 358 | blocking feature battery | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.8 | 20 | 0.6 | yes |
| 366 | partial-frame conn parks (no io spin) | W10 | PASS | 20 | 20 | 100% | 2.4 | 20 | 0.8 | yes |
| 368 | FLIP applies under saturated load | W11 | INSUFFICIENT | 20 | 18 | 90% | 6.3 | 23 | 2.4 | yes |
| 443 | TLS pipeline/torn-record/coexistence battery | W12.handshake, W12.record, W12.parser | INSUFFICIENT | 8 | 0 | 0 (95% < 31%) | 16.2 | - | - | NO (rate; limiting W12.handshake) - W12 per-connection TLS stage hold |
| 503 | atomic torn/window under ASAN | W2.fanout | INSUFFICIENT | 4 | 4 | 100% | 34.9 | 20 | 11.6 | NO (attempt length) |
| 515 | Redis 7.4 differential matrix | W3, W13, W14, W15 | INSUFFICIENT | 1 | 1 | 100% | 846.2 | 20 | 282.1 | NO (attempt length) |
| 516 | Redis 7.4 differential matrix (armed fused + read-local) | W3, W13, W14, W15 | INSUFFICIENT | 1 | 1 | 100% | 786.2 | 20 | 262.1 | NO (attempt length) |

**Rows that cannot reach K=20 within 10 minutes, and what would serve them:**

| Rows | Limit | What the witnesses show | Pause point that would serve them |
|---|---|---|---|
| expwide 159, 193, 242, 277 | Hit rate 0. W4 requires all three sections | In every attempt the fanout section (14 lookups) and the EXEC section (108) straddled the deadline. The script section never did: S4 arms its keys 190 ms before the script's cut, so no lookup can see a live cut over an elapsed deadline | **W4**: a held command expiry cut for the script variant (and read-local/EXEC). The fanout and EXEC legs alone would reach K quickly |
| xmove 324 (atomic 1) | Hit rate 0/102 | The battery skips the concurrent inter-hop cell at atomic 1 ("atomic-on mover stage two is documented scope"). The moment is never exercised | **W6**: a phase-one hold for the atomic-on mover |
| TLS 443 | Hit rate 0/8 | Torn record in 8/8 attempts; partial parser frame at teardown in 2/8; RST mid-handshake after consumed input in 0/8: the server never processed the partial ClientHello of any of the 16 raw RST connections before its reset | **W12**: per-connection TLS stage hold (partial handshake, then parser) |
| differential 515, 516 | Attempt length (one focused matrix attempt takes 13-14 min; 1/1 hits, all four witnesses in every leg) | All 10 climon legs were fenced; every psfix leg recorded admitted SAVEs; every stream auto ID came from its owner's clock; s6fix covered all 200 keys on both peers | None. K=20 needs about 4.5 h per row; run them in a separate long budget, or split per suite |
| atomic_torn 126, ASAN 503 | Attempt length (35-38 s per attempt; 100% hits) | Every attempt witnessed a commit between pinned fragments | None; needs about 12-13 minutes for K=20 |

**FAIL: 310 (xmove, atomic 0).** Five of six attempts passed and hit both
edges. The sixth failed: `concurrent same-edge LMOVE reply: got b'new-edge',
wanted b'moved'`, with W6.left=0. That makes it a miss, but a failure on a miss
is still FAIL.

* The trace shows why. The pusher's LPUSH was sent 0.5 ms after the mover's
  LMOVE, on a different connection. Its push records (call-site stamps
  3729-3730) precede LMOVE phase one (`move_selected` at 3731).
* So the server moved the then-current left element. `new-edge` is the
  correct reply for that order.
* The battery assumes cross-connection arrival order from a 0.5 ms send gap.
  This looks like a test-side timing assumption (a lottery the cell itself
  draws), not a server defect.
* It is reported as found. The battery was not changed. Evidence:
  [row log](docs/lottery/calibration/evidence-310/row.log),
  [trace excerpt](docs/lottery/calibration/evidence-310/trace-excerpt.txt),
  [full trace](docs/lottery/calibration/evidence-310/server.trace.gz).

### Identity proof: unarmed default build versus 991d48f65

The method is docs/ttlclean's. PRE is `build/lottery/pre`, built from an exact
copy of 991d48f65; all 212 tracked files are verified byte-identical. POST is
the worktree's `build/tomokv`. Both were built under `taskset -c 112-127`
with GCC 13.3.0.

| Check | Result |
|---|---|
| `tools/lbstall_artifacts.py compare` hot bodies (`tomo` 601 + `tomo_db0` 603) | **1204/1204** raw-byte equal and equal with resolved relocation targets |
| `tools/ccfix_audit.py` full inventory, both namespaces | **16,439/16,439** bodies equal, **0 changed**; command handlers 1211/1211; hot selection including executor run bodies 1208/1208 |
| `docs/deadswitch/linked_bytes.py` | All 31 loadable sections equal (contents, address, size, alignment) except the GNU build-ID note; `.text` 7,646,972 bytes in both |

**Changed bodies: none.** The receipts are [hot](docs/lottery/identity/hot.log),
[full](docs/lottery/identity/full/summary.json),
[changed-bodies (empty)](docs/lottery/identity/full/changed-bodies.json),
[linked](docs/lottery/identity/linked.json), and the
[proof index](docs/lottery/proof.json).

### Builds and tests

* **`make all`:** PRE and POST both built with exit 0
  ([PRE log](docs/lottery/pre-build.log), [POST log](docs/lottery/post-build.log)).
  POST is fresh at HEAD ([make-all.log](docs/lottery/make-all.log)).
* **Witness build:** `make build/lottery/tomokv build/lottery/tomokv-asan`
  exited 0 with 0 warnings ([log](docs/lottery/witness-build.log)).
* **job_production_units:** all **29/29** targets built with exit 0, and all
  29 pass the gate's `make -q` freshness check. `mdbqsbr-live-arms` also
  exited 0 ([summary](docs/lottery/production-units/summary.txt)).
* **`python3 tests/gates_test.py`:** the run after my builds finished passed
  **65/66**, plus the nested **14/14**
  ([log](docs/lottery/gates-test.log)).
  * The one failure is a deadline: the scheduler fixture hit its 45 s
    `timeout` (exit 124). Another lane was running a full
    `gate.sh iteration` on CPUs 112-127 at the time.
  * The same test passed alone ([rerun](docs/lottery/gates-test-rerun.log)).
  * An earlier run, made while my own builds were running, had nine failures,
    all of them this exit-124 deadline
    ([log](docs/lottery/gates-test-contended.log)).
  * No assertion was changed.

### Caveats

* **The lottery tier tests the witness build.** For 47 rows the binary under
  test is production plus observation anchors. A recording costs one stamp
  and one count atomic plus a buffer append, and only while armed; unarmed it
  costs one relaxed load and a branch. Its timing is therefore not
  production's. The 11 existing-observable rows run production itself.
* **The calibration ran on shared CPUs.** CPUs 112-127 were shared with
  compiles from other lanes and with one lane's full gate iteration. Hit rates
  and attempt times are specific to this box and this load.
* **Snapshot rows 344 and 352 assert load floors.** One floor needs more than
  10,000 storm group writes; another needs more than 200 live MGETs.
  * They passed every calibration attempt (13 each).
  * In smoke runs made while my own builds loaded 112-127, 344 failed only on
    these floors (6,080 and 8,480 writes). No cut was ever torn.
* **Row 159 had an extra run.** Its first calibration attempt failed in the
  battery driver: the observer helper was shadowed by a loop variable. That
  was a lane defect, fixed in cc63b2d73 with serverless controls. Rows 193,
  242 and 277 ran after the fix.
  * Row 159's table entry is the rerun: 2 attempts, both passed, 0 hits.
  * The original failure is kept in
    [campaign-main.log](docs/lottery/calibration/campaign-main.log).
