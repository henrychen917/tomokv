#!/bin/bash
# ab.sh OUT.csv SECS ROUNDS WORKLOAD ARM... -- interleaved A/B matrix on the lane cores.
#   WORKLOAD: mk | sk1:1 | sk9:1 | get
#   ARM:      label=BIN:FLIPAUTO  e.g. base0=$BASE_BIN:0 fix1=$FIX_BIN:1
#   Cells run round-robin over the arms, arm order reversed on even rounds (ABBA). Every cell
#   re-checks the box gate and stops the run if the owner started measuring. One CSV row per cell:
#   flips, clients moved, triggers by kind, holds, anchor, live split, per-role busy over the window.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
OUT=$1; SECS=$2; ROUNDS=$3; WL=$4; shift 4; ARMS=("$@")
PORT=$PORT_AB
[ -f "$OUT" ] || echo "round,arm,wl,fa,rate,p50,p99,comp,xfer,trig,boot,fp,surge,coll,forced,null,hold,anchor,rt,margin,live,busy,lbcli,lbbkt" >"$OUT"
load() { case "$WL" in mk) ./scratch/mk.sh "$PORT" "$SECS";; sk*) ./scratch/sk.sh "$PORT" "$SECS" "${WL#sk}";; get) ./scratch/sk.sh "$PORT" "$SECS" 0:1;; esac; }
cell() { # cell ROUND LABEL BIN FA
  local round=$1 label=$2 bin=$3 fa=$4 pid rate p50 p99 info out
  require_gate || exit 3
  pid=$(boot "$bin" "$PORT" "ab-$label" --ratio "$SRV_RATIO" --shards 64 --atomic 1 --flip-auto "$fa") || exit 2
  preload "$PORT"
  lbsnap "$PORT" >"$SP/fd-lb0.txt"
  # flip timeline: one line per 2 s so moves AFTER stabilization can be told from the boot search
  ( t0=$(date +%s); while :; do echo "$(( $(date +%s) - t0 )) $(redis-cli -p "$PORT" info flipctl 2>/dev/null | tr -d '\r' | grep -E '^flipctl_(state|phase|anchor_io|triggers|model_holds|round_trips|model_margin):' | tr '\n' ' ') $(redis-cli -p "$PORT" info stats 2>/dev/null | tr -d '\r' | grep -E '^flip_(completed|clients_transferred):' | tr '\n' ' ')"; sleep 2; done ) >"$SP/fd-tl-$label-$WL-$round.txt" 2>&1 &
  local tl=$!
  out=$(load 2>/dev/null)
  kill "$tl" 2>/dev/null; wait "$tl" 2>/dev/null
  lbsnap "$PORT" >"$SP/fd-lb1.txt"
  rate=$(echo "$out" | awk '/^Totals/{print $2}'); p50=$(echo "$out" | awk '/^Totals/{print $6}'); p99=$(echo "$out" | awk '/^Totals/{print $8}')
  info=$(redis-cli -p "$PORT" info all 2>/dev/null | tr -d '\r')
  g() { infog "$info" "$1"; }
  echo "$round,$label,$WL,$fa,${rate:-MISSING},${p50:-},${p99:-},$(g flip_completed),$(g flip_clients_transferred),$(g flipctl_triggers),$(g flipctl_boot_triggers),$(g flipctl_fingerprint_triggers),$(g flipctl_rate_surge_triggers),$(g flipctl_rate_collapse_triggers),$(g flipctl_forced_triggers),$(g flipctl_null_maneuvers),$(g flipctl_model_holds),$(g flipctl_anchor_io):$(g flipctl_anchor_ex),$(g flipctl_round_trips),$(g flipctl_model_margin),$(g io_threads):$(g ex_threads),$(lbbusy "$SP/fd-lb0.txt" "$SP/fd-lb1.txt" | tr -d ' '),$(g tomokv_keylb_client_moves),$(g tomokv_keylb_bucket_moves)" | tee -a "$OUT"
  stop "$pid" "$PORT"
}
for r in $(seq "$ROUNDS"); do
  if [ $((r % 2)) = 1 ]; then order=("${ARMS[@]}"); else order=(); for ((i=${#ARMS[@]}-1; i>=0; i--)); do order+=("${ARMS[$i]}"); done; fi
  for arm in "${order[@]}"; do
    label=${arm%%=*}; spec=${arm#*=}; bin=${spec%:*}; fa=${spec##*:}
    cell "$r" "$label" "$bin" "$fa"
  done
done
