#!/usr/bin/env bash
# ===========================================================================
# v9 MAX-INFORMATION CHARACTERIZATION SWEEP  (>=12h, resumable)
# GOAL: maximize what we learn about the system, NOT find one peak config.
# So we EXPLORE broadly (full response curves, interactions, bench axes) rather
# than greedily hill-climb. Every config-vs-config comparison is BRACKETED
# against the SAME v9-default baseline (run default -> run variant -> ratio),
# REPS times, so all numbers are mutually comparable AND thermal drift cancels.
#
# Phases per regime:
#   A) OFAT response curves : each knob across its FULL grid vs default
#   B) interaction grids    : curated knob PAIRS (2-way) vs default
#   C) bench-axis curves    : pipeline depth + client count sweeps (absolute ops)
# (IO/worker split is a separate restart-based driver: v9_sweep_split.sh)
#
# Outputs (under /home/henry/Projects/v9_sweep/):
#   ofat.tsv  inter.tsv  bench.tsv   + per-regime/phase .done markers
# Canonical pin: server 0-7, load 12-15, jemalloc. Resumable on restart.
# ===========================================================================
set -u
# Pin to the FROZEN v9 binary so v10 rebuilds of THredis/src can't contaminate the sweep.
V9BIN=/home/henry/Projects/THredis-opt-v9/src/redis-server
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
JEM=/usr/lib/libjemalloc.so.2
OUT=/home/henry/Projects/v9_sweep; mkdir -p "$OUT"
OFAT="$OUT/ofat.tsv"; INTER="$OUT/inter.tsv"; BENCH="$OUT/bench.tsv"
PORT=7901; REPS=${REPS:-4}
[ -f "$OFAT" ]  || echo -e "regime\tknob\tvalue\trep\tops_def\tops_val\tratio" > "$OFAT"
[ -f "$INTER" ] || echo -e "regime\tcombo\trep\tops_def\tops_val\tratio" > "$INTER"
[ -f "$BENCH" ] || echo -e "regime\taxis\tvalue\trep\tops" > "$BENCH"

REGIMES=(
  "dispatch_r:200000:64:0:1:R"      "dispatch_mix:200000:64:1:9:R"
  "l3spill_r:2000000:64:0:1:R"      "l3spill_mix:2000000:64:1:9:R"
  "dram_cold:10000000:1024:1:9:R"   "dram_hot:10000000:1024:1:9:G"
  "bigval:300000:16384:1:9:R"       "writeheavy:2000000:64:1:0:R"
  "balanced:1000000:256:1:1:R"
)
# OFAT: knob:default:full,grid,of,candidates  (full curves => response shape)
KNOBS=(
  "thredis-worker-pop-batch:16:1,2,4,8,12,16"
  "thredis-pf-w-value:64:0,8,16,24,32,48,64,96,128"
  "thredis-pf-w-entry:64:0,8,16,32,64,128"
  "thredis-pf-w-hash:64:0,16,32,64,128"
  "thredis-pf-w-struct:64:0,16,32,64,128"
  "thredis-pf-w-io-reply:64:0,16,32,64,128"
  "thredis-pf-w-io-struct:64:0,16,32,64,128"
  "thredis-opt-prefetch-worker:yes:no,yes"
  "thredis-opt-prefetch-io:yes:no,yes"
  "thredis-opt-coalesce-signal:yes:no,yes"
  "thredis-opt-hash-carry:yes:no,yes"
  "thredis-opt-feedback-prefetch:no:no,yes"
  "thredis-opt-ship-reuse:no:no,yes"
)
# B: interaction combos "label|knob=val,knob=val"
INTERCOMBOS=(
  "pfval32_entry32|thredis-pf-w-value=32,thredis-pf-w-entry=32"
  "pfval16_entry16|thredis-pf-w-value=16,thredis-pf-w-entry=16"
  "pfoff_all|thredis-opt-prefetch-worker=no,thredis-opt-prefetch-io=no"
  "pop8_pfval32|thredis-worker-pop-batch=8,thredis-pf-w-value=32"
  "pop4_pfval16|thredis-worker-pop-batch=4,thredis-pf-w-value=16"
  "coaloff_hashoff|thredis-opt-coalesce-signal=no,thredis-opt-hash-carry=no"
  "feedback_ship|thredis-opt-feedback-prefetch=yes,thredis-opt-ship-reuse=yes"
)
declare -A DEF   # default value per knob (for reset)
for kspec in "${KNOBS[@]}"; do IFS=: read -r kn def cands <<<"$kspec"; DEF[$kn]="$def"; done

srv_up(){ for i in $(seq 1 40); do $CLI -p $PORT ping >/dev/null 2>&1 && return 0; sleep 0.5; done; return 1; }
start_srv(){ pkill -9 -x redis-server 2>/dev/null; sleep 1
  LD_PRELOAD=$JEM taskset -c 0-7 "$V9BIN" --port $PORT --save '' --appendonly no \
    --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/v9sw_srv.log 2>&1 & srv_up; }
populate(){ taskset -c 12-15 memtier_benchmark -p $PORT -P redis -t 4 -c 16 --pipeline=8 --ratio=1:0 \
    --key-pattern=P:P --key-prefix="key:" --key-minimum=1 --key-maximum=$1 -n $(($1/64+1)) -d $2 --hide-histogram >/dev/null 2>&1; }
run(){ local kp pipe=${5:-12} cl=${6:-32}; [ "$4" = G ] && kp="G:G --key-stddev=$(($1/20))" || kp="R:R"
  timeout 45 taskset -c 12-15 memtier_benchmark -p $PORT -P redis -t 4 -c $cl --pipeline=$pipe --test-time=6 \
    --ratio=$3 --key-pattern=$kp --key-prefix="key:" --key-minimum=1 --key-maximum=$1 -d $2 --hide-histogram 2>&1 | awk '/^Totals/{printf "%.0f",$2}'; }
setk(){ $CLI -p $PORT config set "$1" "$2" >/dev/null 2>&1; }
reset_defaults(){ for k in "${!DEF[@]}"; do setk "$k" "${DEF[$k]}"; done; setk thredis-opt-value-forward no
  [ "${1:-}" = bigval ] && { setk thredis-opt-zerocopy yes; setk thredis-zerocopy-min-value 1024; }; }

for spec in "${REGIMES[@]}"; do
  IFS=: read -r name keys vsz r1 r2 pat <<< "$spec"; ratio="$r1:$r2"
  echo "[regime] $name ${keys}x${vsz}B ${ratio} $pat @ $(date +%H:%M:%S)"
  need_srv=1
  for ph in A B C; do [ -f "$OUT/$name.$ph.done" ] || need_srv=0; done
  [ $need_srv -eq 1 ] && { echo "[skip] $name all phases done"; continue; }
  start_srv || { echo "[err] no server $name"; continue; }
  reset_defaults "$name"; populate "$keys" "$vsz"

  # --- Phase A: OFAT response curves ---
  if [ ! -f "$OUT/$name.A.done" ]; then
    KX=("${KNOBS[@]}"); [ "$name" = bigval ] && KX+=("thredis-opt-zerocopy:yes:no,yes" "thredis-zerocopy-min-value:1024:0,256,512,2048,8192")
    for kspec in "${KX[@]}"; do
      IFS=: read -r kn def cands <<<"$kspec"; IFS=, read -ra cl <<<"$cands"
      for cand in "${cl[@]}"; do
        for rep in $(seq 1 $REPS); do
          reset_defaults "$name"; od=$(run "$keys" "$vsz" "$ratio" "$pat")
          setk "$kn" "$cand"; ov=$(run "$keys" "$vsz" "$ratio" "$pat")
          rr=$(awk -v v="$ov" -v d="$od" 'BEGIN{if(d>0)printf "%.4f",v/d; else print 0}')
          echo -e "$name\t$kn\t$cand\t$rep\t$od\t$ov\t$rr" >> "$OFAT"
        done
      done
    done
    touch "$OUT/$name.A.done"; echo "[A done] $name @ $(date +%H:%M:%S)"
  fi
  # --- Phase B: interactions ---
  if [ ! -f "$OUT/$name.B.done" ]; then
    for combo in "${INTERCOMBOS[@]}"; do
      lab="${combo%%|*}"; sets="${combo#*|}"
      for rep in $(seq 1 $REPS); do
        reset_defaults "$name"; od=$(run "$keys" "$vsz" "$ratio" "$pat")
        IFS=, read -ra kv <<<"$sets"; for p in "${kv[@]}"; do setk "${p%%=*}" "${p#*=}"; done
        ov=$(run "$keys" "$vsz" "$ratio" "$pat")
        rr=$(awk -v v="$ov" -v d="$od" 'BEGIN{if(d>0)printf "%.4f",v/d; else print 0}')
        echo -e "$name\t$lab\t$rep\t$od\t$ov\t$rr" >> "$INTER"
      done
    done
    touch "$OUT/$name.B.done"; echo "[B done] $name @ $(date +%H:%M:%S)"
  fi
  # --- Phase C: bench-axis curves (pipeline, clients) ---
  if [ ! -f "$OUT/$name.C.done" ]; then
    reset_defaults "$name"
    for p in 1 2 4 8 16 32 64; do for rep in 1 2 3; do
      o=$(run "$keys" "$vsz" "$ratio" "$pat" "$p" 32); echo -e "$name\tpipeline\t$p\t$rep\t$o" >> "$BENCH"; done; done
    for c in 8 16 32 64 128; do for rep in 1 2 3; do
      o=$(run "$keys" "$vsz" "$ratio" "$pat" 12 "$c"); echo -e "$name\tclients\t$c\t$rep\t$o" >> "$BENCH"; done; done
    touch "$OUT/$name.C.done"; echo "[C done] $name @ $(date +%H:%M:%S)"
  fi
  $CLI -p $PORT shutdown nosave >/dev/null 2>&1; pkill -9 -x redis-server 2>/dev/null
done
echo "SWEEP COMPLETE @ $(date +%H:%M:%S)"; pkill -9 -x redis-server 2>/dev/null
