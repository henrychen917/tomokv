#!/bin/bash
# wave3 (from docs/wave2/tools/build_refs.sh): default (`make all`) reference builds from `git archive`
# of each revision, with that revision's own Makefile, for per-body attribution. Never runs a
# server. All compiles on CPUs 80-95. usage: build_refs.sh name=rev ...
set -u
WT=/home/user/Projects/cx-wave3
REFS=$WT/build/wave3/refs
mkdir -p "$REFS"
for spec in "$@"; do
  name=${spec%%=*}; rev=${spec#*=}
  dir=$REFS/$name-src
  if [ ! -x "$dir/build/tomokv" ]; then
    mkdir -p "$dir"
    git -C "$WT" archive "$rev" | tar -x -C "$dir"
    ( time taskset -c 80-95 make -C "$dir" -j16 all ) > "$REFS/$name-build.log" 2>&1
    echo "exit=$?" >> "$REFS/$name-build.log"
  fi
  printf '%s %s %s\n' "$name" "$(git -C "$WT" rev-parse "$rev")" "$(sha256sum "$dir/build/tomokv" | cut -d' ' -f1)"
done
