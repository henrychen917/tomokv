# flakefix3 — GT16b, GT18, GT19

Worktree `/home/user/Projects/cx-flakefix3`, branch `cx-flakefix3`, 2026-10-07.
Base and fetched `origin/cpp`: `dbd01dd99`. Merged before implementation and
again immediately before final serverless validation; both were already current.
Code through `e97456d2d` is committed. No push.

**Status: implementation and serverless proofs complete; live proofs pending.**
The shared lane rule reserves server, gate and load-generator execution for the
maintainer. This lane has not run those programs or claimed six clean live runs.
The commands below provide the requested proof on CPUs 112–127.

## GT16b: check the controller's reference on every attempt

`tests/flipctl.py` now captures `flipctl_anchor_rate` alongside the published
rate band when each attempt starts. Every pre-hold and hold sample must fit
both that reference and the driver's fixed pre-hold mean. A fresh driver mean
cannot conceal a departure from the retained controller reference. Invalid
pre-hold samples prevent arming; an invalid hold re-rolls. Movement when both
references certify stationarity still fails for every trigger reason.
The existing three-attempt limit, wall budget, ramp, surge, mix and movement
predicates remain intact. Logs include both anchors and their deviations.

There is a numerical distinction in the incident: **5795/6000 is a 3.4167%
decline, inside the logged 3.7104% band.** That flat trace alone must not excuse
a move. The actual retry includes 5658/s during the hold and 5645/s during
arming, outside the controller reference of 5956.288/s, while fitting the
driver reference of 5794.954/s. The recorded trace now classifies INVALID.
The requested 6000 → 5795 synthetic uses a published 3% band and is INVALID;
6000 for both anchors plus a move is FAIL. An additional control requires FAIL
for a flat 5795/s trace when the published band is 3.7104%.

`tests/flipctl_test.py`: **15 tests pass**. An in-memory mutation that replaces
the controller reference with the driver reference fails both new drift cases.

## GT18: exact metadata and candidate ordering

The production LRU clock uses five bits with `kLruClockShift = 8`: one bucket
is 256 seconds. `FlatStore::random_allkeys_candidate()` samples table positions
with replacement. Both `choose_victim` implementations make up to N draws,
discard duplicates, and rank eligible candidates by `(age << 56) | tie_break`.
There is no exhaustive scan or retained Redis eviction pool. The battery already
sets N to the maximum 64.

Consequently, increasing the old cohort cannot make a sample without an older
candidate impossible. For old-candidate probability p below one, the idealized
miss probability `(1-p)^64` remains positive; shard imbalance also matters.
The old comments claiming exact victim selection at N=64 were incorrect.
The failure log proves the old cohort crossed a bucket and all 750 measured
re-reads were lane-served, but contains no candidate trace or per-key post-touch
metadata to reconstruct the particular lost key. Sampling permits that outcome.

The live battery now establishes the exact property before pressure:

- Warm 50 still-old keys with CLIENT NO-TOUCH, then assert each starts at age
  at least 256. All 50 must reset OBJECT IDLETIME to zero after measured reads;
  50 untouched controls must remain in an older bucket.
- On the armed boot, **all 150 measured reads** must be lane-served. A dispatch
  fallback invalidates arming and retries on a fresh set of 50 old keys, bounded
  to three attempts. An executor touch from an invalid attempt cannot hide a
  broken lane touch on the next one. Exhaustion fails.
- Pressure must fire eviction and satisfy the exact identity
  `DBSIZE NOW + evicted_keys + rejected writes == 9002 offered writes`.
  INFO publishes eviction counts by batch, so the counter gets a bounded
  one-second convergence wait with 1 ms polls and no count tolerance.
- Survival counts remain diagnostics. There is no 49-key acceptance threshold;
  the replacement assertion requires the correct metadata on **every one of
  the 50 keys** before approximate sampling can remove one.

`tests/store_regression.cc` extends the existing `aof-eviction` case: it observes
the real sampler's first two distinct candidates and rewinds its test-only RNG
state. Each candidate in turn becomes the sole older key in a 64-draw sample.
The actual chooser must return that key, in ordinary and armed stores, including
clock wrap from 31 to 0. A one-draw control demonstrates that a newer victim is
legal when the older key is outside the sample. No production hook was needed.

The storage case passes. A throwaway source copy under `build/flakefix3/negative`
removes the age weight from both chooser bodies; its binary fails the new
ordering assertion. `tests/evict_battery_test.py` executes the actual Python
section without sockets: **7 tests pass**, covering a missing touch on one key,
fresh-cohort retry, absent lane/clock windows, and exact counter convergence.

## GT19: both-peer idle barrier before every differential save

`tests/differ.py` polls INFO persistence on both peers before every SAVE/BGSAVE
and before taking its `rdb_saves` baseline. Both must report
`rdb_bgsave_in_progress:0` in the same poll round. The total deadline is 10 seconds,
the poll step is 1 ms, and socket timeouts are bounded by the remaining time and
restored afterward. Missing/invalid fields and timeout fail loudly. A busy-save
reply from either peer raises a named PSFIX harness error with peer and command;
it never reaches reply comparison.

The two SAVE plus one BGSAVE operations per peer, exact `rdb_saves == before + 1`,
second INFO observation, and loading assertions remain. The standalone harness's
failed-save and AOF-rewrite counter assertions also remain exact.

`tests/differ_test.py`: **23 tests pass**, including both-peer polling, timeout,
malformed status, busy replies on either peer, and the real psfix sequence with
delayed completion. Advancing a save count by two fails. Bypassing the before-save
barrier in memory fails the real-sequence regression.

`tests/psfix.py` now accepts `--atomic`, `--seeds`, `--repeats`, and
`--bgsave-load-keys` (default zero). The directed proof seeds 4096-byte random
values, starts one independent BGSAVE on each peer before each differential leg,
and requires both jobs still active after 101 ms. The leg's own before-save
barrier must log observing BOTH busy peers; missing overlap fails. Further
external saves are not injected inside the exact +1 accounting interval: an
idle observation is not a lock against an unrelated producer, and such a race
remains a harness error. `tests/psfix_test.py`: **4 tests pass**, including
refusal of short saves and missing/one-peer overlap witnesses.

## Scope and completed validation

- **49 Python tests pass**, plus the real storage `aof-eviction` case.
- Three negative controls are rejected: erased controller reference, removed
  before-save barrier, and removed LRU age scoring.
- Python compilation, `bash -n tests/gate.sh`, and `git diff --check` pass.
- `grep` searched tests for changed literals and their plain, JSON and escaped
  encodings. Old exact-sampling claims are gone; the gate comment now describes
  exact LRU metadata/accounting checks.
- Production sources, headers, Makefile and fixture files are unchanged. Gate
  executable text is unchanged; its only edit is the descriptive comment.
  No DEBUG hook, layout change, server PRE/POST build, PAD or hot-body audit is
  needed. No performance claim is made.
- **Row delta +0 quick / +0 full.** EXPECT remains **500 / 517**. By line in this
  tree: the existing storage case loop is 1533, armed eviction collection 3276,
  flipctl collection 3302, quick exit 3361, differential folds 3393 and 3404.
  Standalone Python controls introduce no gate rows.

Evidence: [validation archive](docs/flakefix3/validation.log) and
[grep audit](docs/flakefix3/text-audit.log). Original unit outputs and the
throwaway mutant remain under `build/flakefix3/`.

Storage unit SHA-256:

```text
4cdff7e7fb43ea4bc5c9b0cf73bf2986287663b477b9356668ab7aeb67d6cedb  build/store-regression
1ac2b9a05c961a21728302f5a9d47b70a7474564b403a44d4cf74c0f64295f20  build/flakefix3/negative/store-regression
```

## Requested live proof — maintainer execution

Refresh mainline immediately before this proof. Use a new proof directory and
stop on the first failed command. Run the two gate jobs sequentially so each
uses the requested eight server cores and eight load cores.

```bash
set -euo pipefail
cd /home/user/Projects/cx-flakefix3
git fetch origin cpp
git merge --no-edit origin/cpp
mkdir -p build/flakefix3
PROOF_ROOT=$(mktemp -d "$PWD/build/flakefix3/live.XXXXXX")
taskset -c 112-119 make -j8 build/tomokv build/store-regression
python3 tests/flipctl_test.py -v
python3 tests/evict_battery_test.py -v
python3 tests/differ_test.py -v
python3 tests/psfix_test.py -v
taskset -c 112-119 build/store-regression aof-eviction
sha256sum build/tomokv > "$PROOF_ROOT/server.sha256"

for job in flipctl evict-lruclock-armed-1; do
  for run in 1 2 3 4 5 6; do
    GATE_ONLY_JOBS="$job" \
    GATE_LEDGER="$PROOF_ROOT/$job-$run-ledger" \
    taskset -c 112-127 tests/gate.sh iteration \
      --server-cores 112-119 --load-cores 120-127 \
      --server-smt '' --load-smt '' --ports 18340-18342 \
      > "$PROOF_ROOT/$job-$run.log" 2>&1
  done
done

taskset -c 120-127 python3 tests/psfix.py \
  --binary "$PWD/build/tomokv" \
  --oracle /home/user/Projects/redis74/src/redis-server \
  --root "$PROOF_ROOT/psfix" --port 18340 \
  --cores 112-119 --load-cores 120-127 \
  --mode 2s --databases 16 --atomic 1 \
  --seeds 7 28 --repeats 6 --bgsave-load-keys 131072 \
  > "$PROOF_ROOT/psfix.log" 2>&1
sha256sum -c "$PROOF_ROOT/server.sha256"
```

Decision: both gate jobs must complete six consecutive selections with zero
FAIL rows and all windows armed and completed; INVALID attempts are logged,
bounded retries, not passes. GT19 must complete **24 differential invocations**
(six repeats × two seeds × RESP2/RESP3), all with exact counters and a before-save
barrier witnessing both external background jobs. The seed load is 512 MiB of
values per peer. If either job completes too quickly, the harness fails rather
than accepting an unexercised barrier; increase the dataset on a fresh proof
run and retain the failed arming log. The chosen jobs and harness boot the
required split and fused+armed modes across the proofs.

Append the actual outcomes as `MEASURE-RESULT` with run directories, logs,
exit statuses and server SHA-256. These selections do not constitute a full
gate receipt. All six-run live outcomes are currently **NOT RUN**.
