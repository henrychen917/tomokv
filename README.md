# Tomo KV — dev session backup

Off-server snapshot (no physical access to the bench box). Orphan branch of `tomokv`.

## Contents
- `transcript/session_transcript.jsonl.gz` — full Claude Code session transcript (gzip; ~80MB raw).
- `bench-data/` — sweep results + logs: `master.tsv` (config×cell×rep sweep: io4ex4/io2ex6/io6ex2/io5ex3/io3ex5 + redis + dragonfly, dispatch/DRAM/compute cells), `master.log`, `master2.log`, phase logs, plus earlier `*.tsv` / `*.log`.
- `tools/` — all bench harnesses (master_sweep, ab, qb, phase1_decref, resilient/showcase/regime scripts, etc.).
- `memory/` — the assistant's persistent memory files (project state, findings, doctrines).

## Related dev branches on `tomokv` (this repo)
- `stable` — Tomo KV 2-Stage (shipped; pwait2 + idiv caches + config gates).
- `3-stage` — Tomo KV 3-Stage.
- `2s-decref-bounce-dev` — released-operand-bit decref-bounce fix (ASAN-validated, FLAT on 1-CCD, parked for multi-CCD/Threadripper; NOT merged).
- `2s-command-interning-dev` — argv[0] command-name interning (implemented; build+ASAN+A/B pending; NOT merged).

## Key session findings (see memory/ + transcript)
- Decref-bounce: fix correct + validated, flat on 1-CCD (cross-core cheap on shared L3), re-eval on multi-CCD.
- Configurable ingress/execution split is the core tunability thesis; moderate splits (io5ex3/io4ex4/io3ex5) preferred on 8 cores.
- Build-trap lessons: always verify jemalloc (not libc), no `-fsanitize` in .make-settings, distinct md5, .text ~4.36MB, sane number range — three build artifacts (libc/identical/ASAN) each produced garbage numbers.
