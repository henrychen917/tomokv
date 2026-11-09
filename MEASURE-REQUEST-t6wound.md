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

Validation complete on final harness `b5ca96b58a`:

- Build: `LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
  taskset -c 52-63 make -j12 all` passed.
- `/home/user/Projects/calib/binary-neutral.sh
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv`:
  `IDENTICAL (11167504 bytes after stripping)`.
- `python3 tests/gate_ledger_fixture.py --self-test`: 12 tests passed.
- `python3 tests/gates_test.py`: 83 tests passed.
- Unchanged-harness baseline: all 27 legs passed, with 0/24 TomoKV misses.
- Five complete `at412-T6` gate jobs passed on the release reference and five
  on `build/tomokv`: 270 total legs including Redis, 240 TomoKV attempts,
  zero wound misses, zero re-rolls, and zero row failures. Every TomoKV leg
  reported exactly one wound during the directed opening.
- Each row took 813.10-813.34 seconds, below its unchanged 2400-second budget.
  All 270 server boots used the assigned CPUs/ports and exited with status 0
  without forced termination. No listeners remain on ports 26700-26799.
- The final 27-leg short smoke matrix and the three-leg FLIP smoke passed.

The before counts below exclude the three Redis oracle legs. The supplied
logs contain 33 and 32 TomoKV attempts, confirmed independently by their
geometry records. A final failed attempt is already in `unarmed_attempts`;
adding another attempt for that failed leg would double count it.

| Evidence | Wound misses / attempts | Failed legs | Failed rows |
| --- | ---: | ---: | ---: |
| Supplied p2 log | 12/33 (36.36%) | 3/24 | 1/1 |
| Supplied aofblock log | 10/32 (31.25%) | 2/24 | 1/1 |
| Fresh release baseline, original harness | 0/24 (0%) | 0/24 | 0/1 |
| Final harness, release reference | 0/120 (0%) | 0/120 | 0/5 |
| Final harness, local build | 0/120 (0%) | 0/120 | 0/5 |

[Raw logs, results, boot commands, and counter checks](docs/t6wound/evidence/)
are retained with binary and harness SHA-256s in `summary.json`.
The final runs are repetitions 2-6 for each binary. The earlier pilot row on
each binary also passed, but is excluded because it predates the final
controller change that keeps PING active throughout the opening.

Failure controls on the final harness:

- Both thread modes reject a masked zero `atomic_group_wounds` counter after
  running the ordinary counts, exact-value, and worker checks. PRE refusal
  controls still pass with that zero counter and reject any attempted DEBUG
  command through a client wrapper, confirming that no hook is armed there.
- Suppressing `TXN-PLACE-DEFER` makes the directed opening fail all three
  fresh boots. The T6 result is a failure and all four boots (including Redis)
  exit cleanly. This tests that natural later wounds cannot rescue an unopened
  directed schedule.
- Injected assertion failures and timeouts are not retried; an injected
  WoundNotObserved is retried only on three distinct fresh directories and
  still fails. See `final-controls.log` and `retry-controls.log`.
- An AST comparison preserves all 16 original storm assert statements and
  every function other than `storm()`. Three scheduling assertions are added.
  `src/`, `tests/gate.sh`, and its row inventory are unchanged.

The acceptance runs used the following gate job commands, five times per
binary, with `GATE_LEDGER` set to the corresponding
`build/t6wound/after-{release,build}-{2..6}.ledger` path. The two arms ran
concurrently on disjoint resources; repetitions within each arm were serial.

```sh
export LC_ALL=C GATE_ONLY_JOBS=at412-T6 GATE_PROOF_NO_RATES=1
taskset -c 40-51 tests/gate.sh quick \
  --server-cores 40-47 --load-cores 48-51 --ports 26700-26709 \
  --candidate-binary /home/user/Projects/bins/readability-pre-5c363128/tomokv
taskset -c 52-63 tests/gate.sh quick \
  --server-cores 52-59 --load-cores 60-63 --ports 26710-26719 \
  --candidate-binary "$PWD/build/tomokv"
```

Each invocation retained the default 30-second storms and complete matrix:
EVAL/EVALSHA/FCALL x 1s/2s x atomic 0/1 x uring/epoll, plus the three Redis
oracle legs. Servers use eight CPUs and 16 shards, with split ratio 6:2.
Every server boot inherited `LC_ALL=C`. The harness unit/fixture commands and
diagnostic controls were pinned to CPUs 60-63; diagnostic servers used 52-59
and ports 26710/26711 or 26720/26721. These are correctness jobs only; no full
iteration, benchmarks, or push were performed.
