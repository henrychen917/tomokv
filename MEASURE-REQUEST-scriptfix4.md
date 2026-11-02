## scriptfix4

Base/PRE: `9d6ab5526f`. Correctness only: CPUs 87-99, ports 21200-21299,
LC_ALL=C. No throughput measurements, load generators, full iteration or push.

Work in progress. Promoted round-5 cap, scripting tracking, blocked XREAD,
shutdown library-cut and scheduled-save witnesses into `tests/scriptfix4.py`.
Each finding has four gate rows (1s/2s x uring/epoll). These 20 rows are
collected immediately after wave14_functions, before the quick-tier exit:
DQ=+20, DF=+20; owner should change 1046/1063 to 1066/1083. EXPECT unchanged.

The partial-job planner rejected the assigned 13-core allocation because its
minimum was 16 even for one 8-server + 2-client correctness slot. Partial jobs
now accept that 10-core minimum. Complete/performance gates retain 16.

PRE witnesses, POST proofs, arm digests and residuals will be recorded here.
