# Wave 4 landing request

## wave4 integration

Lane wave4b resumes clean branch `cx-wave4` at `cd1423c97`. The four no-ff
merges are `2d276e45c` (compat2), `8bce7c3da` (moverfix), `4c692daf4`
(clockcut), and `7c054dbad` (notifyorder), on headline `8656f9fa9`.
`0350c7b33` retains the three clockcut labels. No push is requested.

The maintainer's compat2 EXPECT update and fixture sync remain intact.
DQ=DF=+16 (+3 compat2, +8 moverfix, +3 clockcut, +2 notifyorder), all collected
before the quick exit. Required landing counts are **685/702** from headline
669/686. Current constants remain **672/689**; this lane does not edit them.

Correctness uses CPUs 64–111 only and ports 26800–26899. Performance benchmarks,
measurement load generators and the full iteration gate remain with the maintainer.

### Oracle and sweep

`docs/wave4/oracle/auth-redis74.json` identifies Redis 7.4.10 (`f103d127`) and
records pre-AUTH `XGROUP x` as `ERR unknown subcommand 'x'. Try XGROUP HELP.`.
`acl-redis74.json` records `NOPERM User alice has no permissions to run the
'acl|whoami' command`. The corresponding TomoKV auth and atomic-0/atomic-1 ACL
receipts agree. Thus the retained evidence covers all three corrected rows in
`cd1423c97`, not just one ACL mode. No further assertion change is assumed.

The initial whole-test-tree textual sweep is retained in `docs/wave4/sweep-hits.json`.
Final job coverage, interaction findings, identity trials and proof outcomes
will be appended here after execution.

### Scope of existing findings

The moverfix lane's broader concurrent EXEC conservation counterexample failed
both headline and isolated POST. Its atomic-0 claim protocol does not establish
EXEC conservation; passing the standard MULTI/EXEC battery cannot erase that
reported counterexample. This integration does not silently broaden the claim.
