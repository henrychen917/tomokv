#!/bin/bash
# WHAT IS READ-LOCAL WORTH HERE AT ALL?
#
# This lane exists to stop the write ring from overflowing, and it succeeds: overflow goes to zero,
# demotions go to zero, and the read-local hit share goes to 100%. It then costs +43 instructions
# per write and, at 70% writes, +249 per read -- far more than the tag sweep itself can account for
# (the microbenchmark's worst case is +90 per rejected probe). The unexplained remainder is the
# difference between SERVING a read locally and DEMOTING it to its owner, and until that is
# measured the lane cannot say whether it bought the wrong thing or bought the right thing badly.
#
# One binary, one geometry, one knob: --read-local 0 against --read-local 1 on the BASE arm.
#   1:1    alternating -- the ring never overflows here, so read-local runs at ~100% hit share and
#          this cell is the value of the FEATURE with nothing in its way
#   55:45  blocked -- the regime where the sixteen-slot ring gives up, so read-local is mostly not
#          running even when it is switched on
#
# If read-local off is FASTER at 1:1, then serving a read locally costs more than demoting it in
# this geometry, and sizing the ring correctly only makes a losing path run more often -- which
# would put the defect somewhere this lane must not fix, and would be the reason for its verdict
# rather than an aside to it.
#
#   rl_value.sh <bin> <outCsv> [rounds]
set -u
BIN="$1"; OUT="$2"; ROUNDS="${3:-2}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
KEYMAX=${KEYMAX:-200000}
SECS=${SECS:-15}
SHARDS=${SHARDS:-2}
THREADS=${THREADS:-8}
CONNS=${CONNS:-64}
TMP=${TMP:-/tmp/ringsize-rlv}
mkdir -p "$TMP"
[ -s "$OUT" ] || echo "round,visit,arm,cell,rate,p50,p99,cmds,instr,cycles,hits,demoted,fallbacks,srv_cores,mux" > "$OUT"

visit(){ # visit <rl> <arm> <round> <visitIndex>
  local rl="$1" arm="$2" round="$3" vi="$4"
  RL="$rl" boot_srv "$BIN" "$TMP/srv-$arm-$round-$vi.log" --atomic 0 --enable-debug-command yes \
    || return 1
  run_cli "$TMP/pre-$arm-$round-$vi.txt" -s 127.0.0.1 -p "$PORT" --hide-histogram \
      --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=P:P --ratio=1:0 \
      -t 4 -c 4 --pipeline=32 -n $((KEYMAX/16)) || { stop_srv; return 1; }
  for spec in "alt:1:1" "blk:55:45"; do
    local cell="${spec%%:*}" ratio="${spec#*:}"
    local h0 f0 a0 c0 j0 t0
    h0=$(info_field read_local_hits); f0=$(info_field read_local_fallback_inflight_write)
    a0=$(info_field read_local_fallbacks); c0=$(info_field total_commands_processed)
    j0=$(awk '{print $14+$15}' /proc/$SRV/stat); t0=$(date +%s.%N)
    local rf="$TMP/$arm-$round-$vi-$cell.txt" pf="$TMP/perf-$arm-$round-$vi-$cell.txt"
    perf stat -e instructions,cycles -x, -o "$pf" -p "$SRV" 2>/dev/null &
    local PERF=$!
    start_cli "$rf" -s 127.0.0.1 -p "$PORT" --hide-histogram --key-maximum=$KEYMAX \
        --key-minimum=1 --data-size=32 --key-pattern=R:R --ratio="$ratio" \
        -t $THREADS -c $CONNS --pipeline=32 --test-time=$SECS \
      || { kill -INT "$PERF" 2>/dev/null; stop_srv; return 1; }
    wait "$MEMTIER_PID" 2>/dev/null
    kill -INT "$PERF" 2>/dev/null; wait "$PERF" 2>/dev/null
    local j1 t1 srvcpu rate p50 p99 h1 f1 a1 c1 ins cyc mux
    j1=$(awk '{print $14+$15}' /proc/$SRV/stat); t1=$(date +%s.%N)
    srvcpu=$(python3 -c "print(f'{(($j1-$j0)/100.0)/max(0.001,$t1-$t0):.2f}')")
    rate=$(grep -E '^Totals' "$rf" | awk '{print $2}')
    p50=$(grep -E '^Totals' "$rf" | awk '{print $6}')
    p99=$(grep -E '^Totals' "$rf" | awk '{print $7}')
    h1=$(info_field read_local_hits); f1=$(info_field read_local_fallback_inflight_write)
    a1=$(info_field read_local_fallbacks); c1=$(info_field total_commands_processed)
    ins=$(grep -m1 ',instructions,' "$pf" | cut -d, -f1)
    cyc=$(grep -m1 ',cycles,' "$pf" | cut -d, -f1)
    mux=$(awk -F, 'NF>4 && $5 ~ /^[0-9]/ {print $5}' "$pf" | sort -n | head -1)
    assert_cell_did_work "$rate" "$((c1-c0))" "$t0" "$t1" "rlv $cell $arm r$round v$vi" "$rf" \
      || { stop_srv; return 1; }
    echo "$round,$vi,$arm,$cell,$rate,$p50,$p99,$((c1-c0)),${ins:-0},${cyc:-0},$((h1-h0)),$((f1-f0)),$((a1-a0)),${srvcpu:-0},${mux:-100}" >> "$OUT"
  done
  stop_srv
}

for r in $(seq 1 "$ROUNDS"); do
  visit 1 RL1 "$r" 1 || exit 1
  visit 0 RL0 "$r" 2 || exit 1
  visit 0 RL0 "$r" 3 || exit 1
  visit 1 RL1 "$r" 4 || exit 1
  echo "rlvalue round $r done @ $(date +%T)"
done

python3 - "$OUT" <<'PY'
import csv, statistics as st, sys
rows = list(csv.DictReader(open(sys.argv[1])))
for r in rows:
    for k in ('rate','p50','p99','cmds','instr','cycles','hits','demoted','fallbacks','srv_cores'):
        r[k] = float(r[k])
    c = r['cmds'] or 1
    r['instr_op'] = r['instr']/c; r['cyc_op'] = r['cycles']/c
    r['ipc'] = r['instr']/r['cycles'] if r['cycles'] else float('nan')
    r['local_pct'] = 100.0*r['hits']/(r['hits']+r['fallbacks']) if (r['hits']+r['fallbacks']) else 0.0
def med(cell, arm, f):
    v=[r[f] for r in rows if r['cell']==cell and r['arm']==arm]
    return st.median(v) if v else float('nan')
LBL={'alt':'1:1 alternating (ring never fills)','blk':'55:45 blocked (ring gives up)'}
hdr=(f"{'cell':<34}{'read-local':<12}{'M ops/s':>9}{'instr/op':>10}{'cyc/op':>9}{'IPC':>7}"
     f"{'p99 ms':>8}{'local %':>9}{'srv cores':>11}")
print(hdr); print('-'*len(hdr))
for c in ('alt','blk'):
    for arm,lab in (('RL0','off'),('RL1','on')):
        print(f"{LBL[c]:<34}{lab:<12}{med(c,arm,'rate')/1e6:>9.3f}{med(c,arm,'instr_op'):>10.0f}"
              f"{med(c,arm,'cyc_op'):>9.0f}{med(c,arm,'ipc'):>7.3f}{med(c,arm,'p99'):>8.2f}"
              f"{med(c,arm,'local_pct'):>8.1f}%{med(c,arm,'srv_cores'):>11.2f}")
    def d(f):
        a,b = med(c,'RL0',f), med(c,'RL1',f)
        return (b-a)/a*100.0 if a else float('nan')
    print(f"{'':<34}{'on vs off':<12}{d('rate'):>+8.2f}%{d('instr_op'):>+9.2f}%"
          f"{d('cyc_op'):>+8.2f}%{d('ipc'):>+6.2f}%")
    print()
print("READ IT THIS WAY: the 1:1 row is read-local with nothing in its way -- the ring never fills,")
print("so the feature runs at its full hit share. If 'on' is not faster THERE, then serving a read")
print("locally costs more than demoting it in this geometry, and a correctly sized ring only makes")
print("that path run more often.")
PY
