from pathlib import Path
import json,shutil
root=Path('docs/txnfix/txnfix3')
j=json.loads((root/'final4-summary.json').read_text());assert j['post_sha256']=='1c808efda63159b31e45e7e960053052b8ac6cd3345049dc23e857bd3da845cc'
p=Path('MEASURE-REQUEST-txnfix.md');s=p.read_text();start=s.index('## txnfix3');before=s[:start];part=s[start:]
old='''- Previous-checkpoint PAD **(A), limited PRE-behaviour aggregate-text-size control**
  (superseded; the final binary control is being regenerated after live proof):
  `build/txnfix3/pad-certified/tomokv`, SHA-256
  `83d6a51112ad42148a0adadd07eb2a6bd42c6d24e993b8d64672262d7df68e3e`.
  It links unchanged PRE objects plus unreachable padding. PRE .text is
  7646972 bytes; the previous POST/PAD were 7740636. This is **not** a full internal-function
  or Server-cold-tail layout twin. It is diagnostic only, cannot close the
  open universal instruction bar, and is not evidence of an accepted gain.
  [Exact build and limits](docs/txnfix/txnfix3/pad-certified/build.json).'''
new='''- PAD **(A), limited PRE-behaviour aggregate-text-size control**:
  `build/txnfix3/pad-final4/tomokv`, SHA-256
  `34a0b1a80c587e25b09aae7eede6f12c39fa27ebbbe6c127cb270a011ff07c3a`.
  It links unchanged PRE objects plus unreachable padding. PRE .text is
  7646972 bytes; POST/PAD are 7740572. This is **not** a full internal-function
  or Server-cold-tail layout twin. No full layout twin was produced. This
  limited control is diagnostic only, cannot close the open universal
  instruction bar, and is not evidence of an accepted gain.
  [Exact build and limits](docs/txnfix/txnfix3/pad-final4/build.json),
  [frozen digests](docs/txnfix/txnfix3/final4-frozen.json).'''
assert old in part;part=part.replace(old,new)
part=part.replace('Only the existing nonzero-reference\n   reaper arm can call the cold attempt destructor.', 'Only the existing nonzero-reference\n   reaper arm can call the cold attempt destructor. The group lifetime unit\n   accounts for this ownership bit in its exact pin counts and adds a check\n   that release fails while an owner pin is live; no lifetime/data guard is\n   removed.')
part=part.replace('Original T05 parameters and G5 assertions were not changed.', 'Original T05 parameters and G5 assertions were not changed. The final\n   controls reproduce PRE **duplicate delivery** in both modes and pass POST\n   in both modes: [fresh paired G5 receipts](docs/txnfix/txnfix3/final4-controls/runs.json).')
checkpoint=part.index('### Final runtime proof in progress')
part=part[:checkpoint]+'''### Final proof and handoff

The final runtime source is `e904cd285`; every POST runtime proof below uses
SHA-256 `1c808efda63159b31e45e7e960053052b8ac6cd3345049dc23e857bd3da845cc`.
The checker validates receipt completeness and exact NX repeats in
[final4-summary.json](docs/txnfix/txnfix3/final4-summary.json).
TomoKV correctness servers use CPUs 112–119; the Redis oracle uses CPU 120;
clients use 121–127. Ports are 22600–22699, and compiles/serverless proof stay
within CPUs 112–127. No benchmark,
full gate, workload on cores 0–111, or push was performed.

| Proof family | Final result | Receipt |
|---|---|---|
| Build and production targets | `all`, all 29 job targets, `mdbqsbr-live-arms`; 30/30 freshness checks | [build](docs/txnfix/txnfix3/final4-build/runs.json) |
| txniso and AOF | 8/8 configurations; 4/4 AOF companions | [main proof](docs/txnfix/txnfix3/final4-proof/runs.json) |
| EXEC NX | Four cells, each 0 failures / 8192; two bare controls also 0/8192 | [main proof](docs/txnfix/txnfix3/final4-proof/runs.json) |
| Original EXEC audits | POST 28/28; PRE 23 data failures and five passes (four WATCH controls plus one counter stress leg) | [originals](docs/txnfix/txnfix3/final4-proof/original-post/) |
| Original-parameter Stage B | 20/20: T03/T04/T05 (SMOVE and RPOPLPUSH)/T10, both modes and atomic settings | [Stage B](docs/txnfix/txnfix3/final4-proof/stage-b/) |
| Group batteries | G1–G6 + GX in both modes × databases 1/16; AOF 2/2 | [main proof](docs/txnfix/txnfix3/final4-proof/runs.json) |
| Atomic-0 mover coverage | Both modes pass all mover variants; fresh G5 PRE fails duplicate delivery 2/2, POST passes 2/2 | [paired controls](docs/txnfix/txnfix3/final4-controls/runs.json) |
| Redis 7.4 | 112/112 focused matrix legs plus both armed-fused witnesses | [split](docs/txnfix/txnfix3/final4-proof/differ-split/test.log), [fused](docs/txnfix/txnfix3/final4-proof/differ-armed-fused/test.log) |
| Broad batteries | 36/38; two existing fused failures retained below | [main proof](docs/txnfix/txnfix3/final4-proof/runs.json) |
| Writer/AOF/snapshot/FLIP | 15/15, including four 60-second writer checks and 183 FLIP checks | [companions](docs/txnfix/txnfix3/final4-extras/runs.json) |
| WATCH liveness | 60/60 fresh boots; crossed-WATCH POST 4/4 while PRE times out 4/4 at the unchanged 20-second deadline | [crossed controls](docs/txnfix/txnfix3/final4-cross-watch/runs.json) |
| Directed transaction units | group, admission, intents, help all pass; independently unfenced/undrained controls fail their exact intended assertions | [controls](docs/txnfix/txnfix3/final4-controls/) |
| MSETNX barrier witness | Both tests pass in both modes; barrier-removed build fails the new witness 4/4 | [broken-barrier receipts](docs/txnfix/txnfix3/final4-barrier-control/proof/runs.json) |
| Serverless and ledger | 66/66 gates_test; INFO/shell checks pass; ledger source/fixture 652/652, protected EXPECT mismatch only (self-tests 9/10) | [serverless](docs/txnfix/txnfix3/final4-serverless/runs.json) |
| Identity/layout | selected hot 1208/1208; lbstall 601/601 + 603/603; locked sizes/old offsets and 35 existing TLS symbols preserved | [identity](docs/txnfix/txnfix3/identity-final4/README.md) |
| Scatter cost | Constructor/destructor/destroy canonical identity; 264 paired sampled cases have no per-function increase; universal sequence identity remains unproven | [disassembly review](docs/txnfix/txnfix3/scatter-cost.md) |

The two nonzero broad rows are **not waived**. Armed-fused `execatomic` expects
an old MGET value but receives uniformly new values; concurrent-read legs show
zero torn reads. Armed-fused `atomic_torn` aborts the server with SIGABRT (-6)
on the previously reported read-local resize path. Both failures reproduce on
the final PRE controls; the resize defect remains unfixed. Prior source/stack
analysis is in [the resize report](docs/txnfix/txnfix2/read-local-atomic-resize.md).
No assertion was changed to make either pass.

The missing universal ordinary-path instruction proof is still a failure to
complete **goal 1's literal acceptance requirement**. Preparation, execution
and completion have changed emitted bodies; bounded paths with fewer
instructions cannot certify all values, errors, snapshot interactions or
phase-two branches. The limited PAD is also not a full layout twin. The
quiet-box performance null remains unmeasured. **Stage B is not accepted or
merge ready on this handoff.** Goals 2–4 have their code and final receipts;
the existing fallback remains separately reviewable in `e1609593d`, with its
policy decision left to the owner.

All receipts, including rejected compiler/fixture trials and earlier complete
passes, are retained. Directory names such as `certified` are checkpoint
labels, not acceptance claims; [PROOF-REVISIONS.md](docs/txnfix/txnfix3/PROOF-REVISIONS.md)
identifies the binaries and compressed trace maps. Production source checks
pass `git diff --check`; raw receipts retain original whitespace. The branch
adds no txnfix3 gate row (DQ=0, DF=0), and neither protected EXPECT assignment
was edited. No push was performed.
'''
p.write_text(before+part)
readme='''The atomic-0 mover repair, falsifiable MSETNX barrier witness and all twelve selected-hot repairs are committed and verified. **Stage B remains unaccepted:** the literal universal ordinary-path instruction-sequence proof is incomplete, and the quiet-box null is unmeasured.

The [txnfix3 handoff](../../../MEASURE-REQUEST-txnfix.md#txnfix3) records implementation commits, complete proof families, row accounting and the owner measurement request. [final4-summary.json](final4-summary.json) verifies the final receipt counts; [scatter-cost.md](scatter-cost.md) lists every scatter/state helper and the precise limits of the 264 matched instruction traces.

Final runtime: `e904cd285`, binary SHA-256 `1c808efda63159b31e45e7e960053052b8ac6cd3345049dc23e857bd3da845cc`, frozen as `build/txnfix3/post-final4/tomokv`.

| Result | Final evidence |
|---|---|
| Required directed data checks | txniso 8/8; EXEC NX 0/8192 in every cell; original EXEC 28/28; Stage B 20/20; all group and mover configurations pass |
| Sensitive controls | Fresh PRE G5 duplicate delivery in both modes; barrier-removed witness fails 4/4; both admission controls fail their intended assertions |
| Broader proof | Redis 112 legs + two witnesses; companions 15/15; WATCH 60 fresh boots; gates_test 66/66 |
| Remaining broad failures | 36/38 pass; fused expected-old MGET and SIGABRT resize failures both reproduce on PRE and remain unfixed |
| Static identity | selected hot 1208/1208; lbstall 601/601 + 603/603; layouts and existing TLS preserved |
| Remaining acceptance work | Universal ordinary-path instruction proof; full layout twin if required for the combined branch; owner quiet-box null and existing baseline failure decisions |

The exclusive fallback stays in separate `e1609593d`. No gate-count constant was edited; txnfix3 DQ/DF are 0/0, and the whole branch is +10/+10 (owner counts 635/652). No performance workload, full gate or push ran. All proof CPUs stayed within 112–127.
'''
(root/'README.md').write_text(readme)
for name in ('summarize-final4.py','final4-controls.py','document-handoff-final4.py'):
 shutil.copy2(Path('build/txnfix3')/name,root/'proof-drivers'/name)
