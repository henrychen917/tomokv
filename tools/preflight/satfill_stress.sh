#!/bin/bash
# satfill_stress.sh — saturating-fill crash gate, promoted 2026-08-11 from the job harness that
# caught the flatstore insert-full P0 (task #117) per the owner rule: a harness that catches a
# bug joins the gate.
#
# THE BUG IT GUARDS: a perfectly uniform 40M-key P:P fill (8 threads, pipeline 32, SET flood)
# synchronizes every flat table's growth-threshold crossing into a resize STORM; with only
# (100-FLAT_LOAD_PCT)% headroom per table, the coordinator's queue-service time races the flood
# and a losing table's insert wraps a full table. Pre-fix that was
#     Guru Meditation: flatstore INSERT: table full (262144 slots) #flatstore.c:258
# at ~10%/fill (4/50 on 2026-08-11, ALWAYS at the 262144 rung). Post-fix the insert must WAIT
# out the rebuild (witnessed) and the fill completes.
#
# Grading: any panic/crash in any iteration = FAIL; any fill not reaching exactly 40M keys =
# FAIL (a dead server or silent loss both surface here); wait-path witnesses are REPORTED per
# iteration when the binary exposes them (engagement is probabilistic ~10%/fill, so zero
# engagement in one run is normal — the fix's own validation runs SATFILL_N=20 twice).
# Port 7971 exclusive (#73: no port sharing between suites).
set -u
SD="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=tools/preflight/preflight_lib.sh
. "$SD/preflight_lib.sh"
J="${TOMO_JOB_DIR:-/tmp/satfill_$$}"; mkdir -p "$J"
BIN="${TOMO_BIN:?satfill_stress.sh: TOMO_BIN required}"
PORT=5971
RES="${TOMO_RESULT_FILE:-$J/satfill_stress.out}"; : > "$RES"
CLI(){ "$SD/../../src/redis-cli" -p $PORT "$@" 2>/dev/null || redis-cli -p $PORT "$@" 2>/dev/null; }
MTB=$(command -v memtier_benchmark || echo /usr/local/bin/memtier_benchmark)
KB=$J/redis-sfl; cp "$BIN" "$KB"; chmod +x "$KB"
N=${SATFILL_N:-10}
FAILS=0; note(){ echo "  $1" | tee -a "$RES"; }
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}
kb_kill(){ pkill -9 -x redis-sfl 2>/dev/null; }
trap 'kb_kill' EXIT TERM INT HUP

waits_total=0; waits_seen=0
for it in $(seq 1 "$N"); do
  kb_kill
  for _ in $(seq 1 40); do ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT" || break; sleep 0.25; done
  rm -rf "$J/scr"; mkdir -p "$J/scr"
  taskset -c "$SERVER_CORES" "$KB" --port $PORT --bind 127.0.0.1 --dir "$J/scr" --tomokv-nodes 2 --tomokv-pin-mode ccd \
    --tomokv-thread-mode static --tomokv-thread-io 8 --tomokv-thread-ex 8 \
    --save '' --appendonly no --protected-mode no --logfile "$J/scr/s.log" >/dev/null 2>&1 &
  SPID=$!
  up=0; for _ in $(seq 1 150); do CLI ping | grep -q PONG && { up=1; break; }; sleep 0.1; done
  if [ $up != 1 ]; then note "FAIL iter$it boot"; FAILS=$((FAILS+1)); continue; fi
  if ! preflight_assert_standard_boot "$J/scr/s.log" "$SPID" 8 8; then
    note "FAIL iter$it 2x16c composed-L3/core-range assertion"; FAILS=$((FAILS+1)); continue
  fi
  taskset -c "$LOAD_CORES" "$MTB" -s 127.0.0.1 -p $PORT --hide-histogram --ratio=1:0 -d 32 \
    --key-pattern=P:P --key-minimum=1 --key-maximum=40000000 -n allkeys -c 1 -t 8 --pipeline 32 \
    > "$J/iter$it.fill.log" 2>&1
  if grep -qE "table full|REDIS BUG REPORT|Guru Meditation" "$J/scr/s.log" 2>/dev/null; then
    note "FAIL iter$it PANIC: $(grep -m1 -oE 'Guru Meditation: [^#]*' "$J/scr/s.log")"
    cp "$J/scr/s.log" "$J/iter$it.crash.srv.log"
    FAILS=$((FAILS+1)); continue
  fi
  db=$(timeout 10 "$SD/../../src/redis-cli" -p $PORT dbsize 2>/dev/null)
  if [ "${db:-0}" != 40000000 ]; then
    note "FAIL iter$it fill-integrity db=${db:-dead} want=40000000"; FAILS=$((FAILS+1)); continue
  fi
  w=$(CLI info everything | grep -oE "flat_insert_full_waits:[0-9]+" | cut -d: -f2)
  if [ -n "${w:-}" ]; then waits_seen=1; waits_total=$((waits_total + w)); fi
  note "PASS iter$it db=40000000 waits=${w:-n/a}"
done
kb_kill

if [ "$waits_seen" = 1 ]; then
  note "wait-path witness total across $N fills: $waits_total (0 is normal for one run; the race is ~10%/fill)"
else
  note "wait-path witness not exposed by this binary (pre-fix build) — panic detection is the only guard"
fi
if [ "$FAILS" = 0 ]; then
  echo "SATFILL-STRESS PASS" | tee -a "$RES"
else
  echo "SATFILL-STRESS FAIL ($FAILS)" | tee -a "$RES"
fi
