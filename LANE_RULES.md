# Standing rules for every lane in this program

- **Never build. Never run `make`. Never start a server, a load generator, or any test script.**
  All building, testing and benchmarking happens in the main session. The box permits ONE server at
  a time; starting one corrupts a measurement in flight and may be the very A/B that judges you.
- **Commit early and often** to your branch. A run that is interrupted must leave recoverable work.
- Record reasoning, line references and your measurement surface in `NOTES-<LANE>.md`.
- **If the premise is false — already implemented, unreachable, or wrong for this architecture —
  say so plainly and change nothing.** That is a good outcome, better than invented work.
- Keep the change **narrow**. Do not bundle unrelated cleanups: extra churn makes the A/B
  unattributable, and an unattributable win is treated as a loss.

## Architecture invariants you may not break

- **Single-owner law**: a thread only touches the store of a shard it owns. Cross-owner work goes
  through the scatter/gather engine (`src/cmd/scatter_engine.inc`), never a direct reach.
- Do not weaken the MVCC resolver, the atomics engine, or the pinned read/commit cuts.
- `Op` is static_asserted at **336 bytes**, `Client` at **1984**. New members go at a struct's
  **cold tail** — a member inserted early shifts every hot field's offset and has bitten this tree
  before.
- **Zero cost when off.** Disabled features must emit unchanged hot-path code: boot-latched
  `if constexpr`, cold-tail placement, dual handler instantiation. Follow the existing idiom rather
  than adding a runtime branch to a hot loop.
- Numeric knobs follow the house style: `0` = off and must not allocate, `-1` = auto, thresholds
  derive themselves rather than being magic constants.

## The acceptance bar (owner's, both gates must hold)

1. **The affected command wins on at least one of throughput, latency, or memory, AND does not lose
   throughput.** A latency-only or memory-only win is fine; a throughput regression is not, even
   alongside a memory win. So a memory-targeted change still owes a throughput number.
2. **GET, SET, MGET and MSET lose nothing.** Hard zero-regression on the four headline commands.

Failing either gate sends the lane to a deprecated branch with its findings. State in your notes
**which commands your change can touch**, so the main session knows which cells to measure.

## Validation you DESCRIBE but never run

Name the **geometry** any check needs: executor count, shard count, same-owner vs cross-owner keys,
one connection or several. Cross-owner pairs must be *found* by walking candidates and bucketing
with `DEBUG SHARD`, never assumed, and a check that cannot find its geometry must FAIL LOUDLY rather
than pass quietly. A check that cannot fail proves nothing.
