# Readability phase 1 comment corrections

## readability-p1fix

Completed source correction against base `7595a6705ac19c1a4eecf7798fde594332f0be0c`
(`origin/cpp`) on branch `cx-readability-p1fix`. Source commits:
`608dfc83ef`, `298e071333`, `4507f9c353`, `59a7b4b3ac`, `58f01be6b6`.

The 114 numbered findings are accounted for below: 113 fixed, one disagreed with
code evidence. All 32 WRONG / DROPPED-INVARIANT / UNESTABLISHED findings are fixed.
Only comments changed in 31 source files owned by A3–A6. R7 generated envelopes
were changed only by `tests/r7shadow_sync.py --write` (also invoked by `make format`).
Code tokens, literal streams, includes, definition order and TOMO_TOOL comments are
unchanged. The stripped production binary is identical to the required reference.
No gate rows, `EXPECT_QUICK` / `EXPECT_FULL`, or other lanes' source files changed.

### Per-finding disposition

Audit IDs below refer to the original reports in `/home/user/Projects/round6-read/`.
All evidence locations refer to this final source tree; the full suggested text was checked against its implementations/callers before editing.
“Fixed” means the finding was addressed, sometimes with a narrower correction than the audit suggested.

| Audit file | Row | Severity | Verdict | Correction and code evidence |
|---|---|---|---|---|
| readability-a3-comment-audit.md | W1 | WRONG | fixed | Home-request switch aborts on unhandled kinds; router supplies eight request kinds. `src/core/pubsub.inc:570`; `src/core/pubsub.inc:677` |
| readability-a3-comment-audit.md | W2 | WRONG | fixed | Shared plan/stage/ACK effects restored. Every IO attempts consumption, but only the elected coordinator can consume a plan; source/destination ClientDrain effects are explicit. `src/core/io_loop.h:2209`; `src/core/lbplanner.cc:512` |
| readability-a3-comment-audit.md | W3 | WRONG | fixed | Both fused acquire paths arm coded replies; split acquire keeps bytes. R7 regenerated. `src/core/io_loop.h:3729`; `src/net/rob.h:240` |
| readability-a3-comment-audit.md | W4 | WRONG | fixed | Boundary ends on Done/retirement or closing with an unpublished initiating op; dispatch stays fenced until it ends. `src/core/io_loop.h:2371`; `src/cmd/multidb.cc:675` |
| readability-a3-comment-audit.md | W5 | WRONG | fixed | No pinned BIO frontier is the precondition; recv_armed can be set for socket polls and epoll owed edges. `src/core/io_loop.h:2887`; `src/core/io_loop.h:3037` |
| readability-a3-comment-audit.md | W6 | WRONG | fixed | Payload is non-copyable/non-movable and travels by owning raw pointer; destructor owns remaining events. `src/core/io_loop.h:5863`; `src/cmd/climon.cc:361` |
| readability-a3-comment-audit.md | W7 | WRONG | fixed | Added clientcompat.cc and its four tracking definitions. `src/cmd/climon.inc:5`; `src/cmd/clientcompat.cc:17` |
| readability-a3-comment-audit.md | D1 | DROPPED-FACT | fixed | Restored every armed executor pass publishing the reclamation tick, including snapshot callbacks, split-local pass end and parked readers. `src/core/read_local.h:4`; `src/core/ex_loop.h:410`; `src/core/genthread.cc:205`; `src/core/rl2s.cc:74` |
| readability-a3-comment-audit.md | D2 | DROPPED-FACT | fixed | CHANNELS/SHARDCHANNELS bad arity uses subcommand syntax; HELP/NUMPAT use wrong-arity replies. `src/core/pubsub.inc:1251`; `src/core/pubsub.inc:1265` |
| readability-a3-comment-audit.md | D3 | DROPPED-FACT | fixed | Restored ordering behind staged bytes and separation from defer_oob ordering of unstaged replies. `src/core/pubsub.inc:354`; `src/net/conn.h:574` |
| readability-a3-comment-audit.md | D4 | DROPPED-FACT | fixed | Restored barrier flag, publish_phase2 counterpart and wrong-reply hazard. Narrowed the suggestion: barrier also covers all-shard commands, not exactly second-wave commands. `src/core/io_loop.h:4392`; `src/cmd/scatter_engine.inc:2248` |
| readability-a3-comment-audit.md | D5 | DROPPED-FACT | fixed | Restored why io_uring needs no epoll-style clear and the CLIENT KILL self regression reference. `src/core/io_loop.h:4941`; `src/core/io_loop.h:1003`; `tests/climon.py:218` |
| readability-a3-comment-audit.md | D6 | DROPPED-FACT | fixed | Named handler_notify selection per operation from the notify_armed_ batch cache. `src/core/io_loop.h:485`; `src/core/io_loop.h:3907` |
| readability-a3-comment-audit.md | D7 | DROPPED-FACT | fixed | Restored one relaxed/unordered feature-mask load per IO batch. `src/core/io_loop.h:646`; `src/core/server.h:2474` |
| readability-a3-comment-audit.md | D8 | DROPPED-FACT | fixed | Restored executor/shard isolation from connection state and subscriber indexes in both headers. `src/core/pubsub.inc:5`; `src/core/pubsub_event.h:3`; `src/cmd/notify.inc:901` |
| readability-a3-comment-audit.md | D9 | DROPPED-FACT | fixed | Restored INFO inflight-write and MGET seq-churn counter names; historic sampling observation is not a new measurement. `src/core/read_local_parse.inc:78`; `src/core/read_local_parse.inc:160`; `src/cmd/t_server.cc:3542` |
| readability-a3-comment-audit.md | D10 | DROPPED-FACT | fixed | Restored why cold CLIENT/MONITOR/TRACKING bodies stay out of IO translation units. `src/cmd/climon.inc:6`; `Makefile:225` |
| readability-a3-comment-audit.md | M1 | MISLEADING | fixed | Worker-local dormant init and same-thread activation replace the implied pre-thread initialization; activate publishes ring/WB. `src/core/io_loop.h:67`; `src/core/io_loop.h:256`; `src/core/genthread.cc:146` |
| readability-a3-comment-audit.md | M2 | MISLEADING | fixed | Added dead/migrating skip cases and all progress event classes. `src/core/io_loop.h:1173`; `src/core/io_loop.h:1206` |
| readability-a3-comment-audit.md | M3 | MISLEADING | fixed | Named commit_client_transfer as the ownership edge and distinguished epoll, io_uring and held FLIP return paths. `src/core/io_loop.h:1739`; `src/core/io_loop.h:1892` |
| readability-a3-comment-audit.md | M4 | MISLEADING | fixed | Selected-set initialization survives count_ truncation; suffix ids/reasons remain live after a partial plan. R7 regenerated. `src/core/io_loop.h:3116`; `src/core/io_loop.h:3312` |
| readability-a3-comment-audit.md | M5 | MISLEADING | fixed | Empty inline frames need no reply; an incomplete tail returns NeedInput only without earlier complete-frame progress. `src/core/io_loop.h:3631`; `src/core/io_loop.h:3797` |
| readability-a3-comment-audit.md | M6 | MISLEADING | fixed | Repointed the serving landmark to Phase 5 / wb_rule::Phase2::serve and regenerated R7. The matching net/rob.h pointer is outside A3–A6 and left for A10. `src/core/io_loop.h:5078`; `src/net/rob.h:366` |
| readability-a3-comment-audit.md | M7 | MISLEADING | fixed | Phase 3 and flush_ready contract distinguish 1s owner work from SplitLocal read-only service. R7 regenerated. `src/core/io_loop.h:5065`; `src/core/ex_loop.h:384` |
| readability-a3-comment-audit.md | M8 | MISLEADING | fixed | Read-local parser enable applies to all frames; slowlog arm is for connection-local commands. Tail placement protects offsets. `src/core/io_loop.h:5831` |
| readability-a3-comment-audit.md | M9 | MISLEADING | fixed | Replaced the invented ownership rationale with preservation of earlier member offsets. `src/core/io_loop.h:5837` |
| readability-a3-comment-audit.md | M10 | MISLEADING | fixed | Forwarding receipts survive installation ACK until pubsub_inflight is zero. `src/core/io_loop.h:5845`; `src/cmd/climon.cc:507` |
| readability-a3-comment-audit.md | M11 | MISLEADING | fixed | No-argument unsubscribe expands current subscriptions and is synchronous only for an empty resulting set. `src/core/pubsub.inc:1142`; `src/core/pubsub.inc:1171` |
| readability-a3-comment-audit.md | M12 | MISLEADING | fixed | Armed-word restriction explicitly covers only the four named kinds, not remote CLIENT UNBLOCK. `src/core/pubsub_event.h:44`; `src/cmd/climon.cc:1082` |
| readability-a3-comment-audit.md | M13 | MISLEADING | fixed | Only coordinator accesses chain items/index/replies; homes consume moved event payloads and coordinator_io. `src/core/pubsub_event.h:127`; `src/core/pubsub.inc:532` |
| readability-a3-comment-audit.md | M14 | MISLEADING | fixed | Added EX producers and refused-post ownership to event transport contracts. `src/core/pubsub_event.h:141`; `src/core/thread.h:664` |
| readability-a3-comment-audit.md | M15 | MISLEADING | fixed | Exact early-exit negation is required; skipping prepare saves the call/validation prologue, not allocation already avoided inside prepare. `src/core/read_local_parse.inc:89`; `src/core/io_loop.h:3182` |
| readability-a3-comment-audit.md | M16 | MISLEADING | fixed | Limited gated parser hook to climon_armed_gate; RESET and CLIENT/MONITOR command paths remain independent. `src/cmd/climon.inc:10`; `src/core/io_loop.h:4008` |
| readability-a4-comment-audit.md | 1 | WRONG | fixed | Production include is reorder.cc only; FIFO translation units do not see reorder.h. `src/core/reorder.h:1`; `src/core/reorder.cc:13` |
| readability-a4-comment-audit.md | 2 | WRONG | fixed | A short-only pass may see an earlier pending long. Kept no-ROB-walk claim limited to all-short pipelines: a scan may visit Done longs even when none remain pending. `src/core/reorder.h:209`; `src/core/reorder.h:173` |
| readability-a4-comment-audit.md | 3 | WRONG | fixed | Named issuer/destructor versus runtime post-join script-pin callers and the atomic-record-release ordering; included former IO owners. `src/core/shutdown.cc:3`; `src/core/genthread.cc:131` |
| readability-a4-comment-audit.md | 4 | DROPPED-INVARIANT | fixed | Restored armed-parser-only reads/writes, uninitialized reorder=0 bytes, and first-parser-entry initialization. `src/core/reorder.h:144`; `src/net/conn.h:918`; `src/core/reorder.cc:2140` |
| readability-a4-comment-audit.md | 5 | UNESTABLISHED | fixed | All three contracts distinguish unhandled failures, unsafe live-worker unwinding, joinable/worker termination and destructor termination; no recovery promise. `src/core/genthread.cc:91`; `src/core/rl2s.cc:119`; `src/core/shutdown.cc:54` |
| readability-a4-comment-audit.md | 6 | UNESTABLISHED | fixed | Scoped no-shard-vector access to split_read_local_pass, not all IO code. `src/core/rl2s.cc:4`; `src/core/io_loop.h:2418` |
| readability-a4-comment-audit.md | 7 | DROPPED-FACT | fixed | Restored first IFID / UINT32_MAX choice and shared unix_owner_tid_ exclusions in both sources; R7 regenerated. `src/core/genthread.cc:113`; `src/core/rl2s.cc:141`; `src/core/server.h:401` |
| readability-a4-comment-audit.md | 8 | DROPPED-FACT | fixed | Restored inherited 8:2 fairness provenance and unmeasured/no-knob caveat without promising an unconditional 4:1 observed service ratio. `src/core/reorder.h:55`; `src/core/reorder.h:56` |
| readability-a4-comment-audit.md | 9 | DROPPED-FACT | fixed | Restored open measurement caveat for bookkeeping and conservative non-head classification. `src/core/reorder.h:316`; `docs/decisions/readability-a4.md:76` |
| readability-a4-comment-audit.md | 10 | DROPPED-FACT | fixed | Explained stack-local union storage avoids default-constructing unused Task slots on every drain. `src/core/reorder.h:326`; `src/core/reorder.h:349` |
| readability-a4-comment-audit.md | 11 | DROPPED-FACT | fixed | Restored monotone Done argument: IO owns recycling and keeps the ROB window stable during the demotion commit. `src/core/reorder.h:252`; `src/core/reorder.h:285` |
| readability-a4-comment-audit.md | 12 | DROPPED-FACT | fixed | Restored prohibition on both sorting and asserting ROB order for legal read-local demotions. `src/core/reorder.h:580` |
| readability-a4-comment-audit.md | 13 | DROPPED-FACT | fixed | Exact per-tenure attribution would require op-path increments, which shutdown reporting must not add. `src/core/shutdown_report.h:190` |
| readability-a4-comment-audit.md | 14 | DROPPED-FACT | fixed | Restored INFO SERVER-only call and no reporting callback/sidecar at boot/runtime. `src/core/rl2s.cc:349`; `src/cmd/t_server.cc:2917` |
| readability-a4-comment-audit.md | 15 | MISLEADING | fixed | Distinguished gate Stopping from only the stop flag and the two give-up sites; R7 regenerated. `src/core/genthread.cc:217`; `src/core/fused_boot_gate.h:65`; `src/core/fused_boot_gate.h:84` |
| readability-a4-comment-audit.md | 16 | MISLEADING | fixed | Separated worker aborts, false-returning main advances and valid-id give_up; failing split workers can stop the gate. `src/core/fused_boot_gate.h:27`; `src/main.cc:416` |
| readability-a4-comment-audit.md | 17 | MISLEADING | fixed | Named io_loop parser batch/Fused mode test, ex_loop and reorder.cc as actual constant consumers. `src/core/genthread_pipeline.h:1`; `src/core/io_loop.h:3641` |
| readability-a4-comment-audit.md | 18 | MISLEADING | fixed | Separated textual inclusion from fused_owner_turn instantiation; only Fused non-SplitLocal loops call it. `src/core/fused_owner_turn.inc:1`; `src/core/io_loop.h:718` |
| readability-a4-comment-audit.md | 19 | MISLEADING | fixed | Named main entry points and reorder.cc selector fallback to run_fused_server. `src/core/genthread.h:1`; `src/main.cc:385`; `src/core/reorder.cc:3435` |
| readability-a4-comment-audit.md | 20 | MISLEADING | fixed | Explained stale/non-socket unlink and live-socket refusal. Retained another source exception omitted by the suggestion: connect errors other than ECONNREFUSED also refuse. `src/main.cc:367`; `src/net/unix_listener.h:67` |
| readability-a4-comment-audit.md | 21 | MISLEADING | fixed | Explained explicit main.o integer-reply instantiation after WAIT stopped pulling it in, and all-caller weak-symbol selection. `src/main.cc:49`; `docs/decisions/readability-a4.md:16` |
| readability-a4-comment-audit.md | 22 | MISLEADING | fixed | SIGINT exits immediately during any pending signal stop or begun shutdown, including after SIGTERM/SHUTDOWN. `src/main.cc:79`; `src/main.cc:88` |
| readability-a4-comment-audit.md | 23 | MISLEADING | fixed | Named local-lane drain and reclamation of already-retired objects; removed incorrect retirement description. `src/core/rl2s.cc:44`; `src/core/rl2s.cc:61` |
| readability-a4-comment-audit.md | 24 | MISLEADING | fixed | Named the actual DatabaseMap/IO-issuer/snapshot/AOF guards and post-join executor-ring teardown. `src/core/genthread.cc:2`; `src/core/rl2s.cc:171`; `src/main.cc:587`; `src/net/uring.h:98` |
| readability-a5-comment-audit.md | 1 | WRONG | fixed | tracking-table-max-keys is boot-latched, per IO owner and refused by CONFIG SET, unlike Redis. `src/core/config.h:702`; `src/cmd/t_server.cc:508`; `src/cmd/tracking.cc:265` |
| readability-a5-comment-audit.md | 2 | WRONG | fixed | tls-auth-clients is live; concurrent reads and writes require atomic_ref. `src/core/config.h:716`; `src/cmd/t_server.cc:2251`; `src/core/io_loop.h:1649` |
| readability-a5-comment-audit.md | 3 | WRONG | fixed | Zero entry bounds exclude non-empty compact collections; zero value bounds admit empty elements. Did not adopt the suggestion’s overbroad claim that every compact form becomes unreachable. `src/core/config.h:461`; `src/store/kvobj.h:707` |
| readability-a5-comment-audit.md | 4 | WRONG | fixed | FLIP command runs on coordinator IO; automatic controller calls on monitor thread and invokes the named coordinator’s reservation hook there. `src/core/server.h:1573`; `src/core/flipctl.cc:734`; `src/core/server.h:1613` |
| readability-a5-comment-audit.md | 5 | WRONG | fixed | Limited owner-only mutation to store data/indexes, registries and stats; restored cross-owner blocking wake interface and its fence/count protocol. `src/core/shard.h:55`; `src/cmd/multi_execute.inc:297` |
| readability-a5-comment-audit.md | 6 | DROPPED-INVARIANT | fixed | Restored Done-before-notify hazard: ROB quiescence alone does not end executor Client access. `src/core/server.h:184`; `src/core/ex_execute.inc:81` |
| readability-a5-comment-audit.md | 7 | DROPPED-INVARIANT | fixed | Restored oldest sealed stamp across all drained queues; early blocker result is an upper bound, not the exact grace floor. `src/core/server.h:811`; `src/core/read_local.h:344` |
| readability-a5-comment-audit.md | 8 | DROPPED-INVARIANT | fixed | Restored owner-only ordinary reads as well as writes; explicitly preserved read-local accounting and wake/gauge interfaces instead of the suggestion’s false all-mutation-on-owner claim. `src/core/shard.h:4`; `src/core/ex_loop.h:1069` |
| readability-a5-comment-audit.md | 9 | UNESTABLISHED | fixed | Caller-supplied slot index has no single-writer guarantee; fetch_add RMWs retain correctness across workers. `src/core/server.h:147`; `src/core/server.h:3162`; `src/cmd/multi.inc:585` |
| readability-a5-comment-audit.md | 10 | DROPPED-FACT | fixed | Restored version-wrapper isolation from main.o and execution-loop translation units. `src/core/version.cc:4`; `Makefile:211` |
| readability-a5-comment-audit.md | 11 | DROPPED-FACT | disagreed | Left the LbClientRead contract unchanged: the proposed “only” two callers is false. script_window_head also calls lb_client_read during ClientDrain. The existing contract is valid. `src/cmd/script_escalation.inc:45`; `src/core/server.h:902` |
| readability-a5-comment-audit.md | 12 | DROPPED-FACT | fixed | Named init_config and its immutable flag, while preserving the independent protected/refused runtime checks. `src/core/config.h:6`; `src/cmd/t_server.cc:881` |
| readability-a5-comment-audit.md | 13 | DROPPED-FACT | fixed | Restored native knob rules: numeric, off allocates nothing, auto, derived thresholds, delete unread fields; retained Redis grammar exceptions. `src/core/config.h:9` |
| readability-a5-comment-audit.md | 14 | DROPPED-FACT | fixed | Restored the documented Redis 7.4 allocation-limit deviation. `src/core/config.h:322`; `docs/decisions/readability-a5.md:26` |
| readability-a5-comment-audit.md | 15 | DROPPED-FACT | fixed | Restored shared boot / CONFIG GET-SET / REWRITE consumers of encoding metadata. `src/core/config.h:427`; `src/core/config.h:429` |
| readability-a5-comment-audit.md | 16 | DROPPED-FACT | fixed | Restored split-only --ratio constraint. `src/core/config.h:579`; `src/core/config.h:1716` |
| readability-a5-comment-audit.md | 17 | DROPPED-FACT | fixed | Restored atomic=1 single committed decision and collapse winner, plus atomic=0 retained EXEC/script/read cuts. `src/core/config.h:689`; `src/cmd/scatter_engine.inc:1861` |
| readability-a5-comment-audit.md | 18 | DROPPED-FACT | fixed | Named atomic_torn as the gate depending on Shard stride and stats offsets. `src/core/shard.h:593` |
| readability-a5-comment-audit.md | 19 | DROPPED-FACT | fixed | Restored hot-path shared-cache-line write rationale in Server and Shard statistics comments. `src/core/server.h:6`; `src/core/shard.h:442` |
| readability-a5-comment-audit.md | 20 | MISLEADING | fixed | Restored measured linked .rodata shrink as the cause of padding, not assertion-metadata requirement; remeasure when contents change. `src/core/version.cc:27`; `docs/decisions/readability-a5.md:11` |
| readability-a5-comment-audit.md | 21 | MISLEADING | fixed | Shard owns a sub-range of the 16384 buckets and keys hashing into it. `src/core/shard.h:3`; `src/core/server.h:410` |
| readability-a5-comment-audit.md | 22 | MISLEADING | fixed | Removed orphaned bandwidth fragment; retained nonzero migration-cost / thrashing rationale. `src/core/shard.h:17`; `src/core/shard.h:343` |
| readability-a5-comment-audit.md | 23 | MISLEADING | fixed | Distinguished bounded refusal, reserved void posts, transfer abort, spinning, and pubsub’s queued-event/marker boolean in both contracts. `src/core/thread.h:350`; `src/core/thread.h:653`; `src/core/server.h:172` |
| readability-a5-comment-audit.md | 24 | MISLEADING | fixed | pin no emits --no-pin; pin yes emits nothing. `src/core/config.h:1894`; `src/core/config.h:1953` |
| readability-a5-comment-audit.md | 25 | MISLEADING | fixed | Named fatal setup failures and nonfatal pidfile/systemd cases; noted unchecked pidfile write/close results. `src/core/cfgfix.cc:161`; `src/core/cfgfix.cc:215` |
| readability-a6-comment-audit.md | 1 | WRONG | fixed | Distinguished task notify hints from ReadyMask completion publication and its Done fence. `src/core/ex_loop.h:12`; `src/core/ex_loop.h:2975` |
| readability-a6-comment-audit.md | 2 | WRONG | fixed | Worker-only access while running; joined boot thread drains graceful reclamation and frees Impl with the executor vector. `src/core/ex_loop.h:105`; `src/core/genthread.cc:123` |
| readability-a6-comment-audit.md | 3 | WRONG | fixed | ExDrain no-store/vector interval ends at FLIP ExInstall or LB stage exit, followed by remask/rebind. `src/core/ex_loop.h:633`; `src/core/ex_loop.h:1687`; `src/core/ex_loop.h:1712` |
| readability-a6-comment-audit.md | 4 | WRONG | fixed | Object value/layout are immutable, but accounting CAS and idle-clock writes are allowed. `src/core/ex_loop.h:1057`; `src/store/flatstore.h:1518` |
| readability-a6-comment-audit.md | 5 | WRONG | fixed | Client bit 3 must be unused/clear so wholesale reset copy does not inherit reply-skip; listed all Op-only bits. `src/exec/op.h:197`; `src/net/conn.h:758` |
| readability-a6-comment-audit.md | 6 | WRONG | fixed | Arming repeats per fused acquisition; borrowed MGET can disarm mid-operation. Corrected both arming comments. `src/exec/op.h:244`; `src/exec/op.h:362`; `src/cmd/xshard_commands.inc:1982` |
| readability-a6-comment-audit.md | 7 | WRONG | fixed | Producers acquire head; consumer quiescence checks acquire retired and tail. `src/exec/masked_queue.h:68`; `src/exec/masked_queue.h:526` |
| readability-a6-comment-audit.md | 8 | DROPPED-INVARIANT | fixed | Restored mutable-field ownership and immutable concurrent-read restriction; completion orders all completer writes, including flags/descriptors. `src/exec/op.h:5`; `src/exec/op.h:273`; `src/core/reorder.h:96` |
| readability-a6-comment-audit.md | 9 | DROPPED-INVARIANT | fixed | Restored removal-before-forwarding/execution and empty-before-shard-transfer obligations. `src/core/atomic_parked.h:4`; `src/core/ex_loop.h:1578` |
| readability-a6-comment-audit.md | 10 | UNESTABLISHED | fixed | All three comments now say SmallBuf growth does not check malloc and reply OOM is unhandled. `src/exec/op.h:69`; `src/core/ex_loop.h:1115`; `src/base/slice.h:303` |
| readability-a6-comment-audit.md | 11 | DROPPED-FACT | fixed | Restored deliberate absence of repartition/generation checks in every push/pop path. `src/exec/masked_queue.h:4`; `src/exec/masked_queue.h:266` |
| readability-a6-comment-audit.md | 12 | DROPPED-FACT | fixed | Restored boot and FLIP ExDrain -> ExInstall remask callers, parked IO dispatch and abort on install failure. `src/exec/masked_queue.h:6`; `src/core/ex_loop.h:1691` |
| readability-a6-comment-audit.md | 13 | DROPPED-FACT | fixed | Named Channel’s actual header/consumers, task-dispatch replacement and release-only SPSC publication. `src/exec/exqueue.h:1`; `src/persist/aof.h:345`; `src/snapshot/snapshot.h:130` |
| readability-a6-comment-audit.md | 14 | DROPPED-FACT | fixed | Restored live evicting-policy construction condition and preserving the earlier parser precision promise. `src/core/ex_loop.h:76`; `src/core/ex_execute.inc:107` |
| readability-a6-comment-audit.md | 15 | DROPPED-FACT | fixed | Restored why the older unit cannot depend on this parked fragment and the partial-install/probe deadlock back edge. `src/core/ex_execute.inc:43`; `src/core/ex_loop.h:2804` |
| readability-a6-comment-audit.md | 16 | DROPPED-FACT | fixed | Restored deque cursor-word placement as well as footprint/offset rationale; checked target libstdc++ deque layout (start 16, finish 48). `src/core/atomic_parked.h:21`; `src/core/atomic_parked.h:66` |
| readability-a6-comment-audit.md | 17 | DROPPED-FACT | fixed | Explained distinct ARM leftover-session and DISARM cleanup purposes; retained the unestablished in-flight boundary caveat. `src/core/atomic_tripwire.h:153`; `src/core/atomic_tripwire.h:163` |
| readability-a6-comment-audit.md | 18 | DROPPED-FACT | fixed | Restored intentionally empty DEBUG TRIPWIRE payload and no-header acceptance contract. `src/core/atomic_tripwire.h:318`; `src/core/atomic_tripwire.h:327` |
| readability-a6-comment-audit.md | 19 | MISLEADING | fixed | Owner-only data/index mutation explicitly allows approximate foreign access accounting. `src/core/ex_loop.h:7`; `src/core/ex_loop.h:1083` |
| readability-a6-comment-audit.md | 20 | MISLEADING | fixed | Phase 3 acknowledges after reclamation only outside LB freeze; frozen passes may ACK in Phase 2. R7 regenerated. `src/core/ex_loop.h:511`; `src/core/ex_loop.h:533` |
| readability-a6-comment-audit.md | 21 | MISLEADING | fixed | Same-key exclusion is same-connection only; fresh inbox work pauses with xshard retry debt. `src/core/ex_loop.h:2753`; `src/core/atomic_parked.h:116` |
| readability-a6-comment-audit.md | 22 | MISLEADING | fixed | Stack captures die within rotation; queued Client/ROB handles may survive and use tombstone/WB corpse grace. `src/core/ex_loop.h:1373`; `src/core/ex_loop.h:890` |
| readability-a6-comment-audit.md | 23 | MISLEADING | fixed | Corrected keyspace cursor purpose, fused field group and tail padding affecting sizeof only. `src/core/ex_loop.h:3120`; `src/core/ex_loop.h:3140`; `src/core/ex_loop.h:3167` |
| readability-a6-comment-audit.md | 24 | MISLEADING | fixed | Named IO-local completers and scatter/blocking/MULTI/pubsub/script/persistence protocols. `src/exec/op.h:63`; `src/core/ex_loop.h:1525`; `src/cmd/blocking.inc:515` |
| readability-a6-comment-audit.md | 25 | MISLEADING | fixed | Separated MULTI heap children from script/MULTI stack Ops, all with caller-managed lifetimes. `src/exec/op.h:3`; `src/exec/op.h:242` |
| readability-a6-comment-audit.md | 26 | MISLEADING | fixed | read_cut_lo fills the alignment hole after shard in the fixed Op footprint; retained the unestablished age-bound caveat. `src/exec/op.h:172` |
| readability-a6-comment-audit.md | 27 | MISLEADING | fixed | Inline decoder uses one allocation for Slices and bytes, with one argv free. `src/exec/op.h:468`; `src/net/resp.h:169` |
| readability-a6-comment-audit.md | 28 | MISLEADING | fixed | Retire exactly once; after-processing requirement is scoped to quiesced users, with snapshot chunk early-retirement exception. `src/exec/exqueue.h:21`; `src/snapshot/snapshot.cc:1072` |
| readability-a6-comment-audit.md | 29 | MISLEADING | fixed | FIFO serves xshard retry, boundary scans and writer promotion, not stale forwarding. `src/core/atomic_parked.h:2`; `src/core/atomic_parked.h:123` |
| readability-a6-comment-audit.md | 30 | MISLEADING | fixed | Phase is a reused row role; first capture is global across kinds; collapse/exclusion reuse dump columns. Also corrected the adjacent exclusion helper’s first-capture claim. `src/core/atomic_tripwire.h:21`; `src/core/atomic_tripwire.h:128`; `src/core/atomic_tripwire.h:320` |
| readability-a6-comment-audit.md | 31 | MISLEADING | fixed | Same-key diagnostic walk runs for all armed finite-cut chain answers, independent of finding a smaller ticket. `src/core/atomic_tripwire.h:41`; `src/store/flatstore_atomic.inc:1428` |
| readability-a6-comment-audit.md | 32 | MISLEADING | fixed | Only initial notes reservation has a caught allocation failure; later failures do not roll back notes/tasks. Only service_multi_chain acts on false. `src/core/ex_txn_chain.inc:9`; `src/core/ex_txn_chain.inc:31`; `src/core/ex_txn_chain.inc:87` |

### Counts

| Audit | WRONG | DROPPED-INVARIANT | UNESTABLISHED | DROPPED-FACT | MISLEADING | Fixed | Disagreed | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A3 | 7 | 0 | 0 | 10 | 16 | 33 | 0 | 33 |
| A4 | 3 | 1 | 2 | 8 | 10 | 24 | 0 | 24 |
| A5 | 5 | 3 | 1 | 10 | 6 | 24 | 1 | 25 |
| A6 | 7 | 2 | 1 | 8 | 14 | 32 | 0 | 32 |
| **Total** | 22 | 6 | 4 | 36 | 46 | **113** | **1** | **114** |

All 22 WRONG, 6 DROPPED-INVARIANT and 4 UNESTABLISHED findings are fixed. Of the remaining findings, 35 DROPPED-FACT and all 46 MISLEADING findings are fixed; A5 #11 is disagreed with evidence above.
No numbered finding is wholly outside the ownership partition. A3 M6 has an outside A10 pointer, listed separately below; it is not counted as a second numbered finding.

### Additional audit notes and spot-check requirements

These items are separate from the 114 numbered rows; they do not inflate the counts.

| Source | Verdict | Result and final evidence |
|---|---|---|
| Explicit masked-queue spot check | fixed | `src/exec/masked_queue.h:4` restores the deliberate absence of repartition checks from push/pop. Lines 6–9 identify boot and FLIP's ExDrain → ExInstall barrier as remask callers; the executor ACKs drained retired frontiers before remasking in ExInstall, with IO dispatch parked until all installs ACK. `src/core/ex_loop.h:1688` is the implementation. |
| Explicit reclamation-tick spot check / A3 D1 | fixed | `src/core/read_local.h:3` names every armed executor pass, including snapshot-driven passes, both RotationBoundary paths, the split pass's end and parked infinity. |
| A3 notes: broken epoll sentence | fixed | `src/core/io_loop.h:976` states the two lifetime/progress consumers and why each checks the receive flag. |
| A3 notes: one-time arming fence | fixed | `src/core/io_loop.h:3089` states that ArmTransient can recur after sidecar allocation failure. |
| A3 notes: negative control ignores epoch | fixed | `src/core/io_loop.h:2439` says the control skips revalidating whether the sampled stage is still live; the epoch is still checked. |
| A3 notes: obsolete flush header | fixed | The deleted ex-wb / three-stage description above `IoLoop::flush_ready` is removed. The current contract describes fused and split serving. |
| A6 notes: Issued enum comment | fixed | `src/exec/op.h:29` calls Issued the shutdown drain sentinel. `src/core/shutdown.cc:165` is its sole store; normal runtime dispatch does not store it. |
| A6 #30 adjacent exclusion helper | fixed | `src/core/atomic_tripwire.h:128` makes exclusion capture conditional on being the first capture of any kind. |
| A3 M6, matching pointer in net/rob.h | outside A3–A6: A10 | `src/net/rob.h:366` still says “PHASE 2's bounded serve”; the owned flush_ready pointer now says Phase 5 (`src/core/io_loop.h:5078`). Left the A10 pointer untouched as requested. |
| A6 notes: stale ROB handshake | outside A3–A6: A10 | `src/net/rob.h:19–21` still describes an Issued/Done handshake. The actual runtime handoff uses task publication and Done/AofWait completion, as corrected in op.h. |
| A6 notes: stale ordinary-dispatch marker | outside A3–A6: A7 | `src/cmd/flip_liveness.inc:176–177` still contrasts blocking reset Free with an ordinary-dispatch Issued marker. Ordinary runtime dispatch does not store Issued either. |

The A5 #11 disagreement leaves the existing `LbClientRead` comment at
`src/core/server.h:899` unchanged. The audit's proposed exclusive caller list is
false: `script_window_head` also calls `server.lb_client_read()` at
`src/cmd/script_escalation.inc:45`. The two IO LB methods are not the only callers.

### Unresolved code concern from A6 (outside this comment-only lane)

The audit's **possible S1 AOF durability defect** is supported by the inspected
code, but has not been reproduced at runtime. Under `appendfsync always`,
`AofManager::defer_completion` tries to claim a blocking Op with an
`Issued → AofWait` CAS (`src/persist/aof.cc:3032`, A18). Runtime dispatch leaves the
reset `Free` state (`src/exec/op.h:110`; `src/cmd/flip_liveness.inc:176`, A7); the
only Issued store is the shutdown sentinel at `src/core/shutdown.cc:165`.
For a still-Free Op, the CAS fails and returns false. `blocking_task_done` then
publishes Done after a false defer_completion result
(`src/cmd/blocking.inc:529–536`, A13). This path can acknowledge a completed
blocking write before the fsync receipt. A targeted durability test and any
behavioral correction belong to those owners. No production-code fix or targeted
runtime reproduction was made here.

### Verification

All build and test commands used `LC_ALL=C` and CPU affinity within 112–127.
Build metadata was pinned for all builds and freshness checks:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 112-127 make -j16 all
taskset -c 112-127 /home/user/Projects/calib/binary-neutral.sh \
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv
```

The build and comparison exited 0. Exact binary-neutral output:

```text
IDENTICAL (11167504 bytes after stripping)
```

The reference comparison strips debug information, symbol tables and GNU build-id;
it compares the remaining program bytes, not the full debug ELF. The final build
log and comparison are retained in [evidence](docs/readability-p1fix/evidence/).

The raw `tools/source_tokens.py` audit compared all 31 edited source files
against the base, without alias normalization: **186,812 preprocessing
tokens**, **1,240 string/raw-string and character literal occurrences**, and
**107 TOMO_TOOL comments** are identical. TOMO_TOOL checks include
the exact comment text and its position between preprocessing tokens, so added
prose did not move a marker across code. The ownership map confirms A3–A6 for
every edited source file. Per-file counts are in
[source-tokens.json](docs/readability-p1fix/evidence/source-tokens.json).

Reproduce the raw token, literal and marker audit from this worktree root:

```sh
taskset -c 112-127 python3 - <<'PY'
import bisect
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp

BASE = '7595a6705ac19c1a4eecf7798fde594332f0be0c'
spec = importlib.util.spec_from_file_location('partition', '/home/user/Projects/calib/readability-partition.py')
partition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(partition)
owners = partition.owner_map(ROOT / 'src')
files = subprocess.check_output(['git', 'diff', '--name-only', BASE, '--', 'src'], cwd=ROOT, text=True).splitlines()

def literals(source):
    return tuple(m[0] for m in cpp.LEXER.finditer(source) if m.lastgroup in ('raw', 'string'))

def anchors(source):
    ends = [token.end for token in cpp.lex(source)]
    return tuple((m[0], bisect.bisect_left(ends, m.start())) for m in cpp.LEXER.finditer(source)
                 if m.lastgroup == 'comment' and 'TOMO_TOOL_' in m[0])

result = []
for filename in files:
    before = subprocess.check_output(['git', 'show', f'{BASE}:{filename}'], cwd=ROOT).decode()
    after = (ROOT / filename).read_bytes().decode()
    lane = owners[filename.removeprefix('src/')][0].split()[0]
    assert lane in ('A3', 'A4', 'A5', 'A6'), (filename, lane)
    before_tokens = tuple(t.text for t in cpp.lex(before))
    after_tokens = tuple(t.text for t in cpp.lex(after))
    assert before_tokens == after_tokens, (filename, 'preprocessing tokens changed')
    assert literals(before) == literals(after), (filename, 'literal stream changed')
    assert anchors(before) == anchors(after), (filename, 'tool comment changed or moved')
    result.append(dict(file=filename, lane=lane, tokens=len(after_tokens),
                       literals=len(literals(after)), tool_comments=len(anchors(after))))
print(json.dumps(dict(base=BASE, files=result, count=len(result),
                     preprocessing_tokens='IDENTICAL (raw lex, no alias normalization)',
                     literal_stream='IDENTICAL', tool_comments='IDENTICAL text and token boundaries'), indent=2))
PY
```

The final `make format` and `make format-check` both passed with pinned
**clang-format 18.1.8**, covering 418 files. The formatter's R7 sync and a separate
check-mode invocation both reported `R7 shadow production envelopes: current`.
`make -q` exited 0 after the successful release build and final format. The final
format made no source changes beyond source commit `58f01be6b6`.
`git diff --check 7595a6705` passed. These exit statuses are recorded in
[final-checks.json](docs/readability-p1fix/evidence/final-checks.json).
`make format` was run before every source commit and before the report commit;
all associated format checks passed.

The requested tests run through the gate's job interface with this command:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
export GATE_PROOF_NO_RATES=1 GATE_TEST_PORT=25599
export GATE_ONLY_JOBS='source_identity reorder_sync reorder_identity abba_selftest'
export GATE_LEDGER="$PWD/build/readability-p1fix-ledger"
taskset -c 112-127 tests/gate.sh quick \
  --server-cores 112-119 --load-cores 120-127 --load-smt '' --ports 25500-25598
```

The job planner adds the `release` prerequisite. The selected allocation has one
8-thread correctness slot at ratio 6:2 and three ports per slot. Server CPUs are
112–119, load CPUs 120–127, build CPUs 112–127; the unit-test listener is pinned to
port 25599. This is a **partial job run**, not a full quick/full/iteration gate or
a performance receipt. The ABBA job is its serverless comparator/fixture test,
not a benchmark.

All selected jobs exited 0. The gate recorded **5 ok, 0 FAIL**, including the
release prerequisite:

| Gate job | Result | Evidence |
|---|---|---|
| `release` | PASS | Release build and footprint locks. |
| `source_identity` | PASS | `tools/source_identity.py`: 61 C++ TUs in both database variants and six shared C TUs; 11 assertion tests plus the directed abort/site-map check. |
| `abba_selftest` | PASS | Full serverless comparator/fixture suite, including **83 `tests/gates_test.py` tests** and **12 label-fixture unittests** called by `tests/gate_receipt.py --self-test`. |
| `reorder_sync` | PASS | Current generated envelopes; stale-envelope negative control, 11 source-token tests, and lottery insertion/missing/duplicate controls. |
| `reorder_identity` | PASS | Normalizer self-checks; `strict_noop=True: 352/352 identical bodies`; missing policy/parser/clone/callback/scan and changed-opcode controls reject as required. |

Exact gate summary:

```text
GATE(PARTIAL): 5 ok, 0 FAIL; no EXPECT tally, ABBA, NIC or receipt; ledger: /home/user/Projects/cx-readability-p1fix/build/readability-p1fix-ledger.partial
```

[Gate output](docs/readability-p1fix/evidence/gate.log),
[partial ledger](docs/readability-p1fix/evidence/gate-ledger.partial),
[serverless test log](docs/readability-p1fix/evidence/gate-selftests.log), and
[R7 identity output](docs/readability-p1fix/evidence/r7-identity.log) are committed.
The gate artifacts were produced under `build/gate-run.4aZjCe`.
The committed serverless log removes trailing whitespace emitted by unittest;
the original output remains in that run directory. No result lines were removed.

The R7 identity job's built-in FIFO control is **PAD kind A, a behavior twin**:
PRE/FIFO behavior (reorder disabled) with the candidate's text size and layout.
Its [provenance](docs/readability-p1fix/evidence/r7-fifo-twin.json) records that only
the two capability bytes differ and every other ELF byte is equal. This is a
static identity/negative-control proof, not a measured performance arm. No PAD
binary is committed.

No rows were added or retired on either side of the quick-tier exit:
**DQ = 0, DF = 0**. The unchanged maintainer constants remain
`EXPECT_QUICK=1212` and `EXPECT_FULL=1229`; no count adjustment is needed.

### NOT RUN

- Full quick, full or iteration gates, including the complete runtime boot/command
  matrix. Only the listed selected jobs and their release prerequisite ran.
- Benchmarks, rate comparisons, ABBA measurements and NIC measurements. No rate or
  performance claim is made for this binary-identical comment change.
- The targeted blocking-write / `appendfsync always` durability reproduction
  described above; no behavioral fix is included.
- Push or merge. All work is local to `cx-readability-p1fix`.

### Delivery hygiene

Source changes are limited to the 31 A3–A6 files listed by the token audit; the
remaining tracked additions are this report and small proof artifacts. Generated
R7 blocks were never edited by hand. No binary or file over 1 MB is committed.
The final source and proof are committed on the lane branch, and the worktree is
left clean. Build/test artifacts remain ignored under `build/`.
Final measured worktree size: **5.4G**, below 30 GB.
