# Blocked-client idle-timeout reap

## Root cause

`IoLoop::client_cron_pass()` reads `Client::last_interaction_s()` and closes a normal client when
the whole-second idle age is strictly greater than `timeout`. It explicitly exempts clients while
`Client::blocked()` is true (and separately exempts subscribers), so the timeout sweep itself did
contain the documented blocking-client exemption.

Network receive and successful send completion refresh `last_interaction_s()`. Entering or leaving
a blocking command did not. Consequently a BLPOP-family client retained the timestamp of the recv
that submitted BLPOP throughout its parked lifetime.

When the blocking operation completed, reply retirement called `blocking_retire()` (or
`blocking_scatter_retire()` for a resumed move) and cleared `blocked`. The IO loop then ran the
client cron later in the same pass. A socket send submitted by retirement cannot refresh activity
until its CQE is processed in a later pass. If the 100 ms cron beat was due in that interval, the
client was no longer exempt and its old timestamp made the entire blocked duration look idle. The
cron closed it before the blocking reply reached the test, producing EOF. Which pass contained the
cron beat accounted for the intermittent result.

Temporary owner-side diagnostics captured the failing state after a 2.4 second wait with
`timeout=1`: the blocked-to-unblocked retirement retained a timestamp 2--3 whole seconds old, and
the following timeout close saw a fully retired ROB and no blocking barrier.

## Relation to 744cd57f5

Commit 744cd57f5 did not remove the explicit `!c->blocked()` timeout guard and did not change the
sources of `last_interaction_s()`. It made `parse_and_dispatch()` return `NeedInput` and allowed a
quiet partial-frame connection with an armed recv to leave `active_`; before that change the same
buffered tail was repeatedly scanned and counted as work. Removing that accidental scheduling
activity changed when IO passes and the 100 ms cron beat coincided. It exposed the pre-existing
unblock-before-send timestamp gap; parking was not itself the semantic error.

## Fix

The IO retirement hook detects the blocked-to-unblocked transition and resets
`last_interaction_s()` to the IO loop's cached monotonic second. This covers ordinary blocking
retirement and the blocking-move scatter retirement without changing their APIs. The deferred WAIT
completion path applies the same rule. The parked interval is therefore excluded from idle age,
and a newly unblocked client starts a fresh idle interval even when cron runs before send
completion.

## Deterministic regression

`tests/limits.py` now uses the boot-gated one-shot `DEBUG BLOCKING-TIMEOUT-REAP` synchronizer. After
BLPOP has remained blocked beyond `timeout=1`, its retirement consumes the arm and makes that IO
owner's client cron due in the same pass, before the send CQE. The test requires all of the
following:

- the BLPOP wake reply arrives;
- a following PING succeeds, proving the connection remains usable; and
- the synchronizer's counter advances exactly once, proving the vulnerable ordering fired.

As a negative control, the same build and test with only the idle-baseline reset removed failed in
that row with EOF immediately after the synchronizer fired. This replaces the former reliance on
repeating the timing lottery.

## Validation

- Release build: passed.
- Deterministic negative control: failed at `blocked.read()` with EOF after the ordering arm fired.
- Final `tests/limits.py`: 10/10 passes against one `--atomic 1` purpose boot on port 7835, with the
  server and every test process restricted to cores 40--43.
- Final shutdown: `live_conns=0`, `rob_not_quiesced=0`, and `unsent_bytes_pending=0`.
- `gate.sh` and benchmarks were not run, as requested.
