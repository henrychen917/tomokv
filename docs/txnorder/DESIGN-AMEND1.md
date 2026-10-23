# Applied amendment A′: writer episodes

Owner approved 2026-10-22. D1-D10 remain as chosen.

### 6.6 Amendment text

**§2.4, step 2b, replace the row "Writer mark | wait until that writer has run …" with:**

> | Writer mark carrying episode stamp *s* | wait iff my version's `age_ns > s` (I was admitted after the writer's blocked episode began). A unit with `age_ns ≤ s` ignores the mark. |

**§2.4, append after the table:**

> Invariant I. Placement never adds a writer-blocking entry for a unit with `age_ns > s` on a key, or on `""`, that carries a writer mark with stamp *s*. Writer-blocking entries are validation claims, and TO-B claims, which block writers from placement. Validation claims are created only in the placement turn, after the shard's placement returned ready.

**§2.6, "Blocking predicate", append:**

> TO-B group claims count as started on a shard from the group's placement there, because groups read immediately (txn_group.inc:185). Writers therefore also wait on placing TO-B groups. Invariant I covers both kinds of writer-blocking entry.

**§2.6, "Fairness", replace with:**

> **Fairness (writer episodes).**
> - **Start.** A writer opens one blocked episode per shard. At the first poll on which any of its keys is blocked, it draws one stamp `s = now_ns()`. In the same owner turn it leaves a writer mark `{token = &op, stamp = s}` on every key it touches on that shard, or on `""` for zero-key writers (FLUSHDB/FLUSHALL fragments).
> - **End.** Marks and stamp persist unchanged until the writer passes the claim gate. Passing removes them all and ends the episode. A later block opens a new episode.
> - **Failure.** A writer that cannot record its complete mark set removes all of its marks on that shard and stays blocked. Its next poll opens a new episode.
> - **Effect.** Placing units with `age_ns > s` wait behind the marks (2.4 2b). Older units may pass.
> - **No marks.** Blind `--atomic 1` groups, scripts, blocking serves, DEBUG loaders and WATCH registration leave no marks.

**§2.12, "When validation claims block writers", replace with:**

> From validation, as today (D10 as chosen; confirmed by amend1). The alternative (block only from the unit's start, plus a dirty re-check) is not adopted, for three reasons:
> - it is unsound if writers test the per-shard started bit;
> - it is sound only with a phase-word CAS by which writers break placing WATCHes (amend1 §5.2);
> - it does not remove the writer → placing-unit edge of TO-B groups.

**§3.2, consequential edits:**
- **E1:** "a unit claim of a unit started on this shard (an EXEC after its phase CAS; a TO-B group from its placement); a validation claim".
- **E4:** "an older PLACING unit (or its waiter mark); an EXECUTING unit; a writer mark whose stamp is below my `age_ns`; a completing blind group".
- **Proof:** replace "Proof by levels" for levels 2-3 with the rank argument of amend1 §6.2.
- **§3.3 "Writers":** S(W) = units with `age_ns ≤ s(W)` that claim W's keys on its shard, or that shard. Units admitted after the episode starts cannot place there.
- **§5.3:** delete "No chain of older units". Under D10, writers can wait behind finite chains of placing units, and the rank strictly decreases along every such chain.

