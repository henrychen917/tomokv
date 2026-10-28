exec1s-d checkpoint (2026-10-29)

Final production cf3bdaa9e, frozen POST sha4111f5c6ad1784fc6b95fceedc9efe361cf715dbad97f912e130811ab7544f18. Later changes are proof tools/fixtures/evidence only. All frozen arms and PAD controls remain unchanged.

Counts complete: ordinary48 maxdelta0; read-local4 exact; allocation3348/13514=.247743; idle+7 bothnamespaces misses+2. Original INCR/depth72 scopes per arm complete. Added true MSET-child48 scopes for PRE/POST/X12/X3/X5/MERGE all PASS; includes actual two-owner one-child EXEC. Reconstructed inputs have exact matching allocated sections; all whole binaries identical except MERGE's debug/build-id. tools/exec1sd_receipts.py validates both matrices and bindings. All reconstruction trees/probes retired.

Active sessions:
- 63818: family-attempt4 build/gate-run.q0JfME finished832ok8FAIL. Failures: Redis Tcl fused isolated slowlog assertion and propagated compat2 autharity; six zc failures because idle-core preflight refused to boot during concurrent work. No other family failures. Fused supplement215/0; script-a0 both3/0; AOF CQ both57/0, zero drop/overflow. Now standard differ uring (build/gate-run.QWIdhL), then epoll, then gates_test. No full iteration.
- 36945: final4111 native exact original seed22 full split0 plan (POST --native --label=-final), using ports20000/1, active at seed22. Prior C-PRE and MERGE native full235/0; oldPOST22d235/0. Historical SAVE Busy still not reproduced/classified; bare psfix repeat6 timeout is a different pre-existing failure. Passive observer NOT RUN (uprobe EACCES; passwordless sudo unavailable); no system changes.
- All other sessions completed (84110 scatter arms, 62469 receipts). Counts/probes/PAD/lottery done.

Remaining:
1. Let63818 and36945 finish; inspect every failure and standard differential plan/legs.
2. Run tools/exec1sd_proof.py zc ALONE after no other lane work is running. Four legs mode0/1 engineuring/epoll, release+ASAN, unchanged quiet preflight. Preserve original6failed startup rows. This should supersede the matching family zc verdict while keeping failure history.
3. If gates_test still times out, diagnose and rerun alone; original harness is unchanged, earlier2runs failed2/73 because45s scheduler fixture timeouts under concurrent builds.
4. Run tools/exec1sd_proof.py freshness (57make-q checks includingall51productiontargets) and tools/exec1sd_receipts.py.
5. Finish MEASURE-REQUEST-exec1s-d.md PROOF_STATUS_PENDING, final live/differ/gates counts, nativefinalresult, zero-copy reruns, CQ proof. Keep SAVE unresolved and idle+7 explicit. State DQ+4DF+4; EXPECT881898 unchanged, owner should885902. Countcollector6008 beforequick6119.
6. Retire completed passing payloads with tools/exec1sd_retire.py ROOT (current27G, about30G cap). Preserve failures. Commit all meaningful steps, clean worktree, no push.

Slowlog: unchanged isolated Tcl assertion expects newest BLPOP after EXEC(LPUSH,SLOWLOG RESET). FinalPOST2/8fused fail; PRE5/64fused fail afterinitial8passes; bothsplit8pass. Root source commit makes list visible/dirty before IO retirement executes queued RESET/records, allowing blocked log to be cleared. Pre-existing and unfixed; no assertion/manifest/retry change. Gate's five unnamed setup errors are existing manifest entries, not new failures. All evidence in slowlog-*.json.

Important: user explicitly permits correctness servers/Redis7.4/selected jobs/serverless counts onCPUs64-95, ports20000-20099 only. No benchmarks/loadgenerators/fulliteration. Builds-j32. All commands taskset64-95. No subagents. Keep X4off/FIFOout/Dlaws. Report not a green landing request. Report gives actual benchtxn built+hash but neverexecuted. PAD-A is exact common-image twin of POST-layout, larger than releasePOST; that limitation is explicit.
