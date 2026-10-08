# mkprobe2 — fixed-split diagnostic telemetry contract

Branch `cx-mkprobe`. Code commit `2c78708f8ef94704e88b878f3fe8a7e8e235a829`. Gate rows **+0/+0**. No performance claim.

Both requested synchronizations ran `git fetch origin && git merge origin/cpp`; both were already up to date at `9b3cab67ba16d12a282a126dc822c953db20fa6a`. The second merge preceded the final self-test, all nine dry runs and the frozen argv proof below.

The only executable source change is `tools/mkprobe_probe.py`: `telemetry`, `report`, `self_test`, and the shared NA reason constant. `src/`, `tests/`, the cell recipes, `tests/gate.sh`, `EXPECT_QUICK` and `EXPECT_FULL` have no diff against merged mainline. No rows were added or removed on either side of the quick-tier exit; both expected counts stay unchanged. No build or production change was needed.

## Contract before / after

This resolves the observation conflict in `MEASURE-REQUEST-mkprobe.md`. The authoritative flag is **INFO `flip_auto`**, emitted by `src/cmd/t_server.cc:2108` using `g_server->flipctl_enabled()` at line 2113. `src/core/server.h:507` delegates that to `FlipController::enabled()`. It is the reported live enabled state, not an inference from `1s`/`2s` or the launch argv. The separate `flipctl_state` field is emitted at `src/cmd/t_server.cc:2178`; the probe uses the boolean enabled flag. Native queue/age counters are emitted at `src/cmd/lbsignals.cc:290`.

| INFO / telemetry case | Before | After |
|---|---|---|
| 1s | Age/delay `not available` | Unchanged |
| 2s, `flip_auto=0`, zero or stale samples | Required executor sample progress and positive values; FAILED | `not available: flipctl disarmed (flip-auto 0)`; otherwise valid sample remains COMPLETE |
| 2s, `flip_auto=1`, both executor counts advance and both values are positive | Accepted, with existing 60-second value bound | Unchanged |
| 2s, `flip_auto=1`, either count zero/stale or either measured value zero | FAILED | FAILED; each negative is covered independently |
| 2s, missing/invalid/changing `flip_auto` during observation | State was ignored | FAILED; unknown state cannot excuse a silent zero |

The exact disarmed reason replaces the four `lb_io_*` / `lb_ex_*` queue-delay and oldest-age value columns and the two existing executor sample-delta columns. The row also retains the observed `flip_auto` value. Masked-lane counters, atomic counters and native role names keep their existing contract. Both generated `report.md` and `report.json` include the reason and the armed/disarmed rule. Age/delay columns remain diagnostic: M1–M5 do not read them. The recipes still use `--flip-auto 0`; no flip-enabled pass was added or run.

## Final self-test

Run on CPUs 112–127 after the final merge; exit 0. The external collection is mocked for the new row fixture, while the real telemetry, row-completion, durable-row and report paths run. It asserts a COMPLETE disarmed 2s row with the exact reason and checks the reason in both report formats. Armed fixtures reject zero/stale counts and zero values. Synthetic fixtures are not measurement evidence.

```sh
taskset -c 112-127 python3 tools/mkprobe_probe.py --binary build/mkprobe-server --cores 112-119,120-127 --self-test
```

```json
{
  "status": "PASS",
  "checks": [
    "canonical recipes and 14-cell null",
    "all headline/mkprobe complete argv byte-identity plus 14 override round trips",
    "invalid key counts fail",
    "PMU partial, multiplexed, missing, duplicate and unavailable negative controls",
    "cycles/op, instructions/op, IPC and cycles/key independent arithmetic",
    "shutdown accounting and duplicate report negatives",
    "armed INFO flip_auto=1: advancing positive samples pass; zero/stale counts and zero values fail",
    "disarmed INFO flip_auto=0: NA with reason; missing/invalid/changing state fails",
    "1s unavailable and missing-counter negatives",
    "weighted symbol shares and lost-sample negative",
    "all eight collection-mode matrices and ABBA per-arm n=6",
    "null arithmetic rejects 1% delta and n=5; empty campaign unresolved",
    "M1/M3/M5 positive signatures, deliberately broken mechanisms, missing variants and unavailable attribution",
    "resume serialization identity and changed-geometry negative control",
    "owned child process-group stop and reap (CPU112, no listener)",
    "quiet refusal retained without starting a server",
    "disarmed 2s fixture: COMPLETE row and Markdown/JSON reports retain NA reason (no server)"
  ],
  "server_started": false
}
```

## Dry-run receipts and frozen argv

All nine modes exited 0. Each command used `taskset -c 112-127 python3 tools/mkprobe_probe.py --binary build/mkprobe-server --cores 112-119,120-127 --mode MODE --dry-run --output build/mkprobe2-dry-MODE`. Report additionally used `--inputs build/mkprobe2-smoke`. These are serverless plans; printed mainline argv do not schedule work on those CPUs. Collection-mode plans also checked memtier help grammar.

| Mode | Planned rows | Exit | UTC start | Log SHA256 |
|---|---:|---:|---|---|
| null | 168 | 0 | 2026-10-08T03:49:27.356917+00:00 | `435abfb9100171d643c214a5169d6df6001d8760e69a1baa52339cba76a7851e` |
| probes | 114 | 0 | 2026-10-08T03:49:28.643733+00:00 | `6ae057f731fe554c0495d629e401f072a31e707ae69408ee9c53ea24123e414f` |
| counters | 114 | 0 | 2026-10-08T03:49:29.933090+00:00 | `cc2df5d5cf26c867530347bd8f43c8d101f47f25b0254fac77a2899ddb7653c0` |
| coherence | 114 | 0 | 2026-10-08T03:49:31.215145+00:00 | `257020d3268a2d4d1ce0a93141638ce4214b3fc09fa4f6b4abe18a3259192c59` |
| wb-pair | 96 | 0 | 2026-10-08T03:49:32.489669+00:00 | `98597dae1f4f34f903a6c5668f6220a0498a74afd6a3c2c5103ade0c5b1e3ab3` |
| keys | 168 | 0 | 2026-10-08T03:49:33.754827+00:00 | `f6957c78b7e0dbfef4cce74e4814321eee0e19a3e4f9a096508c1ce50c2bb67c` |
| symbols | 114 | 0 | 2026-10-08T03:49:35.026211+00:00 | `276af27fbb0aaac817241529446c93a54d7ea9b26ae8724e84c2bdf4dd331b35` |
| smoke | 2 | 0 | 2026-10-08T03:49:36.312833+00:00 | `3f8412cfc6704a76749658d6238efe36c80bf4f31759f738019d7a70f88d841e` |
| report | 0 | 0 | 2026-10-08T03:49:37.557955+00:00 | `42bf971a18a2fb24b1bedec168eff62b0803c9502d283bb83507fffe361378f0` |

The byte-identity proof still passes **1,656 complete execve argv vectors**, covering all 181 frozen headline cells and all 19 probe cells. UTF-8 arguments are separated and terminated with NUL. All seven key-count overrides round-trip for MGET and MSET, and the unset default is restored.

```
headline SHA256:       d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350
frozen workload SHA:   0060d75451b97c4274600eefcd8c950e0683359b31df910233d5e60765e15ce9
both argv streams SHA: e90f50fe6363bf7d44a3b7eb168641736ad3e6c6f9f0e6fe9c3d63b3b4c5facc
probe source SHA256:   0f0706a06cda804e4cd4cc2000ff84a0806c6f80a661a220579c795b0018b537
```

## Text audit

Used `grep`, never `rg`, throughout. The audit covered underscore, space and hyphen encodings of queue delay / oldest age, age/delay prose, fixed-split failure prose, sampler checks, flip_auto and the disarmed reason in `tests/` and `tools/`. The final audit has 218 matching lines (191 in merged mainline with the same pattern). The removed “Fixed-split campaign blocker” text has zero matches there. The other occurrences describe native telemetry fields, flip-enabled correctness tests, or fixed-split recipes and need no edits. The exact matched lines are retained in `build/mkprobe2-proof/text-encodings-{before,after}.log`.

An AST comparison against merged mainline confirms that only `telemetry`, `report` and `self_test` changed among functions/classes; verdicts, job matrices, server argv, PMU collection, quiet preflight and retry policy are unchanged. `build/mkprobe2-proof/scope-proof.json` records the zero production/test diff and +0/+0 rows.

## Smoke

**Smoke exited 1; zero COMPLETE samples.** m02 was refused three times over 10 minutes (614.12 seconds between first and third starts), before any server or load generator was started. p8g passed the quiet preflight and ran, then failed the unchanged `<98%` generator CPU-headroom requirement. This is a recorded smoke failure, not a passed smoke or a telemetry-contract failure.

| Cell | Attempt UTC (2026-10-08) | Selected CPU seconds at preflight end/refusal | Budget | Outcome | Owned children started / reaped |
|---|---|---:|---:|---|---|
| m02 | 03:49:53 | 0.96 | 0.48 | quiet refusal | 0 / 0 |
| m02 | 03:54:56 | 1.17 | 0.48 | quiet refusal | 0 / 0 |
| m02 | 04:00:07 | 1.17 | 0.48 | quiet refusal | 0 / 0 |
| p8g | 04:00:18 | 0.39 | 0.48 | admitted; generator CPU headroom FAILED | 12 / 12 |

The quiet allowance is for a 20-second preflight; the existing monitor refuses early when the cumulative budget is exceeded. No tolerance, affinity, recipe, retry policy or load-generator headroom check was changed.

p8g generator CPU percentages per configured worker were `98.34072, 98.69079, 97.74091, 97.74088, 97.74089, 98.44084, 98.74085, 95.29122`. Workers 0, 1, 5 and 6 exceeded the strict 98% limit. Its partial `core/pass.json` retains those raw endpoint measurements and the 1s telemetry. The owned setup/measured servers exited 0; perf and load processes were stopped and reaped on the failure. All 12 owned children have recorded exit statuses. The harness retries quiet refusals only, so p8g was not rerun after this failure.

Final smoke row status/error columns (full `MKPROBE_ROW` objects are in `build/mkprobe2-proof/smoke.log` and the archive):

```json
[
  {
    "cell": "m02",
    "status": "FAILED",
    "quiet_refusal": true,
    "rate": "not available",
    "instr_per_op": "not available",
    "ipc": "not available",
    "cyc_per_op": "not available",
    "error": "QuietViolation: QUIET-BOX PRECONDITION FAILED: selected-core CPU screening budget exceeded: 1.170000s > 0.480000s per 20s"
  },
  {
    "cell": "p8g",
    "status": "FAILED",
    "quiet_refusal": false,
    "rate": "not available",
    "instr_per_op": "not available",
    "ipc": "not available",
    "cyc_per_op": "not available",
    "error": "RuntimeError: load generator has no CPU headroom"
  }
]
```

Mainline still needs a successful smoke on its scheduled box. No valid live sample or performance result is claimed here. M1–M5 remain UNRESOLVED. The row receipt binds the same instrument SHA as the final proofs.

```sh
taskset -c 112-127 python3 tools/mkprobe_probe.py --mode smoke --cells m02,p8g --binary build/mkprobe-server --cores 112-119,120-127 --quiet-retries 3 --retry-seconds 300 --output build/mkprobe2-smoke
```

The private binary copy came from `/home/user/Projects/cx-final/build/tomokv`, with matching source/copy SHA256 `f2d62135aa03585ea847457f1fd202b66c108c93084d357095164256a39f20d5`. No compiler was launched. The unchanged quiet preflight must admit a sample before any server or load generator starts. The smoke cells are 1s; the new 2s branch is covered by the serverless fixtures, not a separate live telemetry pass.

## Evidence

`build/mkprobe2-proof/` retains the complete self-test output, full printed dry-run argv, `dry-runs.json`, `default-argv.json`, `final-proof.json`, `scope-proof.json`, grep audit and smoke log. `build/mkprobe2-smoke/` retains the bound receipt and every attempt. The committed portable archive `docs/mkprobe/mkprobe2-proofs.tar.gz` contains 59 evidence files plus an internal SHA256 manifest; every member was read back and verified. It includes all raw smoke logs/INFO/perf CSV/CPU endpoint receipts, both final failed rows, all four attempt records, final generated reports and all final serverless proofs. The executable and snapshot data remain in build/. Archive SHA256: `9818cb9a6a7d5b1cd0a0c7d0474b2508e520553180998e66cff132593c8f6f4e`.
