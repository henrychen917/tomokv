# Round 3 — the collation finding was right; a MULTI read-your-own-writes race remains

## Round 2 verdict: correct, and it fixed the harness

Your collation diagnosis was right and I confirmed it. With `LC_ALL=C` on **both** sides:

    differ sort seed 7,  atomic 0 : 4512 ops, 0 diffs -> PASS
    differ sort seed 19, atomic 0 : 4495 ops, 0 diffs -> PASS
    differ sort seed 7,  atomic 1 : 4512 ops, 0 diffs -> PASS
    differ sort seed 19, atomic 1 : 4495 ops, 0 diffs -> PASS

From 2191 diffs to zero. The reference uses `strcoll` for alpha ordering so its collation follows
the locale; the oracle had been booting without a pinned locale. Your `differ_gate.sh` preflight and
the full-argv diagnostics are the right fix, and the abbreviated argv really was the whole of the
"op 280 returns one element" mystery.

## What blocks the merge: `tests/sort.py` multi-ryow

Your own battery fails, reproducibly, on the lane binary at `--shards 16 --ratio 6:2`:

    run 1: 10 failures     run 2: 10 failures     run 3: 12 failures

**Every failure is `multi ryow N` (order / projection / stored).** The shape is, inside one
transaction:

    MSET s:mrw_<e> <new weight> ... (and s:mrd_<e>)     <- overwrites weights that ALREADY EXIST
    SORT s:mr BY s:mrw_*
    SORT s:mr BY s:mrw_* GET s:mrd_*
    SORT s:mr BY s:mrw_* STORE s:mrdst
    EXEC

Typically **one element is displaced** and its position is consistent with that element's weight
being read at a state that predates the transaction's own `MSET`.

## What I isolated for you — do not redo this

`tests/ryow_sort_repro.py` (committed, takes a port) is a reduced 20-trial version. Results:

| condition | result |
|---|---|
| weight keys **absent** before the MULTI | 0/20 mismatched |
| weight keys **already present**, overwritten inside the MULTI | **3/20** mismatched in one run, 0/20 in another |
| same script against **redis 7.4.2** | 0/20 — the expectation is correct, this is not a harness error |

So: it needs a **prior value to go stale**, and it is **timing-sensitive** — the reduced script is
flaky where the full battery is reliable (10-12 per run), so use `tests/sort.py` as the detector and
the reduced script only for narrowing. `EVIDENCE-multiryow.txt` holds a failing run.

Note the differ suite reports **0 diffs** and cannot see this at all — `gen_sort` never overwrites a
weight inside a transaction. Your battery is the only detector; do not weaken it.

## The likely mechanism — verify, do not assume

This tree's transactions are **ordered per owner but not across owners** (recorded by the
`t-storeorder` lane, which fixed the sibling case where a two-hop store's second wave overtook an
older same-connection op). Your cross-owner gather issues reads to *other* owners; if those reads
are not ordered behind the transaction's own earlier writes **on each participating owner**, a
gather can legitimately observe a pre-transaction value for some keys and the new value for others —
exactly the single-element displacement seen here.

Read `src/cmd/multi.inc` (EXEC lowering, `:1434` sets the connection barrier),
`src/cmd/scatter_engine.inc` (`xshard_execute`, the pinned cut installation) and the ROB-head
barrier the storeorder lane added at `src/core/io_loop.h:1478`. The question to answer precisely:
**at the moment the SORT gather issues, is every participating owner guaranteed to have applied the
transaction's earlier writes to the keys that gather will read?** If not, that is the fix.

Do NOT fix this by making the gather read a live value instead of the pinned cut — the pinned cut is
load-bearing for expiry correctness. The ordering, not the cut, is what needs repair.

## Rules unchanged

- **Never build, never run `make`, never start a server or any test script.** I run everything.
- **Commit early and often** to `t-sortxshard`.
- Geometry for any check you describe: `--shards 16 --ratio 6:2`, both atomic modes, cross-owner
  pairs *found* via `DEBUG SHARD` and failing loudly if absent.
- If you conclude the correct answer is that the battery's expectation is wrong for this
  architecture, you must show that from the reference's semantics — but note redis answers 0/20 on
  the identical sequence, so that case needs to be made very carefully.
