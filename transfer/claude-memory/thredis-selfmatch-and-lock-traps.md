---
name: thredis-selfmatch-and-lock-traps
description: "Harness traps that voided four runs in one session: pgrep/ps -f self-matching the pattern in my own command line, `cd X && … &` backgrounding the whole chain, a leaked server holding the suite's flock fd, and reading a PREVIOUS arm's log after the current one never ran"
metadata:
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-04. Four distinct harness traps, each of which produced a CONFIDENT WRONG RESULT rather
than an error. Every one cost a full run or a false finding.

## 1. `pgrep -f` / `ps | grep` self-matches (hit THREE times in one session)

`pgrep -f 'p32curve.sh'`, `ps -eo args | grep -qF 'controller_sweep.sh'` — the pattern is present
in the command line of the shell RUNNING the check, so it always matches itself. Symptoms: a
"box busy" guard that never lets anything start, or a kill loop that reports survivors forever.

**Use instead:** `fuser <lockfile>` (authoritative — catches a live suite AND a leaked server), or
exact-comm matching `ps -eo pid,comm --no-headers | awk '$2=="redis-sat"{print $1}'`.
NOTE `pgrep -x` cannot match `memtier_benchmark`: comm truncates at 15 chars.

**`pkill -f` is worse than `pgrep -f` — it SIGKILLs the self-match.** 2026-08-13 this hit ~4× and
each time produced empty output + a shell exit code of 144 (128+SIGKILL-ish), never an error I could
read. Two forms: (a) an INLINE `pkill -9 -f "redis-server .*:$PORT"` whose pattern text sits in the
same command line → kills my own tool shell; (b) subtler — a `pkill -f node_load` INSIDE a script
file, launched via a heredoc `cat > f.sh <<'S' … S; bash f.sh`, where the heredoc BODY (containing
`pkill -f node_load`) is embedded in the LAUNCHER bash's argv → the script's pkill matches and kills
its own parent launcher (the script keeps running orphaned, so the box looks "still busy" after the
task reports failed). **In harness cleanup use comm-exact `pkill -x redis-server` / `pkill -x
python3`, or iterate `pgrep -x python3` PIDs and grep each `/proc/$p/cmdline` (never pkill -f a
pattern that could appear in any ancestor's command line).**

## 2. `cd X && ... && cmd &` backgrounds the WHOLE chain (hit twice)

The `&` binds to the entire `&&` list, so the `cd` happens in a subshell and `$!` is the SUBSHELL's
pid, not the command's. Consequences seen: `kill $!` killed the subshell while the server was
reparented to init (four orphans at ppid=1), and every later line in the same call ran from the
ORIGINAL cwd, so a relative `../mergew/src/redis-cli` silently did not exist. That last one made me
conclude "the INFO fields are absent from the binary" — for several turns — when the CLI was simply
missing. **Always absolute paths in harnesses; never `cd && … &`.**

## 3. A leaked server holds the suite's flock

The server inherits the lock fd from its parent shell, so `csweep/.lock` stays held for as long as
the leaked server lives, and the NEXT run dies with "another controller_sweep holds .lock" when no
sweep is running. Root cause was my own new cell doing `boot ... || break` with no `stopsrv` on the
failure path. **Every exit path out of a cell must drop the server.**

## 4. A voided run inherits its predecessor's evidence

Arm K never ran (lock), but the harness still `cp`'d `csweep/logs/flip_auto.srv.log` into
`K.flipctl.log` — arm J's log — and I reported "13 NaN anchors" from it as if it were K's. Caught
only by checking the mtime. **Delete the output artefacts BEFORE a run**, so a run that does not
execute produces nothing rather than the previous run's answer. Same class as
[[thredis-vacuous-validation-trap]]: the artefact existed, so the check "passed".

## The pattern

None of these threw an error. Each produced a plausible number or a plausible refusal, and three of
them nearly became findings I would have reported. The rule that catches all four: **before
believing any harness output, prove the run actually executed** — check mtimes, check exit codes,
check that the guard that fired was matching something other than itself.

Related: [[thredis-ab-harness-traps]], [[thredis-vacuous-validation-trap]],
[[thredis-sanity-gate-benching]].
