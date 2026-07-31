# BIGSTRESS acceptance specification and conformance report

## Release verdict

The corrected release has **no failed or skipped conformance cases**. The
authoritative full run completed in 3,833.11 seconds (63.89 minutes):

```text
SUMMARY PASS=29 FAIL=0 INCONCLUSIVE=12 SKIP=0 TOTAL=41 MODE=FULL
```

All properties that can engage in a supported topology conform. The 12
inconclusive rows are explicitly unqualified, not passed: true DICT auto is a
non-convertible 1-IO/1-EX shape, DICT has only one ownership worker per node,
and DICT auto has only one socket owner. Exact data checks passed in every one
of those rows; only the impossible conversion, ownership-move, or live-handoff
prerequisite is unqualified.

| Item | Qualified value |
|---|---|
| Candidate commit | `e511d6c3a5aa77e66c0e09142b33e0e74238cf4d` |
| Candidate binary | SHA-256 `a26990e9d57b0618faba5f4bcf4c05b2d6eded55fb05b5c4dc1733373c8d6bfd`; embedded SHA `e511d6c3:0` |
| Surface baseline | commit `13f39c6f`; SHA-256 `1ac3e4df8c31539f932940115ef88eee159417640ec7cae052a726a6a342be8b` |
| Full-run artifacts | `/shared/Projects/.claude/jobs/fd085c8e/tmp/bigstress.D8KyVJ` |
| Full-run duration | 3,833.11 s |
| QUICK evidence | 293.46 s; `PASS=20 FAIL=0 INCONCLUSIVE=2 SKIP=20 TOTAL=42` |
| Server/load placement | server cores 0–7; every load process cores 8–15 |
| Dataset/load contract | exactly 2,000,000 keys; `-d 32 -t 8 -c 25`; `--distinct-client-seed` |
| Log result | 0 fatal markers across 630 retained logs/captures |

`PASS` means the case executed, its engagement prerequisites were met, and all
oracles accepted. `FAIL` means a value, topology, timeout, execution-evidence,
performance, memory, surface, or log oracle rejected. `INCONCLUSIVE` means the
functional work executed but a required controller/migration/handoff could not
engage; it is never counted as a pass. `SKIP` is allowed only in QUICK and is a
failure of full coverage in full mode.

## Executable acceptance specification

The standing gate is `tools/preflight/bigstress.sh <server>`. Its header states
the reachable red result for every case. These are the release properties and
their acceptance oracles:

| Property/case family | Acceptance oracle; an out-of-spec result |
|---|---|
| Harness discrimination | Positive controls accept valid positive totals/equal digests/stable memory. Negative controls must reject empty, malformed, or numeric-zero totals, changed digests, malformed role/migration evidence, and rising/diverging memory. Acceptance of an injected defect is out of spec. |
| Storage-engine equivalence | DICT (one EX worker per node) and FLAT (two or more) must complete the same exact-value workload and emit the same canonical digest. Missing execution or a digest difference fails. |
| Thread-mode equivalence | Static and auto must emit the same exact-value digest. Auto additionally requires both a completed grow-front/grow-back log record and changed, complete `DEBUG TOMO-IOLOAD` per-slot roles. Exact results with no conversion are `INCONCLUSIVE ENGAGED=NO`. |
| Concurrent data fidelity | Exact single-key SET/GET and multi-key MSET/MGET cover 32 B, 4 KiB, and 64 KiB values while eight clients read/mutate. A SCAN-bearing mix must exhaust its expected keys. Any wrong/missing byte, incomplete SCAN, wrong engine/topology, zero work, or timeout fails. |
| Ownership-move fidelity | While exact readers remain live, bind one normalized key-balancer decision to its later matching FLIP and DONE, require a moved range overlapping proven traffic, then verify every selected canary’s value and source→destination route. An abort, incomplete coverage, wrong byte, or unpaired record fails. No move is inconclusive. |
| Connection lifecycle | Churn connections while 48 captured sockets survive. Every survivor must retain its client ID and exact replies; churn must do positive work. An engaged row also requires a same-socket IO-owner change. A disconnect, ID/value change, zero churn, or false handoff fails; no possible handoff is inconclusive. |
| Steady-state memory | After warmup, late minus early floor must be ≤ max(1%, 8 MiB) for `used_memory`, ≤ max(2%, 16 MiB) for RSS, and ≤ max(2% of starting RSS, 16 MiB) for RSS-minus-used divergence. Slopes must be ≤ 1 MiB/min used, 2 MiB/min RSS, and 2 MiB/min divergence. Every paired sample interval must be ≤10 s. QUICK records but does not qualify this property. |
| Clean log | Every owned server log must exist and be nonempty. Assertions, panic/fatal text, sanitizer/runtime errors, Redis bug reports, crash signals, and core-dump markers must total exactly zero across all retained logs and stderr captures. |
| Existing correctness suite | `correctness_suite.sh` must materialize exactly 17 PASS rows, no FAIL rows, an exact 2M-key seed, complete topology evidence, positive overlapping load, and `checked=6000 stale=0`. Any nested timeout or missing evidence fails. |
| Surface gate | Candidate and explicit distinct baseline must have identical CONFIG, COMMAND, INFO-field, and DEBUG surfaces; all five supported shapes and both shipped configs must boot with exact topology and SET/GET. Empty dumps, cardinality truncation, or missing execution fail. |
| Role-controller gate | Both actuation directions must complete and hold an exact per-slot shape during three measurement windows. Auto median must be at least 99% of the same-run static median at that exact shape. Zero work, activity during the settled window, aborts, missing log/DEBUG evidence, or a >1% shortfall fails. |
| Reference cells | At exactly 2M keys, `-d 32 -t 8 -c 25`, DICT `io7/ex1 p1` GET/SET and FLAT `io4/ex4 p32` GET/SET must each be at least 96% of its fixed reference. Empty/non-numeric/zero Totals or timeout fails. |

Every server start, client command, helper, correctness invocation, and
generator has a bounded timeout; timeout is failure. Each run stages a
BASHPID-distinct binary and reaps only captured PIDs/process groups from
EXIT/TERM/INT/HUP traps. No process-name matching is used.

Run it as:

```sh
BOXLOCKED=1 /shared/Projects/.claude/jobs/fd085c8e/tmp/withbox.sh -w 7200 \
  tools/preflight/bigstress.sh ./src/redis-server

QUICK=1 BOXLOCKED=1 \
  /shared/Projects/.claude/jobs/fd085c8e/tmp/withbox.sh -w 7200 \
  tools/preflight/bigstress.sh ./src/redis-server
```

An explicit distinct `SURFACE_BASE` is required to qualify, rather than merely
boot, the differential surface row.

## Full conformance ledger

| Case | Result | Confirming observable |
|---|---|---|
| HARNESS-DISCRIMINATION | PASS | 28/28 positive and negative controls |
| SURFACE-HARNESS-DISCRIMINATION | PASS | additions, removals, empty dumps, duplicate/wrong roles rejected |
| ROLE-HARNESS-DISCRIMINATION | PASS | 25/25 positive and negative controls |
| SURFACE-GATE | PASS | 14/14 differential surface/config/topology cases |
| ROLE-CONTROLLER-GATE | PASS | 7/7; both directions engaged, exact static comparison, clean logs |
| FIDELITY-DICT-STATIC | PASS | exact digest `b4bf168c…f955`, all sizes and single/multi/SCAN |
| FIDELITY-DICT-TWONODE-STATIC | PASS | same digest; composite cursor exhausted both private owners |
| FIDELITY-FLAT-STATIC | PASS | same digest, all exact cases |
| FIDELITY-DICT-AUTO | INCONCLUSIVE | exact data PASS; true DICT shape stayed 1/1, 0 flips |
| FIDELITY-FLAT-AUTO | PASS | same digest; roles 4/4→5/3→7/1 during exact traffic |
| STORAGE-ENGINE-EQUIVALENCE-STATIC | PASS | DICT and FLAT digest equal |
| DICT-MULTINODE-EQUIVALENCE | PASS | one-node and two-node DICT composite-SCAN digest equal |
| STORAGE-ENGINE-EQUIVALENCE-AUTO | INCONCLUSIVE | exact digests equal; DICT controller prerequisite cannot engage |
| THREAD-MODE-EQUIVALENCE-DICT | INCONCLUSIVE | exact digests equal; DICT auto cannot convert |
| THREAD-MODE-EQUIVALENCE-FLAT | PASS | static and auto digest equal; auto engaged |
| CORRECTNESS-DICT-STATIC | PASS | 17 passed, 0 failed |
| CORRECTNESS-FLAT-STATIC | PASS | 17 passed, 0 failed |
| CORRECTNESS-DICT-AUTO | INCONCLUSIVE | exact correctness 17/17; roles 1/1→1/1, 0 flips |
| CORRECTNESS-FLAT-AUTO | PASS | 17/17; roles 4/4→5/3, 5 completed flips |
| OWNERSHIP-MOVE-DICT-STATIC | INCONCLUSIVE | exact 16,384-canary coverage and 39,530,752 reads; one owner, no range move |
| OWNERSHIP-MOVE-FLAT-STATIC | PASS | move `[3405,4096)` 0→1; 691/691 traffic buckets; 1,085,440 exact reads |
| OWNERSHIP-MOVE-DICT-AUTO | INCONCLUSIVE | exact 16,384-canary coverage and 58,470,912 reads; no move/conversion |
| OWNERSHIP-MOVE-FLAT-AUTO | PASS | move `[3401,4096)` 0→1; 695/695 traffic buckets; 16,068,608 exact reads; roles 4/4→7/1 |
| OWNERSHIP-MOVE-STORAGE-ENGINE-EQUIVALENCE-STATIC | INCONCLUSIVE | digest equal; moves 0/1 |
| OWNERSHIP-MOVE-STORAGE-ENGINE-EQUIVALENCE-AUTO | INCONCLUSIVE | digest equal; moves 0/1 |
| OWNERSHIP-MOVE-THREAD-MODE-EQUIVALENCE-DICT | INCONCLUSIVE | digest equal; moves 0/0 |
| OWNERSHIP-MOVE-THREAD-MODE-EQUIVALENCE-FLAT | PASS | static/auto digest equal; move and auto controller engaged in both prerequisites |
| CONNECTION-LIFECYCLE-DICT-STATIC | PASS | 48 survivors, 8 same-socket owner moves, 13,213 churn ops, 0 disconnects |
| CONNECTION-LIFECYCLE-FLAT-STATIC | PASS | 48 survivors, 22 owner moves, 13,041 churn ops, 0 disconnects |
| CONNECTION-LIFECYCLE-STORAGE-EQUIVALENCE-STATIC | PASS | exact survivor digests equal |
| CONNECTION-LIFECYCLE-DICT-AUTO | INCONCLUSIVE | all 48 exact/stable, 13,273 churn ops, 0 disconnects; one IO owner |
| CONNECTION-LIFECYCLE-FLAT-AUTO | PASS | 48 survivors, 22 owner moves, 10,465 churn ops, 4 controller completions, 0 disconnects |
| CONNECTION-LIFECYCLE-STORAGE-EQUIVALENCE-AUTO | INCONCLUSIVE | exact digest equal; DICT handoff/controller prerequisite unavailable |
| CONNECTION-LIFECYCLE-THREAD-EQUIVALENCE-DICT | INCONCLUSIVE | exact digest equal; DICT handoff/controller prerequisite unavailable |
| CONNECTION-LIFECYCLE-THREAD-EQUIVALENCE-FLAT | PASS | static/auto exact survivor digest equal; both engaged |
| STEADY-STATE-MEMORY | PASS | 151 samples; every floor, slope, divergence, and cadence check true |
| REFERENCE-DICT-GET | PASS | 839,903.38 vs 826,877 (+1.58%) |
| REFERENCE-DICT-SET | PASS | 828,362.41 vs 817,393 (+1.34%) |
| REFERENCE-FLAT-GET | PASS | 8,165,340.67 vs 7,943,860 (+2.79%) |
| REFERENCE-FLAT-SET | PASS | 6,958,889.42 vs 6,852,385 (+1.55%) |
| CLEAN-LOG | PASS | 0 markers across 630 logs/captures |

The three exact canonical digests are:

- functional fidelity: `b4bf168cf72b4e38bcedfe9525c720b51a3fc8de3e15c29e03b2b3e0d6b7f955`
- ownership fidelity: `565db14348e97054b5ff5568188f70e9f055c41b6b1a763d91f1be77a02f8cee`
- connection survivors: `1cb4ebdeb292cbdf783d641352cc2ebe3369c4b3c620781f04301fc6803d9320`

## Controller and key-balancer engagement

The final embedded controller gate reproduced each settled auto shape as a
fresh static shape and compared medians from three windows:

| History | Completed evidence | Auto median | Exact static median | Delta | Result |
|---|---:|---:|---:|---:|---|
| grow-front from 4/4 to 6/2 | 3 grow-front completions plus exact DEBUG roles | 837,869.01 | 841,091.08 | -0.38% | PASS |
| grow-back after front, 6/2 to 4/4 | 4 grow-back completions plus exact DEBUG roles | 6,912,199.44 | 6,904,315.67 | +0.11% | PASS |
| grow-back from 7/1 to 4/4 | 5 grow-back completions plus exact DEBUG roles | 6,903,992.32 | 6,904,315.67 | -0.00% | PASS |
| grow-front after back, 4/4 to 6/2 | 3 grow-front completions plus exact DEBUG roles | 840,372.61 | 841,091.08 | -0.09% | PASS |

There were no completions, starts, aborts, or outstanding controller actions
during any settled measurement window, and the controller sub-gate found zero
fatal markers in four server plus four launch logs.

The FLAT static key balancer emitted a normalized AUTO decision at log line 54,
matching FLIP at 57 and DONE at 58 for `[3405,4096)` 0→1. All 691 selected
buckets were read exactly while the move was live and reverified afterward.
FLAT auto emitted its normalized decision at line 63, matching FLIP at 66 and
DONE at 67 for `[3401,4096)` 0→1; all 695 selected buckets were covered,
16,068,608 exact reads completed, and the role controller changed 4/4→7/1.
Both cases had zero aborts and the same ownership digest.

## Steady-state memory result

Samples were paired every 8.01–8.03 seconds during a 1,202-second loaded
window after warmup.

| Observable | Start | Peak | End | Early floor | Late floor | Linear slope |
|---|---:|---:|---:|---:|---:|---:|
| RSS bytes | 233,955,328 | 234,299,392 | 234,053,632 | 233,988,096 | 233,961,472 | -4,661 B/min |
| `used_memory` bytes | 280,273,440 | 280,487,224 | 280,295,944 | 279,924,304 | 279,956,452 | +4,293 B/min |
| RSS minus used bytes | — | — | — | -46,289,948 | -46,371,692 | -8,954 B/min |

The maximum paired interval was 8.026817 seconds. Every floor, slope, and
divergence predicate passed by orders of magnitude. The complete series is
included below so the report does not substitute a summary for the evidence:

```text
elapsed_s	rss_bytes	used_memory_bytes
0.002730	233955328	280273440
8.018821	233971712	280232336
16.040774	234012672	280124416
24.057748	234037248	279954656
32.072062	234119168	280091120
40.087031	234102784	280337704
48.100802	234078208	279996520
56.117807	234299392	279955048
64.134171	234188800	280129464
72.149354	234196992	280062952
80.163162	233979904	279843736
88.178580	234127360	279934800
96.193453	234131456	280309896
104.208189	234201088	280196904
112.222934	234123264	279956544
120.237414	234246144	280123056
128.250224	234201088	280150368
136.265291	234205184	280039256
144.280051	234184704	279971944
152.293870	234188800	280121472
160.306817	234127360	279902176
168.322708	234074112	279959752
176.344554	233992192	280200928
184.359798	234016768	280424408
192.376428	234020864	280437904
200.391129	234037248	280299032
208.410043	234045440	280182520
216.426890	234045440	279955064
224.443341	234139648	280041704
232.457315	234119168	279913808
240.471552	233988096	280308632
248.484638	233988096	279886352
256.500521	234094592	280256688
264.515106	234102784	280065808
272.532929	234078208	280219984
280.549419	234061824	280258576
288.565136	234029056	280025032
296.579680	234115072	279954456
304.598394	234135552	280096184
312.614795	234168320	280329376
320.628404	234123264	280017288
328.643139	234082304	280346160
336.657459	234065920	280316520
344.670409	234029056	280086544
352.685511	234057728	279824624
360.701138	234029056	280092544
368.720583	234041344	280028944
376.734293	234041344	280341248
384.749058	234053632	280309624
392.763111	234160128	279874112
400.778803	234143744	279839408
408.794997	234164224	280070616
416.810071	234123264	280030544
424.825365	234098688	280258928
432.841350	234020864	279828744
440.857905	233996288	280360512
448.871209	234037248	279992120
456.887156	234082304	280027000
464.903488	234119168	280246624
472.919504	234033152	280171824
480.937244	234078208	280222552
488.951868	234176512	280188768
496.966042	234176512	280112352
504.979318	234098688	280267224
512.994006	234061824	279893312
521.008023	234033152	280077512
529.034755	234053632	280328912
537.047617	234110976	280427104
545.064805	234172416	280182328
553.078553	234061824	279861912
561.094199	234029056	280228488
569.109769	234020864	280206080
577.131749	234115072	280298216
585.147182	233984000	280209768
593.162312	234074112	279913456
601.175538	234123264	280160040
609.190547	234119168	280272208
617.206020	234156032	279980704
625.222819	234065920	280378168
633.239822	234090496	280245120
641.254886	234131456	280141040
649.272347	234070016	279991520
657.285743	234094592	280173536
665.301551	234065920	280291640
673.316150	234078208	280150752
681.331712	234020864	280381408
689.346080	234024960	280369728
697.360565	234008576	280120856
705.379732	233979904	280111000
713.396496	233943040	280010224
721.413254	234065920	280112440
729.427842	233984000	280280832
737.440884	234004480	280376304
745.455802	233930752	280312408
753.472526	233967616	280269688
761.489705	233922560	280400816
769.504941	233943040	280468632
777.531758	233951232	280053552
785.549610	233959424	279945512
793.566239	234123264	280008576
801.583462	234070016	279968544
809.598073	234004480	280017960
817.613352	234086400	280105536
825.629438	234196992	279846344
833.645724	234147840	280122336
841.659350	234074112	280232248
849.674677	234070016	280191528
857.690189	234020864	279923280
865.708431	234000384	280233024
873.722882	234037248	280466352
881.736535	234041344	280239000
889.749978	234045440	280057944
897.766419	234045440	280188360
905.780919	234061824	280426096
913.797792	233996288	280236384
921.811341	234020864	280487224
929.827697	234045440	280026064
937.845479	234012672	279951976
945.861206	234184704	279920464
953.877076	234156032	279960928
961.893114	234098688	280185024
969.906976	234180608	280206864
977.920642	234102784	280395752
985.934469	234029056	280365528
993.951058	233988096	279963976
1001.967368	233967616	280269168
1009.984638	234024960	279973936
1018.005645	233988096	280257048
1026.019336	234020864	279988600
1034.037113	234086400	280210000
1042.051181	234094592	280018392
1050.065713	233975808	279863240
1058.079109	234053632	280044080
1066.092015	234024960	280127920
1074.108342	233979904	279972016
1082.126466	233963520	280424640
1090.143994	233906176	280318384
1098.160804	233914368	280248816
1106.175252	234016768	280423680
1114.194223	234057728	280142008
1122.209064	233992192	279909160
1130.225554	233959424	280171512
1138.239884	234196992	280196768
1146.256110	234172416	280294992
1154.273757	234057728	280343552
1162.288664	233947136	280101816
1170.304058	234004480	280282760
1178.317422	233979904	280293408
1186.333453	234008576	280018696
1194.346237	233979904	280151256
1202.359647	234053632	280295944
```

## Corrections and confirming observables

The initial full run at `267ba497a` was deliberately allowed to fail:

```text
SUMMARY PASS=28 FAIL=1 INCONCLUSIVE=12 SKIP=0 TOTAL=41
```

Minimal reproduction: build `267ba497a`, then run
`tools/preflight/flipcmp.sh` under the box wrapper. Both grow-back histories
settled at exact 4/4 but were below the unchanged 99% floor:

| Pre-fix row | Auto | Same-run static | Delta |
|---|---:|---:|---:|
| grow-back after grow-front | 6,950,855.55 | 7,039,568.18 | -1.26% |
| grow-back from 7/1 | 6,941,683.39 | 7,039,568.18 | -1.39% |

At `src/server.c`, a converted EX→IO thread performed `ioSlice()` and then the
full EX idle PAUSE/periodic `sched_yield()` policy on every loop, even though
its EX binding owned no buckets. Commit `e511d6c3a` added explicit EX idle
policies. Converted IO threads still execute the complete freeback, QSBR,
reclaim, resize, expiry, queue, execution, frontier, and reply-signal safety
scan, but return directly to IO when that scan is empty and clear the non-live
qdepth signal. Transition drains and live workers retain normal backoff.

The focused rerun passed all four reference cells and all four directional
comparisons; the authoritative full rerun independently confirmed +0.11% and
-0.00% for the formerly red rows. Those deltas, exact roles, directional log
records, and zero fatal markers distinguish the conforming build from the
pre-fix build without weakening the 1% property.

All separately committed corrections made while constructing the standing
gate are recorded here:

| Commit | Class | Minimal reproduction and source/case explanation | Correction | Distinguishing observable |
|---|---|---|---|---|
| `5dd7469b7` | Product correctness | In DICT `io7/ex1`, seed SCAN-matching keys: GET/DBSIZE found them but top-level SCAN walked the coordinator’s intentionally empty `server.db`; multiple private worker dictionaries also lacked an owner-aware cursor. | Route DICT SCAN to owners and encode worker plus kvstore cursor in the opaque cursor. | One-node DICT, two-node DICT, and FLAT exhaust the same canaries and digest. |
| `d2364c0b6` | Harness | No owned reusable differential gate existed, so CONFIG/COMMAND/INFO/DEBUG drift had no standing red row. | Adopt `surface_diff.sh` with bounded unique staging, five shapes, shipped configs, nonempty dumps, and mutation tests. | Self-test rejects additions/removals/empty dumps; live gate passes 14/14 only on exact identity. |
| `314e62b25` | Harness | No gate distinguished real bidirectional conversion from zero work or non-engagement. | Adopt `flipcmp.sh` with exact seed, positive Totals, direction/log/DEBUG evidence, stable-shape static medians, and clean logs. | 25/25 discrimination controls and 7/7 final live cases. |
| `c5635379d` | Product observability | Static `io7/ex1` DEBUG output exposed six dynamic slots because fixed main IO and worker zero had no `polyThreadCtx`. | Publish those two fixed roles explicitly. | Exact eight unique roles and 7/1 totals are visible. |
| `73a131bc3` | Harness case | Self-comparison rejected `COMMAND LIST=412` vs `COUNT=275`; COUNT is top-level while LIST includes subcommands. | Require LIST ≥ COUNT while still differentially comparing both complete outputs. | 275/412 is accepted only when both arms match; truncation/drift remains red. |
| `d67a121aa` | Shipped config | `redis-full.conf` tried four LOADMODULE directives although TomoKV intentionally rejects modules under its ownership model. | Comment unsupported directives and document the limitation. | Both shipped configs boot and pass exact SET/GET. |
| `f15081400` | Harness | Correctness reused one stage name, lost launch output, and accepted too few zero spellings. | BASHPID-distinct staging, retained launch output, numeric value strictly greater than zero. | Empty, malformed, and every numeric-zero Totals form are invalid. |
| `c2779450c` | Harness | Fixed sleeps could hit a foreign listener; topology/2M/order/overlap were not proven and missing work could SKIP. | PID readiness, CONFIG and unique roles, exact seed/DBSIZE, canonical pinned load, strict row/cardinality/order evidence, FAIL semantics. | Every functional arm materializes exactly 17 PASS rows and `checked=6000 stale=0`. |
| `d79e38193` | Harness case | Surface boots accepted any answering shape and mislabeled requested auto 7/1 as DICT, though its effective 1/7 pool is FLAT. | Verify immutable effective config and all roles; use true DICT auto 1/1. | Five boot rows prove requested/effective/live topology exactly. |
| `2ddb07070` | Harness case | The comparator forced pool edges, sampled transients, incompletely counted activity, and treated improvement over static as failure. | Settle under load, recreate the observed exact shape, compare three-window medians with a one-sided 99% floor, reject all in-window activity. | Interior 6/2 convergence is valid and all final directional deltas pass. |
| `7384feba8` | Product safety | IO-born auto threads could call dormant `exSlice` before `exSliceCtx` initialization. | Gate the dormant drain on `ex_inited`; retain it after first EX service. | Repeated conversions preserve exact data with zero crash/assert markers. |
| `263aefec0` | Harness | No single executable acceptance matrix existed. | Add `bigstress.sh` and strict RESP client for fidelity, equivalence, correctness, moves, lifecycle, memory, logs, references, and adopted gates. | 28/28 harness controls; QUICK under five minutes; full 63.89 minutes. |
| `3f25c0149` | Harness | A timed-out asynchronous DEBUG role probe could be hidden by a later successful nested correctness exit. | Latch and propagate the timeout reason. | A 124/137 role probe now fails the enclosing row. |
| `982ead4cc` | Harness | Initial move testing covered only FLAT static and loose counts allowed unrelated controller/RELEVEL records to impersonate a key move. | Run DICT/FLAT × static/auto; bind normalized decision→matching FLIP→DONE; use exact reader selection/stop handshakes, route proofs, full bucket coverage, and cross-arm digests. | Full FLAT static/auto moves prove 691/695 traffic buckets and exact post-move data; DICT is honestly inconclusive. |
| `267ba497a` | Harness | Missing utilities could fail only after a long run began. | Validate every external dependency before staging. | Missing `mv`, `find`, `wc`, etc. produces immediate infrastructure FAIL. |
| `e511d6c3a` | Product performance | Former EX threads serving IO retained worker idle PAUSE/yield overhead; two exact 4/4 comparisons were -1.26%/-1.39%. | Preserve complete dormant drain but use immediate-return idle policy and clear stale non-live qdepth. | Formerly red rows are +0.11%/-0.00%; focused references and full matrix pass. |

## Reference-cell cost guard

The rejection floors are 793,802 DICT GET, 784,697 DICT SET, 7,626,106 FLAT
GET, and 6,578,290 FLAT SET. Every source-affecting correction and each later
gate checkpoint remained above all four floors:

| Checkpoint | DICT GET | DICT SET | FLAT GET | FLAT SET |
|---|---:|---:|---:|---:|
| `5dd7469b7` | 838,439 | 822,813 | 8,131,211 | 6,961,987 |
| `c5635379d` | 838,913 | 828,303 | 8,148,693 | 6,951,029 |
| `d67a121aa` | 841,056 | 828,978 | 8,170,179 | 6,944,359 |
| `c2779450c` | 843,099.62 | 828,576.41 | 8,151,077.80 | 6,945,181.86 |
| `d79e38193` | 839,740.91 | 824,436.64 | 8,172,097.15 | 7,001,014.89 |
| `2ddb07070` | 841,313.26 | 828,311.51 | 8,163,412.86 | 6,951,842.89 |
| `7384feba8` | 842,299.29 | 831,864.65 | 8,155,310.81 | 6,968,231.71 |
| `263aefec0` | 842,961.09 | 826,656.95 | 8,136,568.29 | 7,008,304.92 |
| `3f25c0149` | 842,500.93 | 827,790.77 | 8,105,615.24 | 6,998,535.30 |
| `982ead4cc` | 840,774.24 | 826,794.91 | 8,158,249.45 | 6,958,561.78 |
| `267ba497a` | 838,075.41 | 827,193.87 | 8,125,568.35 | 6,993,075.00 |
| `e511d6c3a` focused | 839,687.30 | 826,471.87 | 8,116,691.16 | 6,916,992.64 |
| `e511d6c3a` final full | 839,903.38 | 828,362.41 | 8,165,340.67 | 6,958,889.42 |

Harness-only commits do not alter the server execution path and inherit the
surrounding server checkpoint; they were still committed separately. No
correction approached the 4% rejection floor, so none was withheld for cost.

## Properties not qualified

These are the 12 explicit `INCONCLUSIVE ENGAGED=NO` rows and the reason each
cannot be promoted to PASS:

1. `FIDELITY-DICT-AUTO`, `CORRECTNESS-DICT-AUTO`,
   `STORAGE-ENGINE-EQUIVALENCE-AUTO`, and
   `THREAD-MODE-EQUIVALENCE-DICT`: true DICT auto is necessarily 1 IO / 1 EX.
   There is no convertible slot. Requested live auto 7/1 is provisioned as
   effective 1/7 and therefore uses FLAT. All exact functional results match,
   but DICT controller behavior is unqualified.

2. `OWNERSHIP-MOVE-DICT-STATIC`, `OWNERSHIP-MOVE-DICT-AUTO`,
   both `OWNERSHIP-MOVE-STORAGE-ENGINE-EQUIVALENCE-*` rows, and
   `OWNERSHIP-MOVE-THREAD-MODE-EQUIVALENCE-DICT`: DICT has one EX owner per
   node and cannot perform the shared-FLAT bucket-range move. Before/during/
   after exact values and digests match; move engagement does not.

3. `CONNECTION-LIFECYCLE-DICT-AUTO`,
   `CONNECTION-LIFECYCLE-STORAGE-EQUIVALENCE-AUTO`, and
   `CONNECTION-LIFECYCLE-THREAD-EQUIVALENCE-DICT`: DICT auto 1/1 has one IO
   socket owner, so a same-socket IO-thread handoff and controller conversion
   cannot occur. All 48 survivors retained IDs and exact values with zero
   disconnects.

One comparator boundary remains documented for future runs: if auto settles at
live 7/1, its effective storage is FLAT while static 7/1 is DICT, so that rate
is a cross-engine release observable rather than a controller-only overhead
measurement. The final corrected confirmation settled at 6/2 and 4/4, where
both compared arms are FLAT, so this run’s controller performance result has
no such ambiguity.
