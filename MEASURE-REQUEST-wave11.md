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

### Maintainer queue — NOT RUN here

Use the frozen arm hashes below, the gate's existing offered-load instrument,
acceptance rules and reviewed CPU geometry. Include contemporaneous identical-arm
nulls. Record rate at matched offered load, cycles/op, instructions/op, IPC and
latency; these serverless instruction counts do not decide throughput merit.

1. Wave null: merged POST against headline `e2b237926`, the unchanged
   [28 cells](docs/wave11/cells/null28.txt). Use **three blocks for p8g, h05 and
   h06**; retain the standing three-block notify_exm control and all remaining
   cell settings. Compare PRE/PAD-A as the labelled layout control.
2. Fixed-anchor race: POST against
   `/home/user/Projects/bench-bins/tomokv-headline-991d48f65`, the
   [generic fourteen](docs/wave11/cells/generic14.txt), the
   [nine read-local cells](docs/wave11/cells/readlocal9.txt), and the EXEC
   matrix below; retain three blocks and this comparison independently of the
   wave null.
3. EXEC: `/home/user/Projects/calib/exec-merit.py`, PRE/POST,
   `--conns 64 --threads 16 --cells all --blocks 3 --secs 20`.
   All eight `x{1,2}s_a{0,1}_{unc,hot}` cells keep pipeline 4, two INCR children,
   four competing plain writers in hot cells, databases=1, 1s read-local=1 with
   64 shards, and split ratio 6:2 with 16 shards. Preserve the driver's balancing
   and automatic-FLIP settings. Use one pinned benchtxn executable and record its
   SHA. Require zero order violations; retain EXEC and competing writes separately.
4. Contended-script storm: `/home/user/Projects/calib/script-storm-merit.py`,
   PRE/POST, `--blocks 3 --secs 30`. Preserve T6: 2s 6:2, 16 shards, atomic 0,
   databases=1, two keys on distinct owners, eight EVAL clients, four EXEC,
   four WATCH/EXEC and four plain writers. Require exact final values, zero
   script refusals and zero atomic-order violations; retain each class and
   WATCH aborts separately.
5. Landing gate: the maintainer applies **977/994** and the prepared label
   fixture, then runs `tests/gate.sh iteration`. No partial correctness receipt
   here is represented as that landing gate.

[Measurement inputs and anchor hashes](docs/wave11/measurement-inputs.json)
bind the cells and driver sources. The maintainer schedules the quiet box and
appends results as MEASURE-RESULT. No performance workload has been started by
this integration lane.
