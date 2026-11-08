## t6wound

Harness-only change on `cx-t6wound`, based on `7595a6705a`. No server sources,
gate labels, budgets, or EXPECT constants change. Count delta: quick 0, full 0;
`at412 T6` remains its existing row before the quick-tier exit. No push.

T6 opens with the first operations of its existing EXEC worker 8, script worker
0, and plain writer 17. Existing DEBUG controls defer the older EXEC's second
key placement for two seconds and the younger script's read for 500 ms. After
the script chooses its read cut, the writer increments the second key. Forced
escalation makes the younger script hold that key while waiting on the EXEC's
first key; the older EXEC then wounds it. All three operations count through
the existing worker attempts, successes, and final exact-value assertion.

All DEBUG controls are disarmed before the remaining storm traffic starts.
The opening consumes the existing 30-second interval, not extra storm time.
The controller keeps checking PING during the opening.
Both the original final wound guard and an additional directed-opening guard
must pass; only WoundNotObserved gets the existing three fresh boots. Other
assertions and the worker mix are unchanged. Oracle, PRE refusal controls,
FLIP, BGSAVE, and diagnostic mixes do not arm the opening. BGSAVE still runs through
the same storm controller and retains its assertions.

The existing production controls suffice. The copy-only wound seams in
`tools/woundfix_windows.py` and the serverless `tests/at412_owner.cc` fixture
are not required, and no test hook is added to any binary.

Validation in progress:

- Build: `LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
  taskset -c 52-63 make -j12 all` passed.
- `/home/user/Projects/calib/binary-neutral.sh
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv`:
  `IDENTICAL (11167504 bytes after stripping)`.
- The directed opening alone produced exactly one wound in all eight
  mode/engine/atomic combinations on the release binary.
- `python3 tests/gate_ledger_fixture.py --self-test`: 12 tests passed.
- `python3 tests/gates_test.py`: 83 tests passed.
- Unchanged-harness baseline: all 27 legs passed, with 0/24 TomoKV misses.
- Full repetitions of the final harness are pending; final evidence and miss
  rates will be recorded here.

The acceptance run uses `GATE_ONLY_JOBS=at412-T6 GATE_PROOF_NO_RATES=1
tests/gate.sh quick`, with explicit candidate binaries and disjoint resources:
release on server CPUs 40-47 / load 48-51 / ports 26700-26709, local build on
server CPUs 52-59 / load 60-63 / ports 26710-26719. Run five complete rows per
binary with the default 30-second storms and full 27-leg matrix. Required:
zero row failures, zero directed-opening misses, all existing assertions pass,
each row below its unchanged 2400-second budget. Every invocation uses
`LC_ALL=C`. These are correctness jobs only; no full iteration or benchmarks.
