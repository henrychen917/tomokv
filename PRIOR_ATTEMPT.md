A prior attempt (branch codex-cxcarrier, 8768e62d3 "keep promoted express dispatches in core")
measured a WASH: +0.9% instructions/op for no net ops gain over 3 interleaved pairs. Lesson: the
express-promotion approach PAID instructions to move state. The clientExecTail split (already
merged) captured the cheap layout locality (+2.9%). What remains of the 1,336-byte/13-line
carrier cost must be removed WITHOUT adding per-dispatch instructions: eliminate writes/reads,
do not relocate them. Candidates: per-dispatch RESET paths touching cold lines (reset only what
the previous command provably dirtied — a dirty-mask or generation tag, one word), init-on-first-
use for fields most commands never read, and any memset/field-sweep in the fake reuse path.
Verify by counting DISTINCT CLIENT LINES TOUCHED per dispatched GET (add a DEBUG-mode counter),
not by instruction diffs alone.
