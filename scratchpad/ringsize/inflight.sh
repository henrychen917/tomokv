#!/bin/bash
# STEP 1 -- the ceiling. How many writes are published-and-unretired on ONE connection at the
# instant a read probes, and at the instant a write commits? Requires a -DTOMO_RLHIST binary.
#   inflight.sh <hist-binary> <outdir>
set -u
BIN="$1"; OUT="${2:-/tmp/ringsize-inflight}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
mkdir -p "$OUT"
KEYMAX=${KEYMAX:-200000}
SECS=${SECS:-20}
THREADS=${THREADS:-8}
CONNS=${CONNS:-8}

cell(){ # cell <ratio> <pipeline> <label>
  local ratio="$1" pl="$2" label="$3"
  local log="$OUT/srv-$label.log"
  boot_srv "$BIN" "$log" --atomic 0 --enable-debug-command yes || return 1
  run_cli "$OUT/$label-preload.txt" -s 127.0.0.1 -p "$PORT" --hide-histogram \
      --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=P:P --ratio=1:0 \
      -t 4 -c 4 --pipeline=32 -n $((KEYMAX/16))
  $CLI -p "$PORT" dbsize > "$OUT/$label-dbsize.txt" 2>&1
  local b_probe b_commit
  b_probe=$(info_field rl_inflight_at_probe); b_commit=$(info_field rl_inflight_at_commit)
  run_cli "$OUT/$label.txt" -s 127.0.0.1 -p "$PORT" --hide-histogram \
      --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=R:R --ratio="$ratio" \
      -t $THREADS -c $CONNS --pipeline="$pl" --test-time=$SECS
  local a_probe a_commit
  a_probe=$(info_field rl_inflight_at_probe); a_commit=$(info_field rl_inflight_at_commit)
  {
    echo "label=$label ratio=$ratio pipeline=$pl"
    echo "rate=$(grep -E '^Totals' "$OUT/$label.txt" | awk '{print $2}')"
    echo "read_local_hits=$(info_field read_local_hits)"
    echo "read_local_fallback_inflight_write=$(info_field read_local_fallback_inflight_write)"
    echo "read_local_fallbacks=$(info_field read_local_fallbacks)"
    echo "probe_before=$b_probe"
    echo "probe_after=$a_probe"
    echo "commit_before=$b_commit"
    echo "commit_after=$a_commit"
  } > "$OUT/$label.hist"
  stop_srv
  echo "done $label"
}

cell "3:2" 32 r41p32
cell "2:3" 32 r61p32
cell "3:2" 8  r41p8
