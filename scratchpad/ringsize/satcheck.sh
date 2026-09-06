#!/bin/bash
# IS THE SERVER THE BOTTLENECK? TESTED, NOT ASSERTED.
#
# Every rate A/B in this lane is only a measurement of the server if the server is the thing that
# limits it. Two nulls have already been thrown away for failing that condition -- the 3/3 pin moved
# -12.14% on one binary against itself, and the 2/4 pin that replaced it still burned 1.75 of its
# two server cores in every cell while its read-only control swung 14% visit to visit. Core burn
# alone cannot settle it: a number like 1.75/2.00 is equally consistent with a server that idles at
# a syscall boundary and a server that is waiting for work.
#
# The test that can settle it is a LADDER. Hold the server fixed and give the load generator more
# capacity, step by step. If the rate climbs, the generator was the limit and every rate taken there
# is a measurement of memtier. If the rate stops climbing while the generator is still growing, the
# server is the limit from that rung on, and that rung is the geometry to measure in.
#
# One binary (PRE) throughout: this is an instrument check, and an A/B inside it would confound the
# question with its answer. Two cells -- the write-ratio edge, and the read-only control that was
# the unstable one.
#
#   satcheck.sh <bin> <outCsv>
set -u
BIN="$1"; OUT="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
KEYMAX=${KEYMAX:-200000}
SECS=${SECS:-12}
SHARDS=${SHARDS:-2}
TMP=${TMP:-/tmp/ringsize-sat}
mkdir -p "$TMP"
[ -s "$OUT" ] || echo "rung,cores,threads,conns,cell,rate,p99,cmds,instr,cycles,srv_cores,srv_ghz,wall" > "$OUT"

# rung : load-generator cpus : threads : connections-per-thread
# Rung 1 is the geometry the last null ran in; every later rung adds generator capacity and nothing
# else. Total connections are held at 512 wherever the arithmetic allows, so what changes between
# rungs is how much hardware is serving them, not how many there are.
RUNGS=${RUNGS:-"1:60-63:8:64 2:60-63,188-191:8:64 3:60-63,188-191:12:43 4:60-63,188-191:16:32"}

boot_srv "$BIN" "$TMP/srv.log" --atomic 0 --enable-debug-command yes || {
  echo "BOOT FAILED -- server log tail:"; tail -25 "$TMP/srv.log"; exit 1; }
CLICORES=60-63,188-191 run_cli "$TMP/preload.txt" -s 127.0.0.1 -p "$PORT" --hide-histogram \
    --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=P:P --ratio=1:0 \
    -t 4 -c 4 --pipeline=32 -n $((KEYMAX/16)) || { stop_srv; exit 1; }
size=$($CLI -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
[ "$size" = "$KEYMAX" ] && echo "dbsize=$size (pinned to keymax)" || echo "WARN dbsize=$size keymax=$KEYMAX"

# Per-thread server cpu across a cell: a pair of workers at 87% each is a server waiting for work;
# one at 100% beside one at 62% is a shard imbalance wearing the same total.
thread_cpu(){ for t in /proc/$SRV/task/*; do
    [ -r "$t/stat" ] || continue
    awk -v tid="${t##*/}" '{print tid, $14+$15}' "$t/stat" 2>/dev/null; done; }

for rung in $RUNGS; do
  n=${rung%%:*};       rest=${rung#*:}
  cores=${rest%%:*};   rest=${rest#*:}
  th=${rest%%:*};      cn=${rest##*:}
  for cell in w55 r100; do
    case "$cell" in w55) ratio=55:45;; r100) ratio=0:1;; esac
    c0=$(info_field total_commands_processed)
    j0=$(awk '{print $14+$15}' /proc/$SRV/stat); t0=$(date +%s.%N)
    thread_cpu > "$TMP/th0-$n-$cell.txt"
    rf="$TMP/r$n-$cell.txt"; pf="$TMP/p$n-$cell.txt"
    perf stat -e instructions,cycles -x, -o "$pf" -p "$SRV" 2>/dev/null &
    PERF=$!
    CLICORES="$cores" start_cli "$rf" -s 127.0.0.1 -p "$PORT" --hide-histogram \
        --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=R:R \
        --ratio="$ratio" -t "$th" -c "$cn" --pipeline=32 --test-time=$SECS \
      || { kill -INT $PERF 2>/dev/null; stop_srv; exit 1; }
    wait "$MEMTIER_PID" 2>/dev/null
    kill -INT $PERF 2>/dev/null; wait $PERF 2>/dev/null
    j1=$(awk '{print $14+$15}' /proc/$SRV/stat); t1=$(date +%s.%N)
    thread_cpu > "$TMP/th1-$n-$cell.txt"
    c1=$(info_field total_commands_processed)
    rate=$(grep -E '^Totals' "$rf" | awk '{print $2}')
    p99=$(grep -E '^Totals' "$rf" | awk '{print $7}')
    ins=$(grep -m1 ',instructions,' "$pf" | cut -d, -f1)
    cyc=$(grep -m1 ',cycles,' "$pf" | cut -d, -f1)
    read -r srvcpu ghz wall <<<"$(python3 -c "
w=$t1-$t0
print(f'{(($j1-$j0)/100.0)/max(0.001,w):.3f} {${cyc:-0}/1e9/max(0.001,w):.3f} {w:.2f}')")"
    # THE CPU LIST GOES IN WITH PLUSES, NOT COMMAS. "60-63,188-191" written raw into a csv is two
    # fields, so every column after it shifts by one and the reader reports `could not convert
    # string to float: 'w55'` -- which is what happened, after the whole ladder had been measured.
    # Only rung 1 survived, because it is the one rung whose cpu list has no comma in it.
    echo "$n,${cores//,/+},$th,$((th*cn)),$cell,${rate:-0},${p99:-0},$((c1-c0)),${ins:-0},${cyc:-0},$srvcpu,$ghz,$wall" >> "$OUT"
    printf 'rung %s  %-16s t=%-3s conns=%-5s %-5s  rate=%10.0f  srv=%s cores  %s Gcyc/s\n' \
      "$n" "$cores" "$th" "$((th*cn))" "$cell" "${rate:-0}" "$srvcpu" "$ghz"
    # per-thread delta, printed so an imbalance cannot hide inside the total
    join <(sort "$TMP/th0-$n-$cell.txt") <(sort "$TMP/th1-$n-$cell.txt") \
      | awk -v w="$wall" '{d=($3-$2)/100.0/w; if (d>0.02) printf "        tid %-8s %.2f cores\n", $1, d}'
  done
done
stop_srv
echo
python3 - "$OUT" <<'PY'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
print(f"{'cell':<6}{'rung':<6}{'gen cpus':<16}{'thr':>4}{'conns':>7}{'M ops/s':>10}{'vs rung1':>10}{'srv cores':>11}{'p99 ms':>9}")
for cell in ('w55', 'r100'):
    base = None
    for r in rows:
        if r['cell'] != cell: continue
        rate = float(r['rate']) / 1e6
        if base is None: base = rate
        print(f"{cell:<6}{r['rung']:<6}{r['cores'].replace('+', ','):<16}{r['threads']:>4}{r['conns']:>7}"
              f"{rate:>10.3f}{100*(rate/base-1):>+9.2f}%{float(r['srv_cores']):>11.2f}{float(r['p99']):>9.2f}")
    print()
print("READ IT THIS WAY: the first rung on which the rate STOPS rising while the generator is still")
print("growing is the first rung on which the server is the bottleneck. Measure there or above it.")
print("If the rate is still climbing at the last rung, this lane has no server-bound geometry inside")
print("its allocation and no rate number from it may be quoted -- only instructions per operation.")

# THE LADDER PICKS THE GEOMETRY, and the rest of the run reads it out of a file rather than out of
# a decision somebody made from the table by eye at two in the morning. The chosen rung is the
# FIRST one within 2% of the best rate any rung reached -- the start of the plateau, because more
# generator past that point buys nothing and only adds threads to schedule. A ladder that is still
# climbing at its last rung has no plateau, and says so: PLATEAU=no means every rate in this run is
# a measurement of memtier and only instructions per operation may be read.
import statistics, os
best_rung, plateau = None, True
per, shape = {}, {}
for r in rows:
    per.setdefault(r['rung'], {})[r['cell']] = float(r['rate'])
    shape[r['rung']] = r
rungs = sorted(per, key=int)
score = {k: statistics.mean(v.values()) for k, v in per.items()}
top = max(score.values())

def cpus(spec):
    n = 0
    for part in spec.replace('+', ',').split(','):
        if '-' in part:
            a, b = part.split('-', 1); n += int(b) - int(a) + 1
        elif part.strip():
            n += 1
    return n

# AMONG RUNGS THAT ARE THE SAME SPEED, TAKE THE LEAST OVERSUBSCRIBED ONE. Rate alone would happily
# choose the rung where eight generator threads time-slice four logical cpus, because its MEAN can
# match while its variance is the thing that broke the last null: two memtier threads sharing one
# hardware thread are rationed by the scheduler, and the scheduler's decisions land in the rate as
# visit-to-visit swing. Threads per logical cpu is that ratio, and the smallest one wins the tie.
cands = [k for k in rungs if score[k] >= 0.98 * top]
best_rung = min(cands, key=lambda k: (float(shape[k]['threads']) / max(1, cpus(shape[k]['cores'])),
                                      -score[k]))
if best_rung == rungs[-1] and len(rungs) > 1 and score[rungs[-1]] > 1.02 * score[rungs[-2]]:
    plateau = False
row = next(r for r in rows if r['rung'] == best_rung)
env = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), 'satcheck.env')
with open(env, 'w') as f:
    f.write(f"CLICORES={row['cores'].replace('+', ',')}\nTHREADS={row['threads']}\n"
            f"CONNS={int(row['conns'])//int(row['threads'])}\nPLATEAU={'yes' if plateau else 'no'}\n")
print(f"\nCHOSEN RUNG {best_rung}: cpus {row['cores'].replace('+', ',')}, {row['threads']} threads x "
      f"{int(row['conns'])//int(row['threads'])} connections; plateau={'yes' if plateau else 'no'}")
print(f"written to {env}; every rate phase in this run reads its geometry from there.")
PY
