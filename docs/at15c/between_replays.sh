#!/bin/bash
# Run after a full matrix exits, while the outer six-run launcher is paused.
set -eu
cd "$(dirname "$0")/../.."
launcher=$1
trap 'kill -CONT "$launcher" 2>/dev/null || true' EXIT
while ! grep -q '^DIFFER GATE:' docs/at15c/replay-2-pre-armed.log; do sleep 1; done
taskset -c 112-127 make -j2 > docs/at15c/build-post.log 2>&1
taskset -c 112-127 python3 docs/at15c/build_candidates.py > docs/at15c/bisect-builds.log 2>&1
taskset -c 112-127 python3 docs/at15c/build_pad.py > docs/at15c/pad-a.log 2>&1
taskset -c 112-127 python3 docs/at15c/focused_replay.py \
  build/at15c/bisect-61a9ab20f/tomokv build/at15c/bisect-pre --runs 3 \
  > docs/at15c/bisect-pre.log 2>&1
taskset -c 112-127 python3 docs/at15c/focused_replay.py \
  build/at15c/bisect-76568a8fc/tomokv build/at15c/bisect-post --runs 3 \
  > docs/at15c/bisect-post.log 2>&1
taskset -c 112-127 python3 docs/at15c/focused_replay.py \
  build/tomokv build/at15c/profile-post-mono --runs 3 --trace --perf --directed \
  > docs/at15c/profile-post-mono.log 2>&1
taskset -c 112-127 python3 docs/at15c/focused_replay.py \
  build/tomokv build/at15c/directed-split --geometry split --runs 3 --directed \
  > docs/at15c/directed-split.log 2>&1
taskset -c 112-127 python3 docs/at15c/focused_replay.py \
  build/tomokv build/at15c/absolute-control-post --runs 3 --trace --absolute-control \
  > docs/at15c/absolute-control-post.log 2>&1
taskset -c 112-127 python3 docs/at15c/focused_replay.py \
  build/at15b-pre/tomokv build/at15c/absolute-control-pre --runs 3 --trace --absolute-control \
  > docs/at15c/absolute-control-pre.log 2>&1
mkdir -p docs/at15c/proofs
taskset -c 112-127 python3 - <<'PY' > docs/at15c/serverless.log 2>&1
from pathlib import Path
source = Path('docs/at15b/prove.py')
text = source.read_text().replace("out = Path('docs/at15b')", "out = Path('docs/at15c/proofs')")
exec(compile(text, str(source), 'exec'))
PY
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare \
  build/at15b-pre/src build/src docs/at15c/hot-namespaced.json > docs/at15c/hot-namespaced.log 2>&1
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare \
  build/at15b-pre/db0/src build/db0/src docs/at15c/hot-db0.json > docs/at15c/hot-db0.log 2>&1
date -u '+completed %FT%TZ'
