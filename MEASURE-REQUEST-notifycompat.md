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

CD4.22: oracle confirms SET EXAT/PXAT past emits `set, expire`, followed by
`expired, keymiss` when a GET triggers lazy expiry with active expiry disabled.
Both existing and absent keys are covered. GETEX past already emits `del` on both
implementations and is retained as a control (NOT REPRODUCED as a GETEX defect).
`tests/notify.py` now expects `expire` for its generic-only event mask. Exact
oracle bytes are in `docs/notifycompat/oracle-setpast.log`. The clean SET
specialization is unchanged; all 65 selected hot bodies remain identical.
Current DQ=+2 / DF=+2; required counts 741 / 758. Full final matrix pending.

CC4.20: oracle confirms source `keymiss` alone when the BITOP/set-algebra
STORE destination is absent; a live destination adds one subsequent `del`.
The owner deletion supplies the plain fire point, and atomic installation records
whether a destination was actually replaced. Local and cross-owner fixtures cover
BITOP, SINTERSTORE, SUNIONSTORE and SDIFFSTORE. Destination mutation ordering was
adjusted to preserve Redis's source-before-destination sequence in these cases.
The initial string POST rerun exposed an overfilled test key-selection bucket on
fused boots; that arming bug was corrected (no skipped leg or relaxed assertion).
Current DQ=+3 / DF=+3; required counts 742 / 759. Final proof pending.

NO-A1: Redis confirms `keymiss` for SET GET, GETSET, GETDEL and GETEX on absent
keys, preceded by `expired` on a lazy-expired key. SET/GETSET then emit `set`.
SET XX GET still reads before rejecting its write. The observer now classifies
these read lookups without adding work to disarmed command handlers.
Oracle bytes: `docs/notifycompat/oracle-writemiss.log`. Current DQ=+4 / DF=+4;
required counts 743 / 760. CC4.20's identity diagnostic reports shared xshard
execution changes and db0 prepare spillover; these remain explicit repair/merit
inputs, not a reason to stop or a performance claim.

NO-A2: all four OBJECT subcommands now use the no-touch lookup, suppress
keymiss, and retain a physical lazy-expiry event. Redis checks missing keys
before the IDLETIME/FREQ policy error, so that precedence is corrected too.
The oracle's exact null/expired frames are retained in `oracle-objectmiss.log`.
Current DQ=+5 / DF=+5; required counts 744 / 761. Final proof pending.

NO-A7: Redis confirms explicit `del` (no `expired`, no expired_keys increment)
for elapsed resident destinations in 11 empty STORE forms. The directed battery
covers local and cross-owner routes, with a physical-residency witness before each
command. Plain application now uses raw owner deletion; atomic application records
its physical old destination. GEO's separate local path is included. Empty zset
stores also retain Redis's source keymiss and source-before-destination ordering.
Oracle bytes: `oracle-expiredstore.log`. Current DQ=+6 / DF=+6; counts 745 / 762.
