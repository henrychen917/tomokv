The run manifest records every invocation, including controls and harness failures.
Runtime binary SHA256: `876db2f6b7421cbc0f79966bc65fac39348da561ed68e58b8f0071707bd64ada`.

The standalone `G5-2s-a0` and `G5-1s-a0` invocations booted with atomic 0.
`txngroup.py` requires atomic 1 at boot and changes to atomic 0 inside G5, so
those two invocations failed their boot precondition and are invalid as data
checks. They remain in the manifest. All four full txngroup batteries include
valid passing G5 checks. `../final-controls/` also retains corrected standalone
G5 invocations with atomic 1 at boot and atomic 0 inside the test.

PRE original-audit and txniso failures are deliberate negative controls.
POST fused `execatomic` and `atomic_torn` failures remain failures; fresh PRE
controls in `../final-controls/` reproduce the expected-old MGET assertion and
the armed read-local resize abort. No assertion was weakened. Ledger checks
fail solely because the protected EXPECT_FULL remains 642 while both the source
and explicit fixture contain 652 rows.
