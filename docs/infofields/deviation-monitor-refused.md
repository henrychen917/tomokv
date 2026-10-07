# MONITOR commands refused by authorization

The infofields2 delivery takes path **2**. Its gated `monitor` leg drives admitted
ordinary commands, admin commands, AUTH redaction, binary quoting and exact RESP
framing. It compares the complete resulting stream with Redis 7.4.10 and its
independent expected stream. It has no tolerance, xfail, or skipped assertions.
The three refused ordinary commands are generated only by the separate strict
witness. The witness is not in the differential generator inventory or gate suite
list and exits nonzero on the current target.

With two running peers, reproduce it exactly with:

```sh
taskset -c 120-127 python3 tools/infofields_monitor_strict.py \
  127.0.0.1 18899 127.0.0.1 18900 --seed 7
```

The script prints the exact extra and missing payloads for each peer before its
strict equality assertion. Current target-only lines are:

```text
"SET" "ifmon:denied" "v"
"GET" "outside:denied"
"GET" "ifmon:noauth"
```

Their timestamps and checked driver endpoint vary. Redis emits none of these
lines. CONFIG refusals remain invisible because the resolved subcommand is admin.

Dispatch currently feeds the armed MONITOR before its normal ACL/NOAUTH verdict.
The predecessor's global reorder changed 55 of 1,584 selected hot body instances,
including ordinary parse/dispatch in main, genthread, rl2s and reorder:
[patch](rejected-acl-order.patch),
[audit](trial-acl-body-audit/summary.json).

This lane also tried a pure duplicate verdict only inside the armed feed, first
through `acl_check_queued` in that feed, then through an isolated overload in the
ACL TU. The first complete audit found 53 unexplained changed climon bodies (28 multi-DB,
25 db0). Its two changed ordinary bodies were INFO-related db0 HELLO compiler
changes, subsequently fixed in the retained delivery; they are not attributed to
the MONITOR predicate. Later isolated ACL trials also changed unrelated emitted
bodies.
Receipts are in [the trial proof](../infofields2/top-level-proof/summary.json) and
[the subsequent body audit](../infofields2/rejected-armed-body-audit.txt).
No global authorization reorder was retained. No runtime selector was added.

To re-gate the refusal assertions after fixing the ordering, change the gated
`run_monitor_suite` call to use `strict=True`, retain all permanent seeds, and
require both peers to equal its expected stream. Remove the separation only after
the witness passes both atomic modes in split 6:2 and armed fused at 16 shards.
This changes no public gate row count.

## Remaining script requirement

Redis explicitly feeds EVAL/EVALSHA/FCALL (including their `_RO` variants) before
the script runs. Their `skip_monitor` flags suppress a duplicate generic feed;
they do not suppress these commands. The retained implementation and gated
generator cover all six entry commands.

**Nested `lua` feeds are still unfinished.** This lane built a MONITOR-only script
handler and executor-to-IO delivery bridge, but it failed the ordinary-body audit
and was removed from runtime code. The attempted implementation and audit are
[retained here](../infofields2/rejected-armed-script.patch) and
[here](../infofields2/rejected-script-body-audit.txt). This is an additional unmet
requirement from the 05:15 addendum, not a claim that path 2 authorized omitting it.
The full task must not be considered complete or landable on the basis of the
gated MONITOR leg alone.

The on-demand witness also exposes the six missing nested lines:

```sh
taskset -c 120-127 python3 tools/infofields_monitor_strict.py \
  127.0.0.1 18899 127.0.0.1 18900 --seed 7 --scripts
```

Reference semantics: Redis 7.4.10
[call/processCommand](https://raw.githubusercontent.com/redis/redis/7.4.10/src/server.c),
[scriptCall](https://raw.githubusercontent.com/redis/redis/7.4.10/src/script.c),
[EVAL/EVALSHA](https://raw.githubusercontent.com/redis/redis/7.4.10/src/eval.c), and
[FCALL](https://raw.githubusercontent.com/redis/redis/7.4.10/src/functions.c).
