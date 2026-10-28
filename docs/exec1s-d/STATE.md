exec1s-d checkpoint (2026-10-29)

Final production cf3bdaa9e, frozen POST sha4111f5c6ad1784fc6b95fceedc9efe361cf715dbad97f912e130811ab7544f18. Later changes are tooling, fixtures and evidence only. No push. CPU64-95, ports20000-20099; no benchmarks/load generators/full iteration.

Completed final proof:
- Main chain63818 exited0. Both standard differential engines PASS, each split0 235, split1 239, armed0 230, armed1 234, equivalence16. Standard seeds7/19/20/23 plus21 uring,22 epoll. Exact native seed22 full235 passed C-PRE, MERGE, finalPOST too.
- gates_test attempt3 ran alone and passed73tests plus14helpers. Prior2timeout receipts retained; no changes to assertions,45s watchdog or suite counts.
- ZC session63070 completed all4mode/engine legs,24rows pass, normal quiet preflight+ASAN. Supersedes six preflight refusals in broad family; history retained.
- Broad family832pass8fail (sixpreflight,slowlog,propagatedcompat2); fused215/0; atomic0script3/0each; AOF CQ57/0each zerooverflow/drop with positive samples.
- Final latest-per-variant index251jobs,1083passing rows,2failing rows (preexisting slowlog and propagatedcompat2). proof-summary.json compact; live-proof.json full history.
-57/57make-q freshness passed, including all51literalproductiontargets, all, MDBQSBRpair,cost+binding,blockfix2pair.
- Lottery copiedimage and PAD controls passed gateexecfair bothmodes/engines. Seven bounded existing lottery multi_exec cases passed firstattempt withpositiveW16; fullnightlyNOTRUN(memtierrunnerresources).

Counts complete/bound: ordinary48maxdelta0, read-local4exact, allocation3348/13514=.247743, idle+7both fails+2. INCR/depth72perarm; genuine MSET-child48 for PRE/POST/X12/X3/X5/MERGE. Scatter includes two-owner one-childEXEC. Inputs exactly match allallocatedsections; wholebinaries identical exceptMERGEdebug/build-id. Reconstructedsource/probe/steptracesretired. build~27G.

Only active session:30651 = tools/exec1sd_save_full.py C-PRE --busy-only. One full original seed22 plan with GDB traps at actual taken Busy branch destinations, offset0x150 in both namespaces, no traps on accepted admissions. Both traps armed. It was at218legs, noBusyobserved. After this run, run MERGE --busy-only once on same reservedports20000/1; noothercorrectnessserverjob active. Tool staticcodeverified branch destinations: source line alone wrongly points to accepted fallthrough, so it derives takenbranch from frozenassembly and records hash/sites. This new diagnostic seeks originalBusy cause, not a different repeat-timeout.

Then finish:
1. Inspect C-PRE and MERGE diagnostic receipts; ifBusy captured classifywithactualerror, otherwise keepSAVEunresolved. Final nativefull4111passed235; existing barepsfixrepeat6timeoutonC-PRE/MERGE is a DIFFERENT failure and notproofhistoricalBusy preexisting.
2. Update report diagnostic results and finalSTATE. Report coreproof already finalized; noPROOF_STATUS_PENDING. OriginalSAVE and idle+7 stayred unless newevidencechangesit.
3. Retire onlycompletedpassinglargepayloads ifneeded via tools/exec1sd_retire.py ROOT;preservefailurelogs. No supersededarm source/scopes remain. Hash currentbinariesagainstmanifest once beforehandoff. All earlierfreshnessvalidunlessproductionchanges.
4. Commitallmeaningfulsteps, finalgitstatusclean, no push. DQ+4DF+4, EXPECT881/898unchanged owner885/902, collectexec1sline6008beforequick6119.

Slowlog exact unchanged assertion reproduced PRE5/64fused afterinitial8passes,POST2/8; bothsplit8pass. Sourceownercommitmakeslistvisible/dirty beforeIOretirequeuedRESET/logging, allowingBLPOGlogtobecleared. Unfixedpreexisting, noassertion/manifestweakening. FiveunnamedTclsetuperrorsmatchfrozenmanifest. HistoricalSAVEBusy stillnotcaptured. PassivekernelobserverNOTRUN(EACCES, no passwordlesssudo), no systemchanges. Rateattribution/depththresholds/meritremainmaintainer-only. X4off, noFIFO, Dlawsunchanged. PAD-AexactcommonimagePREbehaviourtwinofPOST-layout; largerthanreleasePOST, limitationexplicit.
