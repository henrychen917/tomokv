#!/bin/bash
# Validate the reclaim under 2 SIMULATED NUMA nodes (--tomokv-nodes 2). This is the only
# multi-node coverage available on a single-CCD box: it exercises the per-node flat TABLES, the
# per-node reclaim walk (flatReclaimAll iterates n_node_dbs), node-scoped worker ranges in the grace,
# and the numa>=2 flip/balancer paths — even though the physical coherence topology is still one CCD.
J=/tmp/tomo_pfjob; P=/home/user/Projects
# PORT-SAFETY: boot() already re-runs cleanup_n2, but that reaps by pid only — a leaked/foreign
# server on :7978 would still REUSEPORT-join. Gate on the port before boot + verify pid identity
# after (boot currently trusts `sleep 1`/`sleep 3`).
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
CLI="$P/redis/src/redis-cli -p 7978"
CLI_BIN="$P/redis/src/redis-cli"   # bare path (no -p) for server_identity_ok
MT="taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p 7978 --hide-histogram"
OUT=$J/numa2_validate.out; : > $OUT
PASS=0; FAIL=0
ok(){ echo "  PASS: $1" >> $OUT; PASS=$((PASS+1)); }
bad(){ echo "  FAIL: $1" >> $OUT; FAIL=$((FAIL+1)); }

# ee451 2026-07-29: PRIVATE BINARY NAME + OUR-OWN-PID lifecycle.
# This suite was one of the three still reaping the shared name. `pkill -9 -x redis-server` was two
# defects at once: on this shared box it SIGKILLed whatever another session was running (a SIGKILL
# leaves no crash marker, so the victim reads as a mysterious server defect), and once preflight
# started staging the binary under a private name it stopped matching OUR server too -- so every
# boot leaked one, and a leaked server inherits withbox.sh's box-lock fd and holds the shared box
# lock forever. Copy once to a unique comm, kill our recorded pid, trap every exit path.
SRCBIN=${TOMO_BIN:-$J/stable-w/src/redis-server}
N2BIN=$J/redis-n2; cp -f "$SRCBIN" "$N2BIN" 2>/dev/null; chmod +x "$N2BIN" 2>/dev/null
N2PID=""
N2_MTPID=""
cleanup_n2(){
  if [ -n "${N2_MTPID:-}" ]; then
    kill -9 "$N2_MTPID" 2>/dev/null
    wait "$N2_MTPID" 2>/dev/null
    N2_MTPID=""
  fi
  if [ -n "${N2PID:-}" ]; then
    kill -9 "$N2PID" 2>/dev/null
    wait "$N2PID" 2>/dev/null
    N2PID=""
  fi
}
trap cleanup_n2 EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

boot(){ # $1 = numa nodes
  cleanup_n2; sleep 1; rm -rf $J/n2data; mkdir -p $J/n2data; : > $J/numa2.log
  # PORT-SAFETY: refuse to boot while any listener still holds :7978.
  wait_port_free 7978 || { echo "  boot: :7978 still has a listener before boot (SO_REUSEPORT split risk)" >> $OUT; return 1; }
  taskset -c 0-7 "$N2BIN" --port 7978 --dir $J/n2data --tomokv-nodes $1 \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-thread-mode auto \
    --save '' --appendonly no --protected-mode no --enable-debug-command yes \
    --logfile $J/numa2.log --loglevel notice >/dev/null 2>&1 &
  N2PID=$!
  sleep 3
  for i in $(seq 1 30); do
    if timeout 2 $CLI ping 2>/dev/null | grep -q PONG; then
      # IDENTITY: every fresh INFO conn must land on OUR pid or every measurement is a blend.
      server_identity_ok "$CLI_BIN" 7978 "$N2PID" || { echo "  SO_REUSEPORT split on :7978 — measurement void" >> $OUT; return 1; }
      return 0
    fi
    sleep 1
  done
  return 1; }
# rss() read `ps -C redis-server | head -1` -- on a shared box that is whichever server sorts first,
# i.e. potentially ANOTHER SESSION'S process. Read our own /proc entry instead.
rss(){ awk '/VmRSS/{print int($2/1024)}' /proc/$N2PID/status 2>/dev/null; }

echo "=== NUMA=2 (simulated nodes) ===" >> $OUT
if ! boot 2; then bad "numa=2 boot"; tail -12 $J/numa2.log >> $OUT; else
  ok "boots with numa-nodes=2"
  echo "  node/worker layout: $(grep -c 'NUMA-local' $J/numa2.log) workers pinned" >> $OUT

  # A. seed + integrity across both node tables
  $MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=1000000 -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
  n=$($CLI dbsize); [ "$n" -ge 1000000 ] 2>/dev/null && ok "seeded across nodes (dbsize=$n)" || bad "seed dbsize=$n"
  for i in 1 2 3 4 5; do $CLI set n2:$i "val-$i-payload" >/dev/null; done
  # Re-latch AFTER the sentinel writes: the churn below is pure overwrite, so dbsize must be
  # invariant from here on. Latching before these 5 SETs made the check demand 1000001 == 1000006
  # and report the harness's own sentinels as a server bug.
  n=$($CLI dbsize)

  # B. sustained overwrite churn — the leak path, now with 2 node tables + 2 reclaim walks
  R0=$(rss)
  CHURN_OPS=$($MT --test-time=120 --ratio=1:0 -d 64 --key-pattern=R:R --key-maximum=1000000 -t 8 -c 25 --pipeline 32 --distinct-client-seed 2>&1 \
    | awk '/^Totals/{print $2; exit}')
  case "${CHURN_OPS:-}" in
    ''|0|0.0|0.00) bad "INVALID: numa=2 churn produced no nonzero Totals ops/s (${CHURN_OPS:-empty})" ;;
    *) echo "  churn ops/s: $CHURN_OPS" >> $OUT ;;
  esac
  R1=$(rss)
  if [[ "$R0" =~ ^[0-9]+$ && "$R1" =~ ^[0-9]+$ ]]; then
    G=$((R1-R0))
    echo "  rss ${R0}MB -> ${R1}MB (+${G}MB)" >> $OUT
    [ "$G" -lt 800 ] && ok "no runaway RSS under numa=2 churn" || bad "RSS grew +${G}MB (reclaim stalled on a node?)"
  else
    bad "INVALID: could not read own-server RSS (${R0:-empty} -> ${R1:-empty})"
  fi
  n2=$($CLI dbsize); [ "$n2" = "$n" ] && ok "dbsize stable through churn ($n2)" || bad "dbsize $n -> $n2"
  okc=0; for i in 1 2 3 4 5; do [ "$($CLI get n2:$i)" = "val-$i-payload" ] && okc=$((okc+1)); done
  [ "$okc" = 5 ] && ok "sentinel values intact across nodes" || bad "only $okc/5 sentinels intact"

  # C. the UAF paths: whole-table walks on io threads while workers free (both node tables)
  $MT --test-time=45 --ratio=1:0 -d 64 --key-pattern=R:R --key-maximum=1000000 -t 6 -c 20 --pipeline 24 --distinct-client-seed >/dev/null 2>&1 &
  N2_MTPID=$!; W=$N2_MTPID
  for r in 1 2 3 4 5 6; do $CLI debug digest >/dev/null 2>&1; $CLI bgsave >/dev/null 2>&1; $CLI randomkey >/dev/null 2>&1; sleep 2; done
  wait $W 2>/dev/null; N2_MTPID=""
  timeout 2 $CLI ping 2>/dev/null | grep -q PONG && ok "survived DIGEST/BGSAVE walks under churn (numa=2)" || bad "died during walks"

  # D. cross-node MGET (lock-free readers spanning both node tables) + expire/delete churn
  $MT --test-time=30 --command="MGET memtier-1 memtier-2 memtier-3 memtier-4" --command-key-pattern=R --key-maximum=1000000 -t 4 -c 10 --pipeline 8 >/dev/null 2>&1
  for k in $(seq 1 2000); do echo "SET ex:$k v$k PX 300"; done | $CLI --pipe >/dev/null 2>&1
  sleep 3
  timeout 2 $CLI ping 2>/dev/null | grep -q PONG && ok "alive after cross-node MGET + expire churn" || bad "died on MGET/expire"

  # E. flips under numa=2 (per-node flip is a staged path)
  M=$(wc -l < $J/numa2.log)
  $MT --test-time=40 --ratio=1:0 -d 32 --key-pattern=R:R --key-maximum=1000000 -t 6 -c 20 --pipeline 16 --distinct-client-seed >/dev/null 2>&1 &
  N2_MTPID=$!; W=$N2_MTPID; sleep 6
  $CLI debug tomo-modeshift 70 >/dev/null 2>&1   # per-node grow-front (node 0)
  sleep 10; $CLI debug tomo-modeshift 80 >/dev/null 2>&1
  wait $W 2>/dev/null; N2_MTPID=""; sleep 2
  echo "  per-node flips: front=$(tail -n +$M $J/numa2.log | grep -c 'GROW-FRONT complete') back=$(tail -n +$M $J/numa2.log | grep -c 'GROW-BACK complete')" >> $OUT
  timeout 2 $CLI ping 2>/dev/null | grep -q PONG && ok "alive after per-node flip attempts" || bad "died on per-node flip"

  # F. FLUSHALL + regrow (per-node table destroy with pending retires)
  $CLI flushall >/dev/null 2>&1; sleep 1
  $MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=600000 -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
  n3=$($CLI dbsize); [ "$n3" -ge 600000 ] 2>/dev/null && ok "flush+regrow across nodes ($n3)" || bad "flush+regrow dbsize=$n3"
fi
if grep -qiE 'crashed by signal|ASSERTION FAILED|=== REDIS BUG|Guru Meditation' $J/numa2.log 2>/dev/null; then
  bad "crash/assert in numa=2 log"; grep -iE 'Guru Meditation|crashed by signal|ASSERTION FAILED' $J/numa2.log | head -3 >> $OUT
else ok "no crash/assert markers"; fi
cleanup_n2   # our pid only -- never a shared name
echo "" >> $OUT
echo "RESULT: $PASS passed, $FAIL failed" >> $OUT
echo "=== DONE ===" >> $OUT
[ "$FAIL" = 0 ]
