#!/bin/bash
# wave2: default (`make all`) reference builds from `git archive` of each lane tip, for per-body
# attribution. Never runs a server. All compiles on CPUs 80-95.
set -u
WT=/home/user/Projects/cx-wave2
REFS=$WT/build/wave2/refs
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
