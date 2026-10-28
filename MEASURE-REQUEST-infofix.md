## infofix

Work in progress on `cx-infofix`, base `393d6ceb129d8c99dffd70959d6a19267c525fe0`.
CPUs 48–63 only; correctness listeners 20400–20499. No push or throughput claim.
The seven stored reproductions differ on frozen PRE versus Redis 7.4.10 in both
modes: `docs/infofix/pre-repros.json`. Binary hashes: `docs/infofix/pre-sha256.txt`.

Owner decisions pending:

- INFO-CMDSTAT-FIELDS: the root report and renderer explicitly document the
  omission of unmeasured timing. Exact always-on `usec` conflicts with zero
  added hot-path instructions. Stopped under the task's deliberate-restriction rule.
- DEBUG-RELOAD-OPTIONS: snapshot plans/format contain keys and database mapping,
  but no function libraries. The assigned Tcl assertions require function save,
  duplicate detection and merge semantics. This requires a persistence architecture
  extension; stopped under the task's architecture rule. No superficial option parser
  is presented as a fix.

- INFO-ERRORSTATS: no accepted-attempt error journal exists. A generic reply-error
  hook counts rejected/replayed script attempts and misses the distinction between
  rejected and failed calls. Exact accounting needs transaction/script lifecycle
  integration; stopped under the architecture rule. The exploratory hook was removed.
- LAT-HIST-2: exact per-command samples are retained. The candidate amortizes
  metadata lookup, histogram locking, and commit flushing across a homogeneous GET
  batch; it does not replace each duration with a batch mean. Whether the measured
  13% loss is recovered remains for the maintainer. Literal clock amortization would
  need a ruling about changed histogram duration semantics.

Implementation and validation receipts will be finalized here. Performance and
full iteration stay with the maintainer. Five directed collector rows currently
sit before the quick exit (DQ=+5, DF=+5); EXPECT constants are unchanged.
