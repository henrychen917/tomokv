#!/bin/bash
# WHAT DOES A "55% WRITES" CELL ACTUALLY DELIVER TO ONE CONNECTION?
#
# The three-regime matrix names its cells by write FRACTION and assumes that is what a memtier
# --ratio controls. The connection regime says otherwise, on the same binary and the same 512
# connections at the same depth: at --ratio=1:1 the base arm demoted 902 reads for an in-flight
# write and served 99.9% of its reads locally, while at --ratio=55:45 it demoted 3,007,793 and
# served 82.1%. A five-point move in write fraction cannot do that. A change in the SHAPE of the
# stream can: a ring overflows on a RUN of writes, not on their long-run average, and if memtier
# emits its ratio as repeating blocks then "55:45" is a 55-write run and "1:1" is an alternation
# that never puts more than sixteen writes in a thirty-two deep window.
#
# The experiment separates the two by holding one constant and moving the other:
#
#     1:1   and  50:50   -- the SAME 50% write fraction, block length 1 against 50
#     11:9  and  55:45   -- the SAME 55% write fraction, block length ~11 against 55
#
# If the demotion counts track the fraction, the cells mean what their labels say. If they track the
# block length, then this lane's matrix is a run-length sweep wearing a write-fraction label, and
# every row of it has to be described that way -- including in the verdict.
#
#   ratio_shape.sh <bin> <outCsv>
set -u
BIN="$1"; OUT="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
KEYMAX=${KEYMAX:-200000}
SECS=${SECS:-12}
SHARDS=${SHARDS:-2}
THREADS=${THREADS:-8}
CONNS=${CONNS:-64}
TMP=${TMP:-/tmp/ringsize-ratio}
mkdir -p "$TMP"
[ -s "$OUT" ] || echo "ratio,write_frac,rate,cmds,hits,demoted,fallbacks,local_pct,srv_cores" > "$OUT"

boot_srv "$BIN" "$TMP/srv.log" --atomic 0 --enable-debug-command yes || exit 1
run_cli "$TMP/preload.txt" -s 127.0.0.1 -p "$PORT" --hide-histogram \
    --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=P:P --ratio=1:0 \
    -t 4 -c 4 --pipeline=32 -n $((KEYMAX/16)) || { stop_srv; exit 1; }

for ratio in 1:1 50:50 11:9 55:45; do
  w=${ratio%%:*}; r=${ratio##*:}
  frac=$(python3 -c "print(f'{$w/($w+$r):.3f}')")
  h0=$(info_field read_local_hits); f0=$(info_field read_local_fallback_inflight_write)
  a0=$(info_field read_local_fallbacks); c0=$(info_field total_commands_processed)
  j0=$(awk '{print $14+$15}' /proc/$SRV/stat); t0=$(date +%s.%N)
  rf="$TMP/r-$ratio.txt"
  start_cli "$rf" -s 127.0.0.1 -p "$PORT" --hide-histogram --key-maximum=$KEYMAX \
      --key-minimum=1 --data-size=32 --key-pattern=R:R --ratio="$ratio" \
      -t "$THREADS" -c "$CONNS" --pipeline=32 --test-time=$SECS || { stop_srv; exit 1; }
  wait "$MEMTIER_PID" 2>/dev/null
  j1=$(awk '{print $14+$15}' /proc/$SRV/stat); t1=$(date +%s.%N)
  h1=$(info_field read_local_hits); f1=$(info_field read_local_fallback_inflight_write)
  a1=$(info_field read_local_fallbacks); c1=$(info_field total_commands_processed)
  rate=$(grep -E '^Totals' "$rf" | awk '{print $2}')
  srvcpu=$(python3 -c "print(f'{(($j1-$j0)/100.0)/max(0.001,$t1-$t0):.2f}')")
  assert_cell_did_work "$rate" "$((c1-c0))" "$t0" "$t1" "ratio $ratio" "$rf" || { stop_srv; exit 1; }
  pct=$(python3 -c "h=$((h1-h0)); a=$((a1-a0)); print(f'{100.0*h/(h+a):.2f}' if h+a else 'nan')")
  echo "$ratio,$frac,${rate:-0},$((c1-c0)),$((h1-h0)),$((f1-f0)),$((a1-a0)),$pct,$srvcpu" >> "$OUT"
  printf '%-7s frac=%s  rate=%10.0f  local=%6s%%  demoted=%10d\n' \
    "$ratio" "$frac" "${rate:-0}" "$pct" "$((f1-f0))"
done
stop_srv

python3 - "$OUT" <<'PY'
import csv, sys
rows = {r['ratio']: r for r in csv.DictReader(open(sys.argv[1]))}
print()
print(f"{'pair':<26}{'write frac':>11}{'block':>7}{'local %':>10}{'demoted':>13}{'M ops/s':>10}")
print('-' * 77)
for ratio, block in (('1:1', 1), ('50:50', 50), ('11:9', 11), ('55:45', 55)):
    r = rows.get(ratio)
    if not r:
        continue
    print(f"{'--ratio=' + ratio:<26}{float(r['write_frac']):>11.3f}{block:>7}"
          f"{float(r['local_pct']):>9.1f}%{int(r['demoted']):>13,}{float(r['rate'])/1e6:>10.3f}")
print()
def d(a, b, f):
    if a in rows and b in rows:
        return float(rows[b][f]) - float(rows[a][f])
    return float('nan')
print("SAME 50% write fraction, block 1 -> 50:  local share moves "
      f"{d('1:1','50:50','local_pct'):+.1f} points")
print("SAME 55% write fraction, block 11 -> 55: local share moves "
      f"{d('11:9','55:45','local_pct'):+.1f} points")
print()
print("A share that barely moves inside each pair means the cells measure write FRACTION and their")
print("labels are right. A share that collapses inside a pair means they measure the write RUN")
print("LENGTH the load generator happens to emit, and every row of the matrix has to say so.")
PY
