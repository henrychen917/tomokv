#!/bin/bash
# Build both arms from ONE tree, so the only difference between them is this lane's header.
#
# src/net/rob.h is the lane's only source change (tests and this directory aside), so PRE is this
# worktree with the base branch's copy of that one file swapped in and POST is the tree as it
# stands. Nothing is stashed: the header is copied aside and copied back, and a trap puts it back
# even if the build is interrupted -- a half-reverted header that survives into a commit is a
# worse outcome than a failed build.
#
# Warnings are captured per arm rather than eyeballed: "zero-warning" is a claim that needs a file.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BASE="${BASE:-479922c0a}"
OUT="${OUT:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/ringsize}"
JOBS="${JOBS:-8}"
CORES="${CORES:-48-55,176-183}"
mkdir -p "$OUT"
cd "$ROOT"

KEEP=$(mktemp /tmp/ringsize-rob-post.XXXXXX.h)
cp src/net/rob.h "$KEEP"
restore(){ cp "$KEEP" src/net/rob.h; }
trap 'restore; rm -f "$KEEP"' EXIT INT TERM

build(){ # build <label> -> build/tomokv-<label>, $OUT/build-<label>.log
  local label="$1"
  taskset -c "$CORES" make -j"$JOBS" > "$OUT/build-$label.log" 2>&1
  cp build/tomokv "build/tomokv-$label"
  local warn
  warn=$(grep -cE "warning:|error:" "$OUT/build-$label.log" || true)
  # PINNED SOURCE IS NOT A PINNED BINARY. The digest is recorded per arm so a later run can prove
  # which binary produced which row; the arms are additionally self-identifying in every A/B table,
  # because PRE reports millions of read_local_fallback_inflight_write where POST reports thousands.
  echo "$label: md5=$(md5sum "build/tomokv-$label" | cut -d" " -f1) warnings+errors=$warn"
}

# PRE first and POST last, so build/tomokv is left as the lane's own binary and only two full
# builds are paid for instead of three.
echo "== PRE (base $BASE) =="
git show "$BASE:src/net/rob.h" > src/net/rob.h
build pre
restore

echo "== POST (this tree) =="
touch src/net/rob.h
build post
cmp -s build/tomokv build/tomokv-post && echo "build/tomokv == build/tomokv-post" \
  || echo "NOTE: build/tomokv differs from build/tomokv-post"
cmp -s build/tomokv-pre build/tomokv-post \
  && { echo "REFUSING: the two arms are byte-identical -- one of them did not rebuild"; exit 1; } \
  || echo "arms differ, as they must"
