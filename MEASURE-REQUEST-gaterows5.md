## gaterows5

Base: `3700b51d7`, branch `cx-gaterows5`. Correctness only; no push, performance workload,
or full iteration. Builds use CPUs 16–31, `-j16`; selected gate jobs use server CPUs
16–23, client CPUs 24–31, ports 44800–44899. Production sources and EXPECT constants
are maintainer-owned and unchanged. Work in progress; final evidence follows below.

Read the round-4 register T5 rows and cited scope findings, including HX-LB-PROBE's
2026-10-22 addendum. TM4.1–4, EX4.19, RO4.1, ST4.13, WB4.7/14 and HX-LB-PROBE
still need work. NT4.17, CD4.19 and SV4.15 have later standing rows; the final report
will identify remaining subcases and existing coverage explicitly.
