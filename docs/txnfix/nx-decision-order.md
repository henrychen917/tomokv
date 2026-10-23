# NX decision/read ordering repair

The Stage A candidate `2a0eefa...` fails the existing atomic_torn RENAMENX
detector: the final focused probe found an anomaly in its third 256-round arm.
PRE ran sixteen 256-round arms without an anomaly. The older broad regression
had also found one split RENAMENX anomaly. This is a candidate regression;
it is not assigned to the unfixed Stage B findings merely because it involves
an atomic group. Receipts: final-stage-a-checks/conditional-*.

Stage A changed NX validation to ignore the physical image of a cancelled
transaction, because waiting on it can deadlock a transaction child. It first
called find(), then scanned foreign decision words for an undecided unit.
A foreign finalizer on another owner can commit between those two steps:
find skips the epoch-zero candidate, then the scan sees a ticket and does not
wait. Both tests have passed using inconsistent moments. This can let the
second NX group install over a newly committed first winner.

The repair checks the foreign decisions before reading the value. An undecided
physical candidate causes the existing Retry. A ticket observed by the scan
is visible to the subsequent find. Cancellation remains terminal, so a
cancelled transaction image can still be ignored. There is no new loop or
change to ordinary GET/SET/MGET/MSET paths. Neither loop header changes.

The repeated protocol detector retains raw reply/value failures in the later
nx-decision-order proof directory. The earlier diagnostic returned process
status zero even when its result tuple contained an anomaly; that status is
not a semantic pass. The diagnostic driver now returns nonzero for anomalies.
The detector's data checks are unchanged.

An explicit fresh-boot replay of the retained bad image then produced two
failures in256 races: both replies were1, both sources were gone, and only
winner-b remained. See nx-decision-order/before-0.log.

Reviewing the reordered guard exposed a separate pre-existing own-parent
failure. On PRE and the first ordering repair, `MULTI; SET a 1; SET b 2;
RENAMENX a b; EXEC` times out when a/b have different owners. Receipts are in
nx-parent-before/runs.json. The validator erased its own-connection context,
then treated the parent's private destination as an undecided foreign image.
It could therefore wait for its own commit. S1/S6 govern: the child now keeps
its own origin context and excludes its parent and sibling records from the
foreign-decision check. execfix.py exercises both RENAMENX and COPY against a
destination written earlier in the same EXEC. The earlier control build was
stopped before editing source; its partial log is marked interrupted.
