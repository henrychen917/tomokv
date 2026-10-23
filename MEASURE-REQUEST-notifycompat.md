## notifycompat

Work in progress on `cx-notifycompat`, PRE `ef5204b2e`. No push or performance claim.
All lane builds/correctness processes use CPUs 48–63; servers use ports 32800–32899.

CD4.8: Redis 7.4.10 emits no frames for unchanged raw or integer SETBIT, and emits
`setbit` for a changed bit, growth with zero, and a new zero bit. Oracle wire evidence:
`docs/notifycompat/oracle-setbit.log`. PRE failed the new gate row in all 12 declared
mode/engine/atomic/read-local legs. The first POST attempt exposed the missing
`t_string_notify.o: t_string.cc` dependency; its stale-object failures are retained.
The dependency is repaired and a fresh POST build is in progress. GET/SET/MGET/MSET
initial diagnostic: 65/65 bodies identical (`identity-setbit.json`). Final proof pending.

Current row delta: DQ=+1, DF=+1, at `collect_job notifycompat` before the quick exit.
The explicit label fixture matches the source (757 labels); protected EXPECT values
are unchanged. Maintainer required counts at this step: 740 quick / 757 full.
