#!/bin/bash
# Build both arms from ONE tree, so the only difference between them is this lane's header.
#
# PRE is this worktree with the BASE BRANCH's copy of every src/ file this lane touched swapped in;
# POST is the tree as it stands. The file list is COMPUTED (`git diff --name-only $BASE -- src/`)
# rather than written down, because a hand-written list is exactly the thing that goes stale: this
# lane began by changing src/net/rob.h alone and later moved kRobWindow out of src/net/conn.h into
# it, and a PRE built from the base rob.h beside this tree's conn.h defines that constant nowhere
# and does not compile. Nothing is stashed: the files are copied aside and copied back, and a trap
# puts them back even if the build is interrupted -- a half-reverted tree that survives into a
# commit is a worse outcome than a failed build.
#
# Warnings are captured per arm rather than eyeballed: "zero-warning" is a claim that needs a file.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BASE="${BASE:-479922c0a}"
OUT="${OUT:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/ringsize}"
JOBS="${JOBS:-12}"
CORES="${CORES:-58-63,186-191}"
mkdir -p "$OUT"
cd "$ROOT"

LANE_SRC=$(git diff --name-only "$BASE" -- src/)
[ -n "$LANE_SRC" ] || { echo "REFUSING: no src/ file differs from $BASE -- there is no POST arm"; exit 1; }
echo "lane src files: $(echo $LANE_SRC | tr '\n' ' ')"
KEEP=$(mktemp -d /tmp/ringsize-post-src.XXXXXX)
for f in $LANE_SRC; do mkdir -p "$KEEP/$(dirname "$f")"; cp "$f" "$KEEP/$f"; done
restore(){ local f; for f in $LANE_SRC; do cp "$KEEP/$f" "$f"; done; }
trap 'restore; rm -rf "$KEEP"' EXIT INT TERM

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
for f in $LANE_SRC; do git show "$BASE:$f" > "$f"; done
build pre
restore

echo "== POST (this tree) =="
touch $LANE_SRC
build post
cmp -s build/tomokv build/tomokv-post && echo "build/tomokv == build/tomokv-post" \
  || echo "NOTE: build/tomokv differs from build/tomokv-post"
cmp -s build/tomokv-pre build/tomokv-post \
  && { echo "REFUSING: the two arms are byte-identical -- one of them did not rebuild"; exit 1; } \
  || echo "arms differ, as they must"

# THE TWO DIAGNOSTIC ARMS. The overflow counter is grafted on by ovf_patch.py, whose three anchors
# are textually identical in the base header and in this lane's, so BOTH arms are instrumented by
# the same patch and their counts are comparable. They are separate binaries because the counter
# sits on a path PRE takes constantly: leaving it in the measured build would put the diagnostic
# inside the arm it exists to describe. Rate, instructions/op and IPC come from the clean binaries
# above; only the overflow count comes from these.
if [ "${OVF:-1}" = 1 ]; then
  echo "== PRE+ovf / POST+ovf (ring-overflow counter) =="
  for f in $LANE_SRC; do git show "$BASE:$f" > "$f"; done
  python3 "$HERE/ovf_patch.py" apply .
  build pre-ovf
  python3 "$HERE/ovf_patch.py" revert .
  restore
  python3 "$HERE/ovf_patch.py" apply .
  build post-ovf
  python3 "$HERE/ovf_patch.py" revert .
  # The graft must be gone from the tree, and the restored tree must still be the POST tree.
  git diff --quiet -- src/cmd/t_server.cc \
    || { echo "REFUSING: ovf_patch left src/cmd/t_server.cc modified"; exit 1; }
  # build/tomokv is whatever compiled last, and the battery and differ phases run ./build/tomokv.
  # Put the CLEAN post binary back under that name so no correctness run uses an instrumented one.
  cp build/tomokv-post build/tomokv
  echo "ovf arms built; tree restored; build/tomokv is the clean POST binary"
fi
