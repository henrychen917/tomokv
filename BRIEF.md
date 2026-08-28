# Extend SORT's BY/GET pattern dereference to multi-executor configurations

## What exists today

`SORT key BY pattern` and `SORT key GET pattern` dereference a pattern into a *second* key per
element (`weight_*` → `weight_42`, `h_*->field` → hash field lookup). TomoKV currently serves those
two options only when a single executor owns the whole keyspace:

    src/cmd/t_sort.cc:85
    bool sort_deref_local(Server& server) {
        return server.placement().ex_threads().size() == 1;
    }

With more than one executor the request is refused, at `src/cmd/xshard_commands.inc:263` and `:280`,
with `kSortByDenied` / `kSortGetDenied` (declared in `src/cmd/t_sort.h:48-51`).

The reference server has no such restriction in non-clustered mode. Against a pinned Redis 7.4.2
oracle at a 6:2 io:ex ratio the `sort` differential suite reports **2191 differing operations out of
4512** on seed 7 and **2329 of 4495** on seed 19, in both atomic modes. Nearly all of them are the
refusal above; the rest are follow-on reads of a `SORT ... STORE` destination that was never written
because the SORT itself was refused.

**Your job is to make the BY and GET options work when the dereferenced keys live on other
executors, so those two constants become unreachable and can be deleted.**

## The mechanism you must use

This tree's law is single-owner: **a thread may only touch the store of a shard it owns.** A
dereference that names another executor's key therefore cannot be a direct lookup. The tree already
solves exactly this shape for multi-key reads — read these first:

- `src/cmd/scatter_engine.inc` — the scatter/gather engine. `xshard_execute` (~line 2014) is the
  entry point; the gather lambda around line 2227 shows how values come back from other owners.
- `src/cmd/xshard_commands.inc` — per-command scatter definitions; MGET is the model to copy in
  shape. Lines 263 and 280 are the two refusals you are replacing.
- `src/cmd/t_sort.cc` — `sort_run` is the single ordering implementation for every SORT form.
  `sort_image` turns a source snapshot into the natural-order element list.

Shape to aim for: phase one resolves the element list on the source key's owner and builds the
concrete dereferenced key names; the engine then gathers those keys from their owners; ordering and
reply construction run once the gather completes. `sort_image` already accepts a null `owner` for
the cross-shard completion path, so the seam exists.

## Requirements

1. **One read cut for the whole command.** The tree pins a single wall-clock and snapshot cut per
   logical operation (`ScatterState::now_cut_ms`, installed by `xshard_execute`; see the expwide
   work). Every dereferenced key must be read against that same cut. A SORT that reads key A at one
   instant and key B at another produces a reply describing a keyspace that existed at no instant.
2. **Preserve the reference's semantics exactly**, including: a BY pattern containing no `*`
   suppresses ordering entirely (`dontsort`); a missing key, wrong-type value, or absent hash field
   dereferences to NULL and sorts as if zero/empty; `GET #` returns the element itself; multiple
   GET patterns emit one reply element each, in order.
3. **`SORT ... STORE`** must write the destination through the ordinary owner path.
4. **Do not weaken the single-owner law, and do not touch the MVCC resolver or the atomics engine.**
5. **`Op` and `Client` footprints are static_asserted (336 / 1984 bytes).** New state belongs in the
   scatter arena, not in those structs. New struct members go at the **cold tail**.
6. When you are done, `sort_deref_local` and both `kSort*Denied` constants should have no remaining
   callers — delete them and their declarations.

## Validating your work — the geometry matters

The current gap shipped because it was validated where it cannot appear: with one executor, every
key shares an owner and the refusal never fires.

**Any check you write or describe must run with at least two executor threads** (the gate uses
`--shards 16 --ratio 6:2`), and it must *find* a cross-owner pair rather than assume one: walk
candidate key names, bucket them by `DEBUG SHARD`, and assert that the BY/GET pattern for at least
one element resolves to a **different owner** than the source key. If no such pair is found, the
check must fail loudly rather than pass quietly.

State that geometry explicitly in your final report.

## Rules for this lane

- **Never build. Never run `make`. Never start a server, a load generator, or any test script.**
  All building and testing happens in the main session. The box permits one server at a time and
  starting one would corrupt a measurement in flight.
- **Commit early and often** to the current branch (`t-sortxshard`). A long uncommitted run that is
  interrupted loses everything; small commits are recoverable.
- Write your reasoning and findings to `NOTES-SORTXSHARD.md` as you go.
- If any part of this turns out to be already implemented, or genuinely unreachable under this
  architecture, **say so plainly and change nothing** rather than inventing work.
- If you conclude the full cross-owner dereference cannot be done without violating rule 4, stop and
  write down precisely which invariant blocks it and what the alternative would cost. That is a
  legitimate outcome and more useful than a partial implementation.
