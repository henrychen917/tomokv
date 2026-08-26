#!/bin/bash
# PRE-PUSH GATE for tomokv-cpp (pure 2s baseline).
#
#   tests/gate.sh quick   loopback only, ~3 min: build (release+ASAN), footprint locks, boot
#                         matrix, smoke, torture, RYOW, atomic torn/mixed-write/window gates,
#                         shutdown invariants, counter-fired assertions, idle-CPU ceiling. Runs on
#                         any machine.
#   tests/gate.sh full    quick + torture-under-ASAN + NIC regression cells vs tests/gate_refs.txt
#                         (needs the 25GbE netns rig and the scratchpad niclib).
#
# The vacuous-validation rule is load-bearing here: every section proves its mechanism FIRED
# (counters, accepts, direct>0), not merely that nothing crashed. A gate that can pass while
# testing nothing is worse than no gate.
set -u
cd "$(dirname "$0")/.."
TIER=${1:-quick}
PORT=${GATE_PORT:-7899}
CORES=${GATE_CORES:-0-7}
NCORES=$(taskset -c "$CORES" nproc)
if [ "$NCORES" -ge 8 ]; then GATE_RATIO=6:$((NCORES-6))
else GATE_RATIO=$(((NCORES+1)/2)):$((NCORES-(NCORES+1)/2)); fi
PASS=0; FAIL=0
say(){ printf '  %-52s %s\n' "$1" "$2"; }
ok(){ say "$1" "ok"; PASS=$((PASS+1)); }
bad(){ say "$1" "FAIL${2:+ ($2)}"; FAIL=$((FAIL+1)); }

# ---- 1. builds (the static_asserts on sizeof(Op)/sizeof(Client) gate here) -------------------
make -j >/dev/null 2>&1 && ok "release build (+footprint locks)" || bad "release build"
ASAN=/tmp/tomokv-gate-asan
g++ -std=c++20 -O1 -g -fsanitize=address -march=native -pthread -I. \
    src/main.cc src/cmd/*.cc src/snapshot/*.cc -o $ASAN -luring -pthread 2>/dev/null \
    && ok "ASAN build" || bad "ASAN build"
g++ -std=c++20 -O2 -I. tests/config_parser_test.cc -o /tmp/tomokv-config-parser-test \
    && /tmp/tomokv-config-parser-test \
    && ok "Redis config quoting + mid-value #" || bad "Redis config quoting + mid-value #"
python3 tools/gen_acl_categories.py --redis-root "${REDIS74_ROOT:-/tmp/claude-1000/redis74}" \
    --check src/cmd/acl_categories_generated.h \
    && ok "generated Redis 7.4 ACL categories" || bad "generated Redis 7.4 ACL categories"

# ---- 2. boot matrix: deleted flags stay dead; live grammar boots ------------------------------
./build/tomokv --mode 3s      2>&1 | grep -q "unknown" && ok "reject --mode (flag deleted)" || bad "reject --mode (flag deleted)"
./build/tomokv --spread 4:4   2>&1 | grep -q "unknown"  && ok "reject --spread"    || bad "reject --spread"
./build/tomokv --nodes 2      2>&1 | grep -q "unknown"  && ok "reject --nodes"     || bad "reject --nodes"
./build/tomokv --ratio 4:4:2  2>&1 | grep -q "deleted"  && ok "reject 3-part ratio"|| bad "reject 3-part ratio"
./build/tomokv --conf /nonexistent-conf 2>&1 | grep -q "cannot open" && ok "reject missing conf" || bad "reject missing conf"
printf 'florb 1\n' > /tmp/gate-bad.conf
./build/tomokv /tmp/gate-bad.conf 2>&1 | grep -q "unknown argument" && ok "reject bad conf key" || bad "reject bad conf key"
printf 'aclfile /tmp/gate-users.acl\nuser alice on nopass ~* &* +@all\n' > /tmp/gate-acl-mixed.conf
./build/tomokv /tmp/gate-acl-mixed.conf 2>&1 | grep -q \
    "Configuring Redis with users defined in redis.conf and at the same setting an ACL file path is invalid" \
    && ok "reject aclfile + conf user lines" || bad "reject aclfile + conf user lines"

boot(){ # binary -> pid ; server log to $SRVLOG
  local bin=$1; shift
  (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null \
      && { say "port $PORT pre-boot guard" "FAIL (already accepting)"; return 1; }
  SRVLOG=$(mktemp /tmp/gate-srv.XXXXXX)
  timeout 900 taskset -c $CORES "$bin" --port $PORT --bind 127.0.0.1 --shards 16 --ratio $GATE_RATIO "$@" \
      > "$SRVLOG" 2>&1 &
  SRV=$!
  for _ in $(seq 50); do ./build/tomokv --help >/dev/null 2>&1
    (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && return 0; sleep 0.2; done
  return 1
}
stop(){ kill -TERM $SRV 2>/dev/null; wait $SRV 2>/dev/null; sleep 5; }

# ---- 3. correctness: smoke + torture + RYOW on the release build ------------------------------
boot ./build/tomokv || bad "release boot"
python3 tests/../tests/torture.py 127.0.0.1 $PORT >/tmp/gate-tort.txt 2>&1 \
    && ok "torture battery" || bad "torture battery" "see /tmp/gate-tort.txt"
python3 tests/ryow.py 127.0.0.1 $PORT >/tmp/gate-ryow.txt 2>&1 \
    && ok "RYOW battery" || bad "RYOW battery" "see /tmp/gate-ryow.txt"
python3 tests/acl_categories.py 127.0.0.1 $PORT >/tmp/gate-acl-categories.txt 2>&1 \
    && ok "ACL category runtime table" || bad "ACL category runtime table" "see /tmp/gate-acl-categories.txt"
python3 tests/acl.py 127.0.0.1 $PORT - >/tmp/gate-acl-nofile.txt 2>&1 \
    && ok "ACL LOAD/SAVE no-file errors" || bad "ACL LOAD/SAVE no-file errors" "see /tmp/gate-acl-nofile.txt"
# idle-CPU ceiling: after the batteries, an idle server must not burn cores
C0=$(awk '{print $14+$15}' /proc/$SRV/stat 2>/dev/null || echo 0); sleep 5
C1=$(awk '{print $14+$15}' /proc/$SRV/stat 2>/dev/null || echo 0)
J=$((C1-C0))   # jiffies over 5s across all threads; 8 threads @ 50ms-timeout heartbeat ~= tens
[ "$J" -lt 200 ] && ok "idle CPU ceiling ($J jiffies/5s)" || bad "idle CPU ceiling" "$J jiffies/5s"
stop
# shutdown invariants + fired counters, from the TERM dump
grep -q "stuck: live_conns=0 rob_not_quiesced=0 unsent_bytes_pending=0" "$SRVLOG" \
    && ok "shutdown invariants (nothing stuck)" || bad "shutdown invariants"
D=$(grep -oE "direct=[0-9]+" "$SRVLOG" | head -1 | cut -d= -f2)
[ -n "$D" ] && [ "$D" -gt 0 ] && ok "direct-reply fired (direct=$D)" || bad "direct-reply fired"
R=$(grep -oE "dispatched=[0-9]+" "$SRVLOG" | cut -d= -f2)
E=$(grep -oE "executed=[0-9]+"  "$SRVLOG" | cut -d= -f2)
[ -n "$R" ] && [ "$R" = "$E" ] && ok "dispatched==executed ($R)" || bad "dispatched==executed" "$R vs $E"

# Explicit ON boot plus the non-vacuous epoch-MVCC gates. atomic_torn includes its own OFF control,
# predecessor/promotion counters, overlapping writers, window liveness, and live CONFIG flips.
boot ./build/tomokv --atomic 1 || bad "atomic release boot"
python3 tests/atomic_torn.py 127.0.0.1 $PORT >/tmp/gate-atomic-torn.txt 2>&1 \
    && ok "atomic torn/window battery" || bad "atomic torn/window battery" "see /tmp/gate-atomic-torn.txt"
python3 tests/atomic_ryow.py 127.0.0.1 $PORT >/tmp/gate-atomic-ryow.txt 2>&1 \
    && ok "atomic RYOW/mixed-write battery" || bad "atomic RYOW/mixed-write battery" "see /tmp/gate-atomic-ryow.txt"
stop
grep -q "stuck: live_conns=0 rob_not_quiesced=0 unsent_bytes_pending=0" "$SRVLOG" \
    && ok "atomic shutdown invariants" || bad "atomic shutdown invariants"

# ---- feature batteries: every shipped feature's directed test, BOTH atomic settings -----------
# The gate accumulates a section per landed feature (owner rule). Each test is directed and
# asserts its own mechanisms fired; the boot covers multi/blocking/pubsub+sharded/lua/limits.
for AT in 0 1; do
  boot ./build/tomokv --atomic $AT || bad "feature battery boot (atomic $AT)"
  for t in multi_exec blocking pubsub lua_scripting limits; do
    python3 tests/$t.py 127.0.0.1 $PORT >/tmp/gate-$t-$AT.txt 2>&1 \
        && ok "$t battery (atomic $AT)" || bad "$t battery (atomic $AT)" "see /tmp/gate-$t-$AT.txt"
  done
  stop
  grep -q "stuck: live_conns=0 rob_not_quiesced=0 unsent_bytes_pending=0" "$SRVLOG" \
      && ok "feature shutdown invariants (atomic $AT)" || bad "feature shutdown invariants (atomic $AT)"
done

# ---- auth + audit DEBUG (purpose-booted; each test asserts its gate actually opened) -----------
./build/tomokv --protected-mode maybe 2>&1 | grep -q "protected-mode wants" \
    && ok "reject bad protected-mode" || bad "reject bad protected-mode"
./build/tomokv --enable-debug-command maybe 2>&1 | grep -q "enable-debug-command wants" \
    && ok "reject bad enable-debug-command" || bad "reject bad enable-debug-command"
boot ./build/tomokv --requirepass gatepass || bad "auth purpose boot"
python3 tests/auth.py 127.0.0.1 $PORT gatepass >/tmp/gate-auth.txt 2>&1 \
    && ok "AUTH/HELLO/protected state machine" || bad "AUTH/HELLO/protected state machine" "see /tmp/gate-auth.txt"
stop
ACL_DIR=$(mktemp -d /tmp/gate-acl.XXXXXX)
ACL_FILE="$ACL_DIR/users.acl"
: > "$ACL_FILE"
boot ./build/tomokv --aclfile "$ACL_FILE" || bad "ACL purpose boot"
python3 tests/acl.py 127.0.0.1 $PORT "$ACL_FILE" >/tmp/gate-acl.txt 2>&1 \
    && ok "ACL battery (atomic off)" || bad "ACL battery (atomic off)" "see /tmp/gate-acl.txt"
stop
ACL_ATOMIC_FILE="$ACL_DIR/users-atomic.acl"
: > "$ACL_ATOMIC_FILE"
boot ./build/tomokv --aclfile "$ACL_ATOMIC_FILE" --atomic 1 || bad "ACL atomic purpose boot"
python3 tests/acl.py 127.0.0.1 $PORT "$ACL_ATOMIC_FILE" >/tmp/gate-acl-atomic.txt 2>&1 \
    && ok "ACL battery (atomic on)" || bad "ACL battery (atomic on)" "see /tmp/gate-acl-atomic.txt"
stop
DEBUG_DIR=$(mktemp -d /tmp/gate-debug.XXXXXX)
boot ./build/tomokv --enable-debug-command local --dir "$DEBUG_DIR" --dbfilename reload.tomo \
    || bad "DEBUG purpose boot"
python3 tests/debug.py 127.0.0.1 $PORT >/tmp/gate-debug.txt 2>&1 \
    && ok "DEBUG toggle/reload battery" || bad "DEBUG toggle/reload battery" "see /tmp/gate-debug.txt"
stop

if [ "$TIER" = quick ]; then
  echo; echo "GATE(quick): $PASS ok, $FAIL FAIL"; [ $FAIL -eq 0 ] || exit 1; exit 0
fi

# ---- 4. full tier: torture under ASAN ---------------------------------------------------------
boot $ASAN --atomic 1 || bad "ASAN boot"
python3 tests/torture.py 127.0.0.1 $PORT >/tmp/gate-tort-asan.txt 2>&1 \
    && ok "torture under ASAN" || bad "torture under ASAN"
python3 tests/ryow.py 127.0.0.1 $PORT >/tmp/gate-ryow-asan.txt 2>&1 \
    && ok "RYOW under ASAN" || bad "RYOW under ASAN"
python3 tests/atomic_torn.py 127.0.0.1 $PORT >/tmp/gate-atomic-torn-asan.txt 2>&1 \
    && ok "atomic torn/window under ASAN" || bad "atomic torn/window under ASAN"
python3 tests/atomic_ryow.py 127.0.0.1 $PORT >/tmp/gate-atomic-ryow-asan.txt 2>&1 \
    && ok "atomic RYOW under ASAN" || bad "atomic RYOW under ASAN"
stop
grep -q "ERROR: AddressSanitizer" "$SRVLOG" && bad "ASAN clean" || ok "ASAN clean"

# ---- 4b. full tier: zero-copy borrow lifetime (release+ASAN) ----------------------------------
zcboot(){ SRVLOG=$(mktemp /tmp/gate-srv.XXXXXX)
  (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null \
      && { say "port $PORT pre-boot guard" "FAIL (already accepting)"; return 1; }
  timeout 900 taskset -c $CORES "$1" --port $PORT --bind 127.0.0.1 --shards 16 --ratio $GATE_RATIO       --zc-min 16384 > "$SRVLOG" 2>&1 &
  SRV=$!
  for _ in $(seq 50); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && return 0; sleep 0.2; done
  return 1
}
zcboot ./build/tomokv || bad "zc boot"
python3 tests/zc.py 127.0.0.1 $PORT >/tmp/gate-zc.txt 2>&1     && ok "zc borrow battery" || bad "zc borrow battery" "see /tmp/gate-zc.txt"
stop
ZS=$(grep -oE "zc_sends=[0-9]+" "$SRVLOG" | cut -d= -f2)
[ -n "$ZS" ] && [ "$ZS" -gt 0 ] && ok "zc fired (zc_sends=$ZS)" || bad "zc fired"
zcboot $ASAN || bad "zc ASAN boot"
python3 tests/zc.py 127.0.0.1 $PORT >/tmp/gate-zc-asan.txt 2>&1     && ok "zc borrow battery under ASAN" || bad "zc borrow battery under ASAN"
stop
grep -q "ERROR: AddressSanitizer" "$SRVLOG" && bad "zc ASAN clean" || ok "zc ASAN clean"

# ---- 5. full tier: NIC regression cells vs pinned refs ----------------------------------------
SPD=${GATE_SCRATCH:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad}
if [ -f "$SPD/niclib.sh" ] && [ -f tests/gate_refs.txt ]; then
  ( set -u
    . "$SPD/niclib.sh"; . "$SPD/procsafe.sh"
    NIC_PORT=6380; NIC_CLI_BIN=$SPD/bins/cli; BL_LOGDIR=$(mktemp -d)
    nic_assert_link || exit 9
    nic_tune >/dev/null 2>&1 || true
    CPP=$(pwd)/build/tomokv; KMAX=2000000
    run_cell(){ # name cores ratio shards pipe lg t conns ratio_rw
      nic_kill_srv $NIC_PORT
      # --protected-mode no: protected mode (vanilla-compat: no bind check) denies non-local
      # peers when no password is set — which is every NIC cell.
      NIC_SRV_CORES=$2 nic_boot "gate_$1" "$CPP" --port $NIC_PORT --bind $NIC_SRV_IP --ratio $3 --shards $4 --protected-mode no || return 1
      NIC_TO=1200 NIC_LG_CORES=$6 nic_memtier -t 16 -c 4 --pipeline=32 --ratio=1:0 --key-pattern=P:P \
          --key-minimum=1 --key-maximum=$KMAX -n allkeys -d 64 >/dev/null 2>&1
      local f=$BL_LOGDIR/g_$1.log
      NIC_TO=90 NIC_LG_CORES=$6 nic_memtier -t $7 -c $(( $8 / $7 )) --pipeline=$5 --ratio=$9 \
          --key-pattern=R:R --key-minimum=1 --key-maximum=$KMAX --test-time=15 -d 64 \
          --distinct-client-seed > "$f" 2>&1
      tr '\r' '\n' < "$f" | grep -E '^Totals' | tail -1 | awk '{print $2}'
    }
    RC=0
    while read -r name cores ratio shards pipe lg t conns rw ref; do
      case "$name" in \#*|"") continue;; esac
      got=$(run_cell "$name" "$cores" "$ratio" "$shards" "$pipe" "$lg" "$t" "$conns" "$rw")
      python3 - "$name" "$got" "$ref" <<'PY' || RC=1
import sys
name, got, ref = sys.argv[1], float(sys.argv[2] or 0), float(sys.argv[3])
d = (got - ref) / ref * 100
status = "ok" if d >= -3.0 else "FAIL"
print(f"  regression {name:<28} {got/1e6:.2f}M vs ref {ref/1e6:.2f}M ({d:+.1f}%)  {status}")
sys.exit(0 if d >= -3.0 else 1)
PY
    done < tests/gate_refs.txt
    nic_kill_srv $NIC_PORT
    exit $RC
  )
  case $? in
    0) ok "NIC regression cells (all within -3%)";;
    9) say "NIC regression cells" "SKIPPED (no rig)";;
    *) bad "NIC regression cells";;
  esac
else
  say "NIC regression cells" "SKIPPED (no rig/refs)"
fi

echo; echo "GATE(full): $PASS ok, $FAIL FAIL"
[ $FAIL -eq 0 ] || exit 1
