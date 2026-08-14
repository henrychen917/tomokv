---
name: thredis-notify-scaling-invariants
description: OWNER RULE — cache/memory/message-passing work must never revert a CDB or IO<->EX notification optimisation; guard script notifyguard.sh enforces the 11 protections
metadata:
  type: feedback
---

**Owner, 2026-08-09:** "make sure the message passing and cache residency and memory residency don't
revert changes that make cdb or notifying io to ex and ex to io slow or scale bad with core count."

**Why this needs a guard and not just care:** every protection below is an OPTIMISATION that looks
like removable complexity to someone whose brief is "make the structures smaller". Padding, a
one-line-per-CDB rule, and a redundant-looking identity branch all read as waste on a footprint
audit. Removing any of them is silent on a single-thread bench and gets WORSE with core count.

# The protections (all verified present on the ship line, 2026-08-09)

**EX->IO completion bus (CDB = "common-data-bus", server.h ~1644-1655):**
- `cdbSlots` is EXACTLY one cache line, aligned, explicitly padded — enforced by
  `_Static_assert(sizeof(cdbSlots) == CACHE_LINE_SIZE)`. Workers on different CDBs therefore never
  share a completion line; without it every reply publication invalidates a line another core polls.
- Reply-ready slots are ONE-BYTE atomics (`_Static_assert(sizeof(redisAtomic uint8_t) == 1)` +
  `ATOMIC_CHAR_LOCK_FREE == 2`), so publication is a release STORE, not a word-wide RMW that would
  serialise every completer on the line.
- `cdbIndexFor()` (server.c ~2732) has an IDIV-FREE identity path: `if (ex_id < server.num_cdb)
  return ex_id;` with the comment "auto config: num_cdb == num_workers => identity, no idiv".
  Reducing num_cdb to save memory silently puts an integer division on EVERY dispatched op.

**IO->EX dispatch ring:** `exQueue.head` and `.tail` are on separate aligned lines (`retired` shares
the consumer line, `cached_head`/`staged_tail` share the producer line — deliberate and correct).
`commit_seq_line` and `tomo_atomic_inflight_line` are each independently line-isolated.

**Notification is amortised, never per-command:** the notifier fd handler only DRAINS the eventfd;
the real work runs in `beforeSleepIO`. A wake per command would put a syscall on the fast path.

# The guard

`tmp/notifyguard.sh <worktree>` — grep-based, ~1s, no box needed. Run it on every candidate branch
BEFORE building. All 10 in-flight branches passed on 2026-08-09.

**Lesson from writing it:** my first version reported a FALSE failure on the clean baseline (regex
expected two closing parens where the code has three). A guard that cries wolf on a clean tree is
worse than no guard — always run a new guard against the KNOWN-GOOD tree first and require it to
pass there before trusting a failure elsewhere.

**If a removal is genuinely intended**, it needs a measurement showing per-worker throughput stays
FLAT as worker count rises — not merely that total throughput held at one thread config. See
[[thredis-worker-overhead-bound]] for the ~2.0M ops/s/worker baseline that must not degrade.
