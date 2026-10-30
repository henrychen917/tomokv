# Wave11 landing request

## wave11 integration

Integration on `cx-wave11`, from `e2b237926`, without pushing. Merged in order:
`cx-flipfix5`, `cx-scriptfix3`, `cx-climonfix5` (including climonfix4), and
`cx-flushmerit`, with separate no-fast-forward commits. The shared source cache
owns the original bytes, lowercase SHA, parsed flags and body offset. PAUSE
borrows cached flags on warm EVAL/EVALSHA; no-writes compiled closures use those
same flags. Persistent protected EVAL/FUNCTION interpreters and library
runtime environments survive the merge.

The source-declaration inventory is **977 quick / 994 full**, exactly +31/+31
from 946/963. All added collectors are before the quick-tier exit; see
[collector lines and labels](docs/wave11/row-inventory.json). The prepared [landing fixture](docs/wave11/landing-label-fixture.json) lists
every declaration. Its installation and the EXPECT repair are confined to a
throwaway copy for `abba_selftest`, as requested; the tracked fixture stays at
the headline until the maintainer lands the count update. `EXPECT_QUICK=946` and `EXPECT_FULL=963` remain untouched;
the maintainer must set 977/994 at landing. Tcl promotions are the union of
both histories; [reconciliation](docs/wave11/tcl-reconciliation.json) retains
all named compatibility skips without adding any.

Build, instruction, correctness and artifact receipts are being assembled.
No throughput claim is made. Performance loads and full iteration remain
maintainer-owned. The separate FLIP-EXEC-TRANSFER-TIMEOUT, flushfix2, execfifo,
rlfix4 and lineshare variants are outside this wave.
