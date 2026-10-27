# Pre-existing defects: non-gate diagnostics

`tests/at412_diagnostics.py` retains the independent failure shapes. It returns
nonzero on a missing reply/event, wrong data, timeout, abort or forced teardown;
zero means the defect did not reproduce in the requested bounded attempts.
It never changes the gate's success rules. All boot argv, exits and exceptions
are retained in the output directory. These defects are assigned to other lanes.

From this worktree (all children inherit CPUs 48-63; server CPUs 48-55):

```sh
taskset -c 56-63 python3 tests/at412_diagnostics.py \
  --defect XS-SHUT-1 --binary build/at412/pre/tomokv \
  --cores 48-55 --port 20280 --output build/diagnostic-shutdown

taskset -c 56-63 python3 tests/at412_diagnostics.py \
  --defect XS-NOTIFY-1 --binary build/at412/pre/tomokv \
  --cores 48-55 --port 20280 --output build/diagnostic-notifications

taskset -c 56-63 python3 tests/at412_diagnostics.py \
  --defect SNAP-STORM-1 --binary build/at412/pre/tomokv --pre-control \
  --seconds 30 --attempts 8 --cores 48-55 --port 20280 \
  --output build/diagnostic-snapshot
```

For POST replace the binary with `build/tomokv` and omit `--pre-control`.
For Redis add `--redis` (uses port 20281); for the script-free snapshot
reproduction add `--mix execs,writers`. Choose `--mode 1s|2s`,
`--engine uring|epoll`, `--atomic 0|1` as needed. Default geometry is 1s,
uring, atomic 0, shards 16; split uses 6:2. No rates are reported.

Fresh PRE reproductions in this directory: XS-SHUT-1 aborts with rc -6;
XS-NOTIFY-1 commits both writes but produces zero keyspace events and zero
tracking invalidations. The archived snapshot reproduction remains in
`docs/at412/deviations/bgsave-storm-stall.json` (including EXEC + writers
without scripts). Fresh snapshot attempts and final-source results are in the
lane report. A failure is never relabelled as a gate pass.

Gate geometry changes:

* T11b finishes each forced-conflict script batch before BGSAVE, waits for the
  save, reloads it, and checks exact replies and restored data. T11a continues
  to force SAVE and BGSAVE across live script Final/escalation windows.
* T15 disconnects a dispatched escalated script and FIFO waiters, proves claims
  and credits drain, then verifies eight accepted script replies and exact data
  before clean SHUTDOWN NOSAVE. In-flight shutdown remains diagnostic-only.
* T16 compares exact same-shard script notifications with Redis, with no missing
  event allowance. Cross-owner read-only scripts race an atomic script writer.
  The archived T16 failure was `[2,1]` from an atomic-0 MSET writer: that writer
  intentionally publishes independent fragments and cannot prove equal pairs.
  The new writer produces atomic generations in both atomic settings.

Every directed-row boot now asserts rc 0 and no forced kill, including teardown
after a test body completes. No crash, abort or stall is tolerated.
