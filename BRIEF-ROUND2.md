# Round 2 — the cross-owner gather works; a BY-weight ordering difference remains

## Where round 1 got to (measured, not claimed)

Your work builds clean and the refusals are gone — `sort_deref_local`, `kSortByDenied` and
`kSortGetDenied` have **zero** remaining references. Against the pinned Redis 7.4.2 oracle at
`--shards 16 --ratio 6:2 --atomic 0 --enable-debug-command yes`, the `sort` differential suite went

    before your lane:  4512 ops, 2191 diffs
    after  your lane:  4512 ops,   93 diffs

That is the cross-owner dereference working. What is left is a narrower, different problem.

## What remains — and what it is NOT

**Every one of the remaining diffs is `SORT` / `SORT_RO` with `BY so:a_*`.** No other pattern shape
appears. The full captured output is committed alongside this brief as
`EVIDENCE-remaining.txt` (seed 7); the first entries are:

    DIFF op 268 ['SORT', 'so:l0', 'BY', 'so:a_*']
      target: [nil, "alpha", "Echo!", "HOTEL", nil, "alpha"]
      oracle: [nil, "Echo!", "HOTEL", nil, "alpha", "alpha"]
    DIFF op 279 ['SORT_RO', 'so:l0', 'BY', 'so:a_*']
      target: [9, 68, 50, 19, 83, 6]
      oracle: [9, 50, 19, 83, 68, 6]
    DIFF op 280 ['SORT', 'so:z1', 'BY', 'so:a_*']
      target: [13]
      oracle: [95]

In 268 and 279 the **multiset is identical and only the order differs** — one element migrates
(`68`; the second `alpha`). 280 is a single-element reply where the element itself differs, which
does not fit an ordering story at all and needs its own explanation.

**I have already ruled out the two obvious explanations. Do not re-test these:**

1. **Not a tie-break difference.** With a BY pattern matching no keys at all
   (`SORT tb:list BY nokey_*` over `e5 e3 e9 e1 e7 e2`), TomoKV and Redis return the **identical**
   `e1 e2 e3 e5 e7 e9`. Both tie-break lexicographically on equal scores, and they agree.
2. **Not mixed present/absent weights.** With `mx:list = 73 89 23 31 10 99` and only
   `w_73=5 w_89=7 w_10=2` present, both return the **identical** `23 31 99 10 73 89`.

So the divergence needs something those two probes did not have.

## What to investigate

- **What is actually in `so:a_*` at the failing ops.** Live inspection after the run shows values
  like `so:a_73 = "Bravo073"` — a **non-numeric string**. A numeric SORT whose weight will not parse
  should produce `ERR One or more scores can't be converted into double` in the reference; both
  servers returned data instead, so at those ops the values must have been different (numeric, or
  absent). Read the `sort` generator in `tests/differ.py` and establish exactly what `so:a_*` holds
  at ops 268/279/280 and how it mutates over the run. **The generator is the ground truth here, not
  a post-run `GET`.**
- **Whether the weight your gather returns for a given element matches what the source key's owner
  would have returned.** Your gather crosses owners; a subtly wrong key derivation, a missed
  hash-field form, or a value read against the wrong pinned cut would produce a *different weight*,
  which shows up exactly like a reordering.
- **Op 280 specifically.** A one-element reply differing in the element itself means either the
  source collection differs between the two servers (an earlier silent divergence) or the reply is
  not what the argv suggests. Chase this one first — it is the most diagnostic, and it is the case
  an ordering theory cannot explain.
- Check whether the failing sources skew to a particular type. 268/279 are `so:l0` (list), 280 is
  `so:z1` (zset). Sets and zsets have their own natural-order rules in the reference.

## Rules unchanged

- **Never build, never run `make`, never start a server or any test script.** I run everything.
- **Commit early and often** to `t-sortxshard`.
- Append to `NOTES-SORTXSHARD.md`.
- Validation geometry is still `--shards 16 --ratio 6:2`, both atomic modes, with cross-owner pairs
  *found* via `DEBUG SHARD` rather than assumed, failing loudly if none exists.
- If you conclude some part of the residue is a **generator** artefact rather than a server
  difference, say so with the evidence and change no server code — that is a legitimate finding, but
  it must be demonstrated from the generator's source, not asserted.
