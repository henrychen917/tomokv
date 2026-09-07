#!/bin/bash
# abr.sh OUT.csv SECS ROUNDS WORKLOAD ARM... -- the redesign's A/B matrix (abw.sh + the model's
#   decision trail). PAUSES on the box marker instead of exiting; ROUND_OFFSET=n labels rounds n+1..
#   WORKLOAD: mk | sk1:1 | sk9:1 | get       ARM: label=BIN:FLIPAUTO
#   Cells run round-robin over the arms, arm order reversed on even rounds (ABBA). One CSV row per
#   cell: rate/p50/p99, flips, clients moved, triggers by kind, holds, anchor, round trips, margin,
#   live split, per-role busy, and the redesign's decision, kappa, misses, cost holds, client cost.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
OUT=$1; SECS=$2; ROUNDS=$3; WL=$4; shift 4; ARMS=("$@")
PORT=$PORT_AB
[ -f "$OUT" ] || echo "round,arm,wl,fa,rate,p50,p99,comp,xfer,trig,boot,fp,surge,coll,forced,null,hold,anchor,rt,margin,live,busy,lbcli,lbbkt,decision,kappa,moves,misses,costholds,clientcost,flipticks" >"$OUT"
load() { case "$WL" in mk) ./scratch/mk.sh "$PORT" "$SECS";; sk*) ./scratch/sk.sh "$PORT" "$SECS" "${WL#sk}";; get) ./scratch/sk.sh "$PORT" "$SECS" 0:1;; esac; }
cell() { # cell ROUND LABEL BIN FA
  local round=$1 label=$2 bin=$3 fa=$4 pid rate p50 p99 info out
  while ! gate_ok; do echo "paused $(date +%T): box marker held"; sleep 30; done
  pid=$(boot "$bin" "$PORT" "ab-$label" --ratio "$SRV_RATIO" --shards 64 --atomic 1 --flip-auto "$fa") || exit 2
  preload "$PORT"
  lbsnap "$PORT" >"$SP/fd-lb0-$label-$WL-$round.txt"
  ( t0=$(date +%s); while :; do echo "$(( $(date +%s) - t0 )) $(redis-cli -p "$PORT" info flipctl 2>/dev/null | tr -d '\r' | grep -E '^flipctl_(state|phase|anchor_io|triggers|model_holds|round_trips|model_margin|model_last_decision|model_kappa|model_misses|cost_holds):' | tr '\n' ' ') $(redis-cli -p "$PORT" info stats 2>/dev/null | tr -d '\r' | grep -E '^flip_(completed|clients_transferred):' | tr '\n' ' ') foreign=$(ps -eo pid,psr,comm --no-headers | awk '($2==52||$2==53||$2==54||$2==55||$2==56||$2==57||$2==180||$2==181||$2==182||$2==183||$2==184||$2==185) && $3!="tomokv" && $3!="memtier_benchma" && $3!="redis-cli" && $3!="ps" && $3!="awk" {printf "%s/%s@%s ", $1, $3, $2}')"; sleep 2; done ) >"$SP/fd-tl-$label-$WL-$round.txt" 2>&1 &
  local tl=$!
  load >"$SP/fd-mt-$label-$WL-$round.txt" 2>&1; out=$(tr '\r' '\n' <"$SP/fd-mt-$label-$WL-$round.txt")
  kill "$tl" 2>/dev/null; wait "$tl" 2>/dev/null
  lbsnap "$PORT" >"$SP/fd-lb1-$label-$WL-$round.txt"
  rate=$(echo "$out" | awk '/^Totals/{print $2}'); p50=$(echo "$out" | awk '/^Totals/{print $6}'); p99=$(echo "$out" | awk '/^Totals/{print $8}')
  info=$(redis-cli -p "$PORT" info all 2>/dev/null | tr -d '\r')
  redis-cli -p "$PORT" debug flipctl 2>/dev/null >"$SP/fd-dbg-$label-$WL-$round.txt"
  g() { infog "$info" "$1"; }
  echo "$round,$label,$WL,$fa,${rate:-MISSING},${p50:-},${p99:-},$(g flip_completed),$(g flip_clients_transferred),$(g flipctl_triggers),$(g flipctl_boot_triggers),$(g flipctl_fingerprint_triggers),$(g flipctl_rate_surge_triggers),$(g flipctl_rate_collapse_triggers),$(g flipctl_forced_triggers),$(g flipctl_null_maneuvers),$(g flipctl_model_holds),$(g flipctl_anchor_io):$(g flipctl_anchor_ex),$(g flipctl_round_trips),$(g flipctl_model_margin),$(g io_threads):$(g ex_threads),$(lbbusy "$SP/fd-lb0-$label-$WL-$round.txt" "$SP/fd-lb1-$label-$WL-$round.txt"),$(g tomokv_keylb_client_moves),$(g tomokv_keylb_bucket_moves),$(g flipctl_model_last_decision),$(g flipctl_model_kappa),$(g flipctl_model_moves),$(g flipctl_model_misses),$(g flipctl_cost_holds),$(g flipctl_client_cost),$(g flipctl_flip_ticks)" | tee -a "$OUT"
  stop "$pid" "$PORT"
}
R0=${ROUND_OFFSET:-0}
for rr in $(seq "$ROUNDS"); do r=$((rr + R0))
  if [ $((r % 2)) = 1 ]; then order=("${ARMS[@]}"); else order=(); for ((i=${#ARMS[@]}-1; i>=0; i--)); do order+=("${ARMS[$i]}"); done; fi
  for arm in "${order[@]}"; do
    label=${arm%%=*}; spec=${arm#*=}; bin=${spec%:*}; fa=${spec##*:}
    cell "$r" "$label" "$bin" "$fa"
  done
done
