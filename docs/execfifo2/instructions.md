# Serverless instruction scopes

Production images: PRE `735cbffb1afa279a4b47ddd42411cbc5d4e25a38653c01150ee15edc5fd6ebca`,
POST `ee5aee2768e0e8f8899a90f628a45f8a2ec47cebe3e405dbf9cf21210e9d0b0a`.
All probes preserve production object/COMDAT order, append the fixture last,
and call linked production functions. Every build receipt binds the probe SHA
and production SHA. GDB single-steps named Tomo routines; library callees and
fixture glue are excluded and inventoried, and clocks are deterministic.
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

Counts and function-by-function attribution are being completed for two scopes:
`exec/` uses the existing INCR fixture from MULTI queueing through execution,
retirement and reaping; it calls the executor routine directly without an owner
promoter, so its cross-shard one-child case degenerates to one shard.
`owner/` prepares one EXEC outside the scope, then calls the linked owner batch
and retry-service entrypoints. Its two-key MSET children genuinely span one or
two owners even with one child. It includes C1 boundary/drain work and validates
exact replies and final values, with retirement outside the measured scope.
Both cover 1/2/4 children, both modes/namespaces and atomic 0/1.
