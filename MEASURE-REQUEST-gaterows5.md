## gaterows5

Base `3700b51d7`; branch `cx-gaterows5`; no push. This is a correctness receipt,
not a performance measurement request. All commands were confined to CPUs 16–31
(builds `-j16`); gate servers used 16–23, clients 24–31, and ports 44800–44899.
Production sources and `EXPECT_QUICK` / `EXPECT_FULL` are unchanged.

The tests now cover the remaining gaps, with two explicit production exceptions:
valid quoted inline decoding and the existing cross-object placement defects fail
on the headline. Those assertions remain strict; this lane does not fix production
or describe these five new red ledger rows as passing. Final run receipts and
per-row timings are recorded below and in `docs/gaterows5/`.

### Register audit

Read each requested T5 row in `/home/user/Projects/round4-read/REGISTER.md`, its
full row in the cited scope report (`testmap`, `net`, `cmd-data`, `cmd-server`,
`ex-path`, `reorder`, `structs`, `writeback`), and the HX-LB-PROBE addendum.

| Finding | Disposition and coverage |
| --- | --- |
| TM4.1 | Fixed. `feature_atomic.py` restores and checks the advertised atomic setting before and after every shared feature battery, including a failed child. It also wraps the four shared batteries in unarmed `fused-*`. The observer sends QUIT and witnesses EOF before launching the battery, so it cannot consume a maxclients slot. Intentional mode changes inside a battery remain allowed. |
| TM4.2 | Fixed. Both DEBUG-refusal paths in `scriptatomic` now increment FAIL/VACUOUS under `TOMO_GATE_STRICT=1`. A whole-battery response fixture refuses only DEBUG; all other commands use the live gate boot. The same fixture with the original silent-skip behavior exits zero and is rejected by the strict contract. |
| TM4.3 | Fixed. Pair selection and the cross-owner witness consume actual owner IDs from DEBUG SHARDS, with bounded search and a recheck. The old distinct-shard/same-owner pair is rejected. Boot atomic configuration is restored exactly. |
| TM4.4 | Fixed. `witness_contracts` permanently invokes `flakeaudit_test`, `flipctl_test`, `cd13b_window_test`, and the new label/placement contract suite. All three previously uncalled suites were also individually poisoned temporarily; the whole gate job failed each time. |
| HX-LB-PROBE | Fixed. Only an owner disagreement raises the new typed `PlacementChanged`. The admission witness spends one of its original four attempts and recreates the observer and key prefix before probing again. No writers or holds have started at that point. Malformed evidence is not retried; perpetual placement movement still fails “window never observed.” |
| NT4.17 | Partly already closed: `tls` invokes `respcompat --ntfix preauth/frontier` in both modes/engines and TCP/TLS; `respresume-*` bounds incremental parsing; `fliplisten` covers arriving and established TLS connections through FLIP. Added a standing non-BMI ROB unit and a failing missing-fence-clear control. Added four quoted-inline decoding rows: all expose the remaining production defect. |
| CD4.19 | Already covered by later standing jobs: `clientfix` geo-count/geo-store; `bugs5` scancompact; `datafix1_geo/spop/lists/locale/bitfield/hexpire/randscan`; `datafix2_notouch/watch/encoding/subkeys`; `hexpread`; `notifycompat`. These cover the full scope row's omitted COUNT ordering, mutable scan, encoding, no-op/watch/access and notification cases. No duplicate rows added. |
| SV4.15 | Already covered: `authfix` binary-password rewrite/restart and redaction; `bugs5` slowlog historical identity; `clientfix` repeated shorter pause; `serverfix_waitaof` wait lifecycle. No duplicate rows added. |
| EX4.19 | Added four live legs retaining 1030 simultaneous clients on the same DEBUG-witnessed IO owner, with balancers/FLIP disabled, remote-owner GET/ECHO ordering, three rounds and an observed final connection drain. Native production-route fixtures prove the 1025th client has no slot, claims the channel, coalesces duplicate notifications, drains and rearms. |
| RO4.1 | Standing `reorder_bounds` runs the real scan units and instrumented production parser fixtures in both database images. Quadratic demotion and eager-construction controls fail. The production fixtures cover fused rl0 and rl1; these are the two surviving R7 parser paths. Native scan accounting is transport-independent. |
| ST4.13 | Added actual vector/heap/ROB allocation assertions, plus the shared slotless coverage. The placement row exposes existing ST4.3/4/7 defects; no layout change is included. It proves addresses/line overlap, not a measured performance penalty. |
| WB4.7 / WB4.14 | Added four live legs, each booting both policies and S:D = 0:0, 2:0, 2:1, 64:255 (32 total boots). Exact CONFIG/INFO, borrowed-send counter, GET/MULTI/EXEC/REPLY OFF/ON/SKIP/DEBUG SLEEP transcript, and SKIP before PING/GET/WAIT/SCRIPT/FUNCTION/BLPOP/XREAD. An admitted MSET held at atomic publication proves the unbounded small-pipe hold and the bounded/half-policy progress controls, then exact resume replies. |

### Failing controls

Controls run inside their standing gate job unless the receipt explicitly says
that a temporary poison made the entire job fail. Temporary modified source trees,
fixtures and binaries are never linked into the production server.

| Guard | Planted control and observed rejection |
| --- | --- |
| TM4.1 | Monkeypatch restoration away: the next child rejects “stale advertised atomic arm.” Ignore CONFIG SET: the exact GET check rejects “atomic boundary mismatch.” Positive/failing children both restore arms 0 and 1. |
| TM4.2 | Whole `scriptatomic` with only DEBUG responses denied: headline exits 1 with exactly one FAIL/one vacuity; original skip fixture exits 0/zero vacuity, which fails the same strict-result assertion. The ordinary DEBUG-enabled battery must also pass first. |
| TM4.3 | Original pair fixture maps different shard IDs onto owner 6 twice; the owner-span assertion fails. New helper selects owners 6 and 7. |
| TM4.4 | Prepend an identifying RuntimeError separately to each of the three previously uncalled suites, run `GATE_ONLY_JOBS=witness_contracts`, demand nonzero exit, FAIL ledger and the exact marker, then restore original bytes. All three failed as intended. Receipts: `invocation-controls.json` and individual logs. |
| HX-LB-PROBE | One placement move reaches a second fresh observer/prefix; four consecutive moves fail the original window assertion. Unknown-shard/malformed evidence propagates on the first attempt. |
| RO4.1 | Compile the real old demotion loop and eager ShadowDispatch construction as separate test binaries in both DB images. Each exits 1 at the work-bound assertion. Headline depth 8/32/64 visits are 7/31/63 versus the quadratic controls' 28/496/2016. No-Long paths construct/visit zero; Long and demotion positive witnesses do fire. |
| EX4.19 | Native throwaway `TOMO_SLOTLESS_DROP` omits notification and exits 1 at “slotless completion must claim the channel.” The native headline covers both modes; every live mode/engine row includes positive and negative native fixtures. |
| WB4.7/14 | Monkeypatched fixtures reject a leaked SKIP reply, corrupted borrowed bytes, an ignored complete-pipe hold, and ignored boot-knob values. Live S=2/D=0/policy1 must hold the ready head while the atomic tail is held; S=0, D=1 and policy0 controls must make progress. |
| NT4.17 portable | A temporary copy of `rob.h` removes only fallback completion's MGET-fence clear; a `-mno-bmi -mno-bmi2` build exits 1 at the covered-fence assertion. The unmodified non-BMI unit passes. |
| NT4.17 quoted / ST4.13 | Headline itself still contains the defects: all quoted cases and all five placement assertions fail. No passing-headline claim or fabricated passing control is made for these production exceptions. |

### Production failures and reproduction

All new live rows boot the gate's eight-thread/16-shard geometry; split is 6 IO +
2 EX. Use the gate job interface, preserving its complete set of legs:

```sh
taskset -c 16-31 env GATE_ONLY_JOBS="inline_quoted layout_placement" \
  GATE_TEST_PORT=44898 bash tests/gate.sh iteration \
  --server-cores 16-23 --server-smt "" --load-cores 24-31 --load-smt "" \
  --ports 44850-44879
```

* `inline_quoted`: all seven valid decoding cases fail in both 1s/2s and
  epoll/uring. For example `ECHO "a b"` gives wrong arity, and the escaped/binary
  forms retain quote/backslash bytes instead of decoding. A following PING is
  checked in every case to separate incorrect argument decoding from frame loss.
  Production still describes quote validation without decoding in `src/net/resp.h`.
* `layout_placement`: actual 16-element allocations have 14 shared IoLoop
  boundaries, 8 ExLoop boundaries, 14 FusedExLoop boundaries; 16 single-DB
  StoreSizeState allocations have 8 sharing pairs; real ROB chunks have 128
  straddling inline argv Slices out of 512. This reproduces ST4.3/4/7 with the
  current types and allocator, without changing any layout lock. Runtime rounds
  this native row to 0.00 seconds; that means below ledger resolution.

### Gate counts and timing

The seven new collection sites precede the quick-tier exit. Four single-row jobs
plus three four-leg jobs add **DQ=+16, DF=+16**. The maintainer's proposed constants
are **EXPECT_QUICK=814 and EXPECT_FULL=831**, from 798/815. This lane does not edit
either constant. Existing feature/debug/atomic rows retain their labels/counts.

The label fixture was generated from source declarations, preserving duplicate
labels. It has 831 labels, exactly matching source (zero missing/extra). The
standard fixture validator deliberately fails only because protected EXPECT_FULL
remains 815. A partial passing ledger is not used to overwrite that fixture.

Collection lines are `tests/gate.sh:5486–5492`; the quick branch is at 5719
and calls its count check at 5722. They are all above that exit.

| New job / leg | Rows | Seconds | Result |
| --- | ---: | ---: | --- |
| witness_contracts | 1 | 0.67 | PASS, 8 new contracts plus the three existing suites |
| reorder_bounds, both database images | 1 | 0.09 | PASS, including four failing controls |
| rob_portable | 1 | 0.76 | PASS, includes throwaway compilation/control |
| layout_placement | 1 | <0.01 | FAIL, existing placement defects |
| inline_quoted, 1s epoll / uring | 2 | 1.48 / 1.56 | FAIL / FAIL, existing decoding defect |
| inline_quoted, 2s epoll / uring | 2 | 1.41 / 1.52 | FAIL / FAIL, same defect |
| slotless, 1s epoll / uring | 2 | 2.08 / 2.07 | PASS / PASS |
| slotless, 2s epoll / uring | 2 | 1.96 / 1.99 | PASS / PASS |
| wb_mixed, 1s epoll / uring | 2 | 13.36 / 13.56 | PASS / PASS, eight boots per row |
| wb_mixed, 2s epoll / uring | 2 | 14.05 / 13.94 | PASS / PASS, eight boots per row |

The measured added work is **70.50 serialized row-seconds**, before extra cold
build cost; `new-row-timings.tsv` identifies each raw ledger. Atomic-boundary and
strict-control overhead within existing rows was not separately isolated. Total
full-gate wall-time growth is **NOT RUN**: full iteration/performance remain with
the maintainer, and scheduler overlap prevents equating this sum with wall time.
These are correctness-row runtimes, not performance measurements.

### Harness development failures retained

The first WB hold attempt used BLPOP, which is a parser barrier and did not create
two simultaneous ROB slots; all four legs failed. The final latch uses an admitted
MSET. The first atomic boundary wrapper retained an observer and interfered with
the maxclients battery; it now witnesses QUIT/EOF before the child. The first
slotless run completed every reply but one uring shutdown raced outstanding socket
cleanup; it now observes connected_clients reach one and closes that observer.

An initial ACL-based DEBUG control also disabled scripting by the server's ACL
policy, contaminating the following xscript battery. It was discarded: the final
control changes only DEBUG responses in a temporary Python fixture and additionally
reintroduces the exact original skip. These failed development runs are retained
and are not production regression claims.

The first `gates_test.py` run hit the unchanged 45-second synthetic scheduler
deadline during heavy compilation. The later run passed all 72 tests in 97.103s;
no deadline was widened. Servertail spare-port bind failures and their final
rerun disposition are recorded with the final receipts.

### Final selected-job validation

The latest complete receipt for each required job/shape contains **254 correctness
row executions: 249 PASS, 5 FAIL**. The five failures are exactly the four quoted
inline legs and the single placement row above. This is a union of explicitly
identified selected-job runs, not a full-gate tally. `final-row-timings.tsv` records
every row's status and time, with run/job/mode; `final-jobs.json` summarizes them.

| Jobs | Declared shapes run | Final result / total row seconds |
| --- | --- | --- |
| feature-split-0 / feature-split-1 | 2s, uring, atomic 0/1 | 34/34 each; 149.91 / 104.09s |
| feature-armed-0 / feature-armed-1 | 1s, read-local 1, uring, atomic 0/1 | 35/35 each; 119.24 / 112.96s |
| fused-0 / fused-1 | 1s, read-local 0, uring, atomic 0/1 | 9/9 each; 18.56 / 20.42s |
| debug-0 / debug-1 | 2s, uring | 16/16 each; 82.37 / 79.67s |
| debug-0 / debug-1 | 1s via GATE_TXN_FUSED=1, uring | 16/16 each; 83.67 / 86.92s |
| atomic_batteries | 2s and 1s, uring | 4/4 each; 40.89 / 35.83s |
| asan_batteries | 2s and 1s, uring | 5/5 each; 37.11 / 37.14s |

All new live rows run both modes and both engines; all 32 WB boots are present.
RO's two database images and both surviving fused parser templates are present.
The existing debug/feature/atomic jobs declare uring; no unrun epoll leg is hidden
inside their receipt. Native and harness-only jobs have no network-engine leg.

Build/validation receipts:

* `make -j16 all` passed; its final warm run reports 0.02s. The gate's own
  `production_units` job built all 43 ordinary targets, both recursive
  `mdbqsbr-live-arms` images, and `blockfix-cost` plus its paired server digest.
  All **47 concrete make -q queries**, and the wrapper `make -q mdbqsbr-live-arms`,
  return zero. The cold production-units job took 594.14s (all existing targets,
  not a claim about incremental cost). The ASAN build job passed in 129.59s.
* Binary SHA-256 values for the headline, ASAN and 12 new native fixtures are in
  `binary-manifest.json`; production `src/` diff is empty. `bash -n tests/gate.sh`
  and `git diff --check` pass. Neither EXPECT assignment changed.
* Source/fixture comparison: 831 vs 831, missing/extra none; protected-count
  refusal at 815 is retained in `label-fixture-final.log`.
* Final `python3 tests/gates_test.py`: **72/72 PASS in 94.861s**, exit zero;
  `final-receipts.json` and `gates-test-complete.log` retain the result. The
  preceding successful run was 72/72 in 97.103s.

For reproduction, these are selected correctness jobs through the gate's own
interface; the `iteration` argument does **not** run full iteration when
`GATE_ONLY_JOBS` is set:

```sh
taskset -c 16-31 env GATE_TEST_PORT=44898 GATE_TXN_FUSED=0 \
  GATE_ONLY_JOBS="witness_contracts reorder_bounds rob_portable layout_placement inline_quoted slotless wb_mixed feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 fused-0 fused-1 debug-0 debug-1 atomic_batteries asan_batteries" \
  bash tests/gate.sh iteration --server-cores 16-23 --server-smt "" \
  --load-cores 24-31 --load-smt "" --ports 44851-44879

taskset -c 16-31 env GATE_TEST_PORT=44898 GATE_TXN_FUSED=1 \
  GATE_ONLY_JOBS="debug-0 debug-1 atomic_batteries asan_batteries" \
  bash tests/gate.sh iteration --server-cores 16-23 --server-smt "" \
  --load-cores 24-31 --load-smt "" --ports 44851-44879

taskset -c 16-31 env GATE_TEST_PORT=44898 python3 tests/gates_test.py
taskset -c 16-31 make -j16 all
```

The final isolated feature-split-1 run (`gate-run.z8N2vl`, ports 44851–44879)
passes all 34 rows, including all 111 servertail checks. Earlier attempts on spare
ports 44802/44822 failed with EADDRINUSE after the live-listener guard found no
listener. An ephemeral/TIME_WAIT collision is a possible cause, not established by
the retained logs. No production or servertail assertion was changed to obtain the
passing rerun.

### Evidence and explicit limits

`docs/gaterows5/receipts.tar.gz` retains gate plans, per-job output, ledgers, timings,
server logs, native/control logs, earlier failed development runs, source-fixture
refusal, build/freshness results and binary digests. `evidence-index.json` binds the
archive and lists its source runs. Native binaries remain in ignored `build/`;
throwaway control trees were removed after their expected failures.

**NOT RUN:** full `tests/gate.sh iteration`, ABBA/NIC/performance load generators,
PRE/POST throughput or c2c measurements, and full-gate wall-time growth. These
remain maintainer work under the explicit lane authorization. No PAD arm is needed:
production layout/text is unchanged. Untouched later coverage identified for CD4.19,
SV4.15 and NT4.17 was source-audited, not rerun as an extra campaign. Passing-headline
controls for quoted decoding and placement are unavailable because those production
defects remain; their failing reproductions are retained instead. No requested new
or directly touched job/declared leg was omitted.
