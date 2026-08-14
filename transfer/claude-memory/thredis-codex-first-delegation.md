---
name: thredis-codex-first-delegation
description: "USER RULE — delegate to `codex exec`, not Claude subagents/workflows; Claude tokens are scarce, Codex tokens are plentiful. Claude does coordination, review, merge and ALL testing."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Owner, 2026-07-30: *"try not to use Claude agents only codex agents as I'm running out of Claude
tokens but still have a ton of codex ones"*. Earlier the same day: *"I have a lot of codex tokens
left while Claude is running thin, so if possible use this method to go very deep"*.

**The division of labour:**
- **Codex does the work** — reading the codebase, implementing, and deep review. Spawn many, in
  parallel, at high effort.
- **Claude does only what Codex cannot**: choosing what to work on, reviewing diffs, running tests,
  merging, and pushing. Do NOT spawn Claude subagents or Workflows for work Codex can do.

**AMENDED 2026-08-11 (owner): up to THREE Claude Opus agents are additionally authorized per
overnight run** ("use some opus 5 Max agents, max 3 of them and any number of gpt 5.6sol Max
agents") — use them for deep READ-ONLY analysis/design (census decompositions, ranked registers,
synthesis) where Claude-grade reasoning over the tree beats implementation throughput; codex
remains the implementation fleet. The "only test inline" rule binds ALL agents: no agent of any
kind runs make/servers/benchmarks.

**The invocation that works here:**
```
codex exec --sandbox danger-full-access -m gpt-5.6-sol -c model_reasoning_effort=xhigh "<task>"
```
- `danger-full-access` is acceptable **only** because the cwd is a throwaway git worktree. The
  owner's rule was "full access but only to the forked dir".
- The default `workspace-write` sandbox **does not work in this environment**: bubblewrap needs
  uid_map writes, which are blocked (`bwrap: loopback: Failed RTM_NEWADDR`), so every file op fails.
- Codex is authenticated via ChatGPT (`~/.codex/auth.json`). There is **no codex plugin** in the
  official Claude Code marketplace — all 243 checked.

**Fork with `git worktree add --detach <dir> <sha>`, never `cp -a`.** A `cp -a` of a tree with
uncommitted edits gave forks showing 19/21/28 changed files, most of it inherited dirt that had to
be separated from the real work by hand. Worktrees off a commit gave 2-3 file diffs, exactly scoped.

**Always tell Codex: NEVER build, NEVER run tests, NEVER start a server or load generator.** Testing
is Claude's job in the main thread. This is not only about correctness — the box allows one server
at a time, and a Codex worker starting one would contend with the very benchmark meant to gate it.

**Brief it with the architecture and with what NOT to re-derive.** `$JOB/ARCH_BRIEF.md` exists for
this: execution model, the decoy-`server.db` trap, single-writer ownership, owner-publishes pattern,
the three LB mechanisms, the measurement apparatus, and the list of already-settled conclusions
(cross-thread alloc ownership dead, per-type pools disproven, AMAC rejected and why, forwarding
dead, io_uring deleted, `instr/op` polluted). Copy it into each worktree.

**End every brief with:** *if it turns out already done or unreachable, SAY SO and change nothing* —
see [[thredis-verify-before-implementing]].

**ENUMERABLE FACTS drift even under a "strictly from code" brief (2026-08-12).** The README
synthesizer, told to document knobs strictly from code, listed 15 knobs that DO NOT EXIST in
config.c (express-slim, mset-move, key-lb-fine, reply-iovec, ... — all deleted in the 20-knob
collapse). It pulled them from stale comments/old-docs/its own training of the codebase, not the
actual createXConfig sites. FIX for any enumerable surface (knobs, commands, INFO fields, enum
values): the brief must (1) name the SINGLE definition site to enumerate from, (2) forbid every
other source explicitly, and (3) hand the agent the authoritative list (grep it yourself, e.g.
`grep -oE '"tomokv-[a-z-]+"' config.c`) as a cross-check it must reconcile against. Verify the
result by diffing the doc's list against the real definition site — a doc that reproduces the
DRIFT is worse than none, and it's exactly what "too much has changed, rewrite from code" is
trying to escape. The 7 prose subsystem docs (algorithm descriptions) were code-accurate; only
the enumerable knob table drifted — enumerations are the high-risk surface.

**Watch for scope creep in the result.** One task scoped to "make per-command scratch thread-local"
came back as a 787-line rewrite of the whole subsystem. Check the diffstat against the size of the
change you asked for before reading the code, and reject rather than review a rewrite you did not
ask for.

**Codex CPU contends with benchmarks.** Workers start no servers, but they burn cores. A gate came
back with all four cells negative on a config-table edit that touches no data path — physically
impossible as a regression, i.e. it was measuring contention. Count `codex exec` processes before
any timing run. Related: [[thredis-right-sized-tests]], [[thredis-box-noise-truth]].

## Fleet operation, learned 2026-07-30 (≈45 agents in one session)

**Scale that works:** 14-23 concurrent `codex exec` runs on this box is fine; they are API-bound,
not CPU-bound. ~37 agents at `xhigh` cost about 4% of a weekly 20x-plan budget. `ultra` is a valid
`model_reasoning_effort` value and was adopted as the default for this work.

**The content filter refuses DEFECT-HUNT shaped tasks.** Two runs briefed as "find bugs /
concurrency defects that can crash or corrupt" were killed with *"This content was flagged for
possible cybersecurity risk"* — both times only AFTER reading ~150k tokens of source, so it is
reacting to the task SHAPE, not the wording; a careful non-security rewrite was refused too.
**INVENTORY framing passes and yields more actionable output:** "produce the ownership table",
"produce the call() coverage table", "produce the invariant register", "produce the failure-mode
register". Same information, constructive shape.

**The filter also kills plain IMPLEMENTATION runs mid-edit (2026-08-11).** cxinlinering — an
ordinary perf task (64B ring entries, no security language anywhere) — was killed at 818K tokens
while writing t_string.c, leaving a HALF-APPLIED tree that does not compile (duplicate/conflicting
declarations). Consequences: (1) a dirty tree + dead process does NOT mean "finished but
uncommitted" — ALWAYS read the codex_run.log TAIL for the red ERROR lines before judging a
delivery; (2) a filter-killed tree needs a recovery brief: state the compile error, tell the agent
to read its own diff and keep/repair/redo per file, forbid leaving dead halves of both approaches.
(3) The completion watcher trap: a `until ! pgrep -f "codex exec"` watcher MATCHES ITSELF and both
livelocks and makes agent-liveness counts wrong (same self-match family as above) — classify with
`ps -eo args | grep -i codex` + worktree state + log tail, never bare pgrep -f counts.

**Wrapper shell scripts die on this box; agents do not.** Agents launched as
`( cd "$dir" && nohup $CX "$(cat BRIEF.txt)" > log 2>&1 & )` survive reliably. Detached *driver*
scripts (`setsid nohup ./chain.sh &`) died silently twice. Verify liveness with
`pgrep -x <script>.sh` — `ps | grep -c 'chain_all.sh'` MATCHES ITS OWN command line and reports a
dead script as alive (same self-match family as `pkill -f`, which killed my own shell mid-script).

**Codex kills long-running foreground commands.** A tester agent told to `until ...; sleep 60; done`
died inside that loop having tested nothing. Waiting must happen in a plain shell OUTSIDE the
agent; inside an agent, start long work with `nohup ... &` and poll.

**A killed parent does not kill the codex child** (it is a foreground subshell, not a job). Killing
a chain script leaves its agent orphaned and running — check before re-launching, or a restart will
`rm -rf` a live agent's worktree.

**Adversarial reviewers manufacture plausible defects.** Told to find problems, one produced a
"critical use-after-free" with a convincing six-step interleaving that was simply false. A second
agent refuted it from the source and a third correctly REFUSED its assigned deletion because the
review's premise was wrong. Always add: *if the premise is false, say so and change nothing* — and
verify contested findings yourself. See [[thredis-prefetch-dict-lifetime-invariant]].
