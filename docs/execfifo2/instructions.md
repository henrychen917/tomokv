# Serverless instruction scopes

Production images: PRE `735cbffb1afa279a4b47ddd42411cbc5d4e25a38653c01150ee15edc5fd6ebca`,
POST `ee5aee2768e0e8f8899a90f628a45f8a2ec47cebe3e405dbf9cf21210e9d0b0a`.
All probes preserve production object/COMDAT order, append the fixture last,
and call linked production functions. Every build receipt binds the probe SHA
and production SHA. GDB single-steps functions whose demangled names contain the selected Tomo
namespace, including standard-library specializations naming Tomo types. Other
library callees and fixture glue are excluded and inventoried; clocks are deterministic.
These are instruction counts, not cycles, throughput or latency measurements.
Full step logs are deleted after their SHA-256, count and completion tail are saved.

## Ordinary commands

**48/48 cells are exactly PRE = POST.** Each batch count covers the complete
fixture batch, not one operation. MGET/MSET use the fixture's cross-shard keys.
The MSET atomic 0 and 1 paths are both included.

| Namespace | Mode | Command | Atomic | PRE batch 1 | POST batch 1 | PRE batch 32 | POST batch 32 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| normal | 1s | GET | 1 | 936 | 936 | 18482 | 18482 |
| normal | 1s | SET | 1 | 1060 | 1060 | 22450 | 22450 |
| normal | 1s | INCR | 1 | 1511 | 1511 | 37411 | 37411 |
| normal | 1s | MGET | 1 | 10177 | 10177 | 324486 | 324486 |
| normal | 1s | MSET | 0 | 10779 | 10779 | 344773 | 344773 |
| normal | 1s | MSET | 1 | 16956 | 16956 | 960806 | 960806 |
| normal | 2s | GET | 1 | 1556 | 1556 | 18327 | 18327 |
| normal | 2s | SET | 1 | 1680 | 1680 | 22295 | 22295 |
| normal | 2s | INCR | 1 | 2131 | 2131 | 37256 | 37256 |
| normal | 2s | MGET | 1 | 10177 | 10177 | 324486 | 324486 |
| normal | 2s | MSET | 0 | 10597 | 10597 | 338949 | 338949 |
| normal | 2s | MSET | 1 | 16624 | 16624 | 950182 | 950182 |
| db0 | 1s | GET | 1 | 818 | 818 | 18705 | 18705 |
| db0 | 1s | SET | 1 | 926 | 926 | 22161 | 22161 |
| db0 | 1s | INCR | 1 | 1308 | 1308 | 34914 | 34914 |
| db0 | 1s | MGET | 1 | 10325 | 10325 | 329222 | 329222 |
| db0 | 1s | MSET | 0 | 11018 | 11018 | 352421 | 352421 |
| db0 | 1s | MSET | 1 | 16415 | 16415 | 951926 | 951926 |
| db0 | 2s | GET | 1 | 1051 | 1051 | 18163 | 18163 |
| db0 | 2s | SET | 1 | 1159 | 1159 | 21619 | 21619 |
| db0 | 2s | INCR | 1 | 1541 | 1541 | 34372 | 34372 |
| db0 | 2s | MGET | 1 | 10325 | 10325 | 329222 | 329222 |
| db0 | 2s | MSET | 0 | 10828 | 10828 | 346341 | 346341 |
| db0 | 2s | MSET | 1 | 16075 | 16075 | 941046 | 941046 |

The first release link had inlining spillover in cross-shard bodies. GCC's
initial IPA unit sizes increased from 124880 to 126590 (normal xshard) and
123867 to 125626 (db0 xshard). Adding those exact deltas to the existing
large-unit budgets gives 155438 and 154303, preserving the PRE absolute
inlining allowance. The bounded compile-only trial restored all 24 MGET/MSET
cells; the final production-linked run confirms all 48 cells. The C1 port's
db0 main budget is 147690 (PRE 146080); other headline template-unit budgets
are retained. No speculative survey budget was adopted for those units.
Initial counts and the trial remain in `commands-before-budgets/` and
`commands-budget/`; compiler surveys and trial scores are in `budgets-POST/`.

## Uncontended EXEC

The completed counts and function-by-function attribution cover two scopes:
`exec/` uses the existing INCR fixture from MULTI queueing through execution,
retirement and reaping; it calls the executor routine directly without an owner
promoter, so its cross-shard one-child case degenerates to one shard.
`owner/` prepares one EXEC outside the scope, then calls the linked owner batch
and retry-service entrypoints. Its two-key MSET children genuinely span one or
two owners even with one child. It includes C1 boundary/drain work and validates
exact replies and final values, with retirement outside the measured scope.
Both cover 1/2/4 children, both modes/namespaces and atomic 0/1.

### Dispatch through retirement: INCR children

Atomic 0 and 1 produce identical counts in every paired cell below. Each triple
is for **1 / 2 / 4 children**; counts are per complete fixture EXEC.

| Namespace | Mode | Placement | PRE | POST | Delta |
| --- | --- | --- | --- | --- | --- |
| normal | 1s | single shard | 12102 / 16447 / 25097 | 12198 / 16568 / 25268 | 96 / 121 / 171 |
| normal | 1s | cross | 12102 / 21370 / 39759 | 12198 / 21544 / 40060 | 96 / 174 / 301 |
| normal | 2s | single shard | 12057 / 16387 / 25007 | 12153 / 16508 / 25178 | 96 / 121 / 171 |
| normal | 2s | cross | 12057 / 21220 / 39261 | 12153 / 21394 / 39562 | 96 / 174 / 301 |
| db0 | 1s | single shard | 10904 / 14971 / 23058 | 10972 / 15057 / 23180 | 68 / 86 / 122 |
| db0 | 1s | cross | 10904 / 19674 / 37054 | 10972 / 19809 / 37296 | 68 / 135 / 242 |
| db0 | 2s | single shard | 10859 / 14911 / 22968 | 10927 / 14997 / 23090 | 68 / 86 / 122 |
| db0 | 2s | cross | 10859 / 19524 / 36556 | 10927 / 19659 / 36798 | 68 / 135 / 242 |

### Production owner turn: two-key MSET children

Atomic 0 and 1 produce identical counts in every paired cell below. Each triple
is for **1 / 2 / 4 children**; counts are per complete fixture EXEC.

| Namespace | Mode | Placement | PRE | POST | Delta |
| --- | --- | --- | --- | --- | --- |
| normal | 1s | single shard | 10047 / 15484 / 26358 | 10320 / 15805 / 26775 | 273 / 321 / 417 |
| normal | 1s | cross | 13744 / 19883 / 32161 | 14740 / 21094 / 33802 | 996 / 1211 / 1641 |
| normal | 2s | single shard | 10626 / 16048 / 26892 | 10941 / 16411 / 27351 | 315 / 363 / 459 |
| normal | 2s | cross | 14767 / 20838 / 32980 | 15868 / 22180 / 34804 | 1101 / 1342 / 1824 |
| db0 | 1s | single shard | 9637 / 14844 / 25258 | 9882 / 15112 / 25572 | 245 / 268 / 314 |
| db0 | 1s | cross | 12806 / 18623 / 30257 | 13786 / 19805 / 31843 | 980 / 1182 / 1586 |
| db0 | 2s | single shard | 9898 / 15090 / 25474 | 10185 / 15400 / 25830 | 287 / 310 / 356 |
| db0 | 2s | cross | 13184 / 18933 / 30431 | 14268 / 20245 / 32199 | 1084 / 1312 / 1768 |

### Attribution and limits

`attribution.json` accounts for **every changed function in all 96 EXEC
comparisons**, with category totals that must sum exactly to each observed
PRE/POST delta. `exec/comparison.json` and `owner/comparison.json` retain the
unclassified per-function differences as well. There is no unaccounted residual.

- C1 adds participant-node initialization, event promotion, owner dispatch
  callbacks, ready-queue service, and H3 boundary checks. The owner scope
  exposes the cost omitted by the direct routine scope: **+245 to +1824**
  instructions per EXEC here, versus **+68 to +301** in the direct scope.
- B adds the plain-writer hand-off check to completion and enlarges embedded
  waiter links. The ordinary non-FIFO readiness body is renamed to a template
  specialization and costs two fewer instructions per call in these traces;
  its old and new symbol counts must be combined.
- Claim/key construction shifts code between `txn_add_claim` and
  `database_owned_key`; the paired totals record the actual change. The
  enlarged retry node also changes destruction code by one instruction.
- Normal-namespace `FlatStore::snapshot_prepare_write` and `atomic_collapse`
  show residual compiler/COMDAT changes despite unchanged source. They are
  reported explicitly, not attributed to FIFO semantics or hidden inside the
  zero-cost ordinary-command claim. Disassembly in `builds/*-snapshot_prepare_write.asm`
  confirms the new normal snapshot helper has a stack-protector prologue/epilogue
  (+6 instructions per observed fast-path call) after its changed outlining.
  `store-codegen.json` records the emitted body sizes and hashes for both arms.

For example, the normal 2s cross-owner four-child MSET EXEC adds 1824:
H3 boundary 735, runnable drain 420, retry queue 140, local event promotion 294,
owner dispatch 110, EXEC state machine 51, FIFO completion 58, readiness -32,
and unchanged-store codegen 48. This deterministic fixture visits owners in a
fixed sequence; it is an instruction accounting schedule, not a timing model
of concurrent owners. C1's contended/depth merit and the generic null still
require the maintainer's matched-load measurements.
