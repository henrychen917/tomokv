#!/bin/bash
# wrongsplit.sh N -- the "must move on EVERY run" bar: N repeats of the 3:1 boot, 120 s, 1 Hz trace.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh; cd "$WT"
for i in $(seq "${1:-4}"); do
  while ! gate_ok; do sleep 30; done
  tr=$SP/fd-ws-trace-$i.txt
  pid=$(boot "$FIX_BIN" "$PORT_SIG" "ws-$i" --ratio 3:1 --shards 64 --atomic 1 --flip-auto 1) || continue
  preload "$PORT_SIG"
  ( t0=$(date +%s); while :; do tc=$(redis-cli -p "$PORT_SIG" info stats 2>/dev/null | tr -d '\r' | sed -n 's/^total_commands_processed://p'); sp=$(redis-cli -p "$PORT_SIG" info server 2>/dev/null | tr -d '\r' | grep -E '^(io|ex)_threads:' | sed 's/.*://' | tr '\n' ':' | sed 's/:$//'); echo "$(( $(date +%s) - t0 )) ${tc:-0} ${sp:-0:0}"; sleep 1; done ) >"$tr" 2>&1 &
  sampler=$!
  ./scratch/mk.sh "$PORT_SIG" 120 >"$SP/fd-ws-mt-$i.txt" 2>&1
  kill "$sampler" 2>/dev/null; wait "$sampler" 2>/dev/null
  info=$(redis-cli -p "$PORT_SIG" info all 2>/dev/null | tr -d '\r')
  redis-cli -p "$PORT_SIG" debug flipctl >"$SP/fd-ws-dbg-$i.txt" 2>&1
  echo "run $i flips=$(infog "$info" flip_completed) live=$(infog "$info" io_threads):$(infog "$info" ex_threads) decision=$(infog "$info" flipctl_model_last_decision) | $(python3 ./scratch/ttfm.py "$tr" 3 1 | head -1)"
  stop "$pid" "$PORT_SIG"
done
