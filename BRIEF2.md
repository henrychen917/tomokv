# ROUND 2: recover and complete the inline-command-ring work

The previous run on this worktree ended abruptly partway through applying edits. The tree is
now in a PARTIAL state and does not compile:

    server.c:8963: error: conflicting types for 'xxh64'

Your job: make this worktree a complete, coherent, compiling implementation of the ORIGINAL
BRIEF.md (still in the worktree root — read it first), reusing as much of the existing dirty
work as is sound.

Method:
1. Read BRIEF.md (the original task) and the current diff (git diff) in full.
2. For each touched file (src/db.c, src/networking.c, src/server.c, src/server.h,
   src/t_string.c), decide: keep the applied hunks, repair them, or redo that file's part of
   the design from scratch. The half-applied state may include duplicated declarations
   (the xxh64 conflict suggests a helper was declared twice or with two signatures) and
   hunks whose counterparts in other files were never applied.
3. Finish the remaining parts of BRIEF.md.
4. The result must be self-consistent: every new function declared once, every caller matching
   its signature, every new struct field initialized where client/ring state is created and
   reset. Do NOT leave dead halves of abandoned approaches in place.

Constraints (unchanged from round 1):
- WRITE CODE ONLY. Never run make/compile/servers/benchmarks. I do all building and testing.
- Keep the existing engagement-witness discipline: any new fast path must expose an INFO
  counter proving it fired.
- notifyguard.sh in the repo root encodes layout invariants (cache-line isolation, byte
  atomics, ring head/tail split). Your changes must keep all 11 checks passing honestly.
- Commit when done with clear messages; leave the tree clean (no uncommitted files).
