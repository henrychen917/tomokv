## gaterows5

Base: `3700b51d7`, branch `cx-gaterows5`. Correctness only; no push, performance workload,
or full iteration. Builds use CPUs 16–31, `-j16`; selected gate jobs use server CPUs
16–23, client CPUs 24–31, ports 44800–44899. Production sources and EXPECT constants
are maintainer-owned and unchanged. Work in progress; final evidence follows below.

Read the round-4 register T5 rows and cited scope findings, including HX-LB-PROBE's
2026-10-22 addendum. TM4.1–4, EX4.19, RO4.1, ST4.13, WB4.7/14 and HX-LB-PROBE
still need work. NT4.17, CD4.19 and SV4.15 have later standing rows; the final report
will identify remaining subcases and existing coverage explicitly.

### Audit of later coverage

| Finding | Current standing coverage / remaining work |
| --- | --- |
| NT4.17 | `respcompat` now has pre-AUTH limits/precedence and authenticated controls; `respresume-*` has bounded incremental parsing; `fliplisten` covers arrivals and established TLS connections through FLIP. Successful inline quoted decoding remains absent and production explicitly only validates quotes. Add `inline_quoted` and report the production failure. Add the missing non-BMI build/run of the existing ROB fence unit. |
| CD4.19 | `clientfix` geo-count/geo-store; `bugs5` scancompact; `datafix1_geo/spop/lists/locale/bitfield/hexpire/randscan`; `datafix2_notouch/watch/encoding/subkeys`; `hexpread`; `notifycompat` cover the enumerated omissions. No duplicate row added. |
| SV4.15 | `authfix` redaction and binary-password rewrite/restart; `bugs5` slowlog identity; `clientfix` repeated shorter pause; `serverfix_waitaof` wait lifecycle. No duplicate row added. |
| TM4.1 | Restore/assert atomic entry and exit for split/armed shared feature jobs, plus the unarmed fused shared battery loop. Individual scripts that deliberately test both settings still do so. |
| TM4.2/3 | Strict DEBUG refusal is a failed vacuity witness. Same/different owner selection uses DEBUG SHARDS owner IDs, never shard inequality. |
| TM4.4 | Four witness-control suites now run in `witness_contracts`. |
| HX-LB-PROBE | A typed placement change spends one of the existing four attempts before any writes/holds start; next attempt opens a fresh observer and key prefix. Other probe failures propagate. |
| RO4.1 | `reorder_bounds` runs linear/lazy work assertions, quadratic/eager throwaway controls and production parser fixtures in both database images. |
| EX4.19 | `slotless` keeps 1030 clients on one DEBUG-witnessed IO owner with balancers disabled, checks remote-owner replies, and runs exact native claim/channel/drain controls. |
| ST4.13 | Actual vector/heap/ROB placement assertions added. These expose existing production layout defects; no layout fix is included. Slotless coverage is shared with EX4.19. |
| WB4.7/14 | `wb_mixed` boots both policies, both engines/modes and four S/D combinations; it mixes borrowed GET, MULTI, REPLY suppression, DEBUG SLEEP and ordered/blocking SKIP targets. A publication latch tests the incomplete small-pipe rule. |

The initial WB hold attempt used BLPOP, which is a parser barrier and did not create
two simultaneous ROB slots. That harness attempt failed in all four legs and is
retained in the initial logs; it is not evidence of a production defect. The
replacement uses an admitted MSET held by ATOMIC-COMMIT-HOLD.
