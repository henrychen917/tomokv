---
name: user-autonomy-no-permission-asks
description: "How the user wants me to work — full autonomy, don't ask permission for investigative/build/bench steps"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

User runs in **bypass-permissions mode** and wants full autonomy. Do NOT ask "want me to…?" / for permission before investigative, build, benchmark, config, or fix steps — just DO them and report results. Asking wastes a round-trip and annoys them.

**Why:** they've explicitly granted autonomy; the harness won't prompt them anyway. The only genuine blocker is the **OS sudo password** (can't be supplied non-interactively — `sudo -n` fails), so flag *that* and let them run it; everything else, just proceed.

**How to apply:** end turns with results + next action taken, not with permission questions. Reserve questions for genuine product decisions the user alone can make (per AskUserQuestion), not for "should I run this benchmark/build."
