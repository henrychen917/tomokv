#!/bin/bash
# DEBUG RELOAD across the SHARDED keyspace.
#
# WHY THIS EXISTS. emptyData() emptied only server.db — but under sharding the keyspace lives in
# the per-node shard dbs (server.node_dbs; every worker's db array aliases one). So the flush that
# DEBUG RELOAD performs before reloading was a silent NO-OP on the real data, and rdbLoad then
# re-added every key into the shard where it was still present: dbAddRDBLoad returned NULL and the
# server took "Guru Meditation: Duplicated key found in RDB file" (rdb.c) — deterministically.
# The same hole silently kept stale keys across a replica full resync.
#
# The dataset must span MANY buckets: with a handful of keys a per-shard bug hides completely.
# Both regimes are exercised, because the keyspace is dict-backed at ex=1 and FLATSTORE at ex>=2
# (shared_node_dbs = workers-per-node > 1) and the reload path differs between them:
#   ex=1  -> DICT
#   ex=4  -> FLATSTORE (shared node db)
set -u
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
BIN=${TOMO_BIN:?TOMO_BIN required}
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
SRC=$(cd "$(dirname "$0")/../.." && pwd)
CLI=${TOMO_CLI:-$SRC/src/redis-cli}
PORT=${PORT:-5996}
NKEYS=${NKEYS:-100000}
[ "${SMOKE:-0}" = "1" ] && NKEYS=20000
OUT=${OUT:-$J/debug_reload.out}; : > $OUT
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}

# Private binary name: never `pkill -x redis-server` on this box, other sessions run exactly that.
NAME=redis-dbgreload
cp "$BIN" $J/$NAME 2>/dev/null || { echo "cannot stage $BIN" >&2; exit 2; }
cleanup() { pkill -9 -x $NAME 2>/dev/null; }
trap cleanup EXIT

rec() { printf "%s\t%s\t%s\n" "$1" "$2" "${3:-}" >> $OUT; }

fill() { # $1=port  $2=nkeys — mixed types so the reload exercises more than strings
  taskset -c "$LOAD_CORES" python3 -c "
import sys
n=int('$2'); o=[]
def c(*a):
    r=b'*%d\r\n'%len(a)
    for x in a:
        b_=x if isinstance(x,bytes) else str(x).encode()
        r+=b'\$%d\r\n%s\r\n'%(len(b_),b_)
    return r
for i in range(n):
    m=i%4
    if   m==0: o.append(c('SET','k:%d'%i,'v'*40+str(i)))
    elif m==1: o.append(c('SET','e:%d'%i,'v'*40+str(i),'EX','100000'))
    elif m==2: o.append(c('HSET','h:%d'%i,'f1','a','f2','b'))
    else:      o.append(c('ZADD','z:%d'%i,'1','a','2','b'))
sys.stdout.buffer.write(b''.join(o))" | taskset -c "$LOAD_CORES" $CLI -p $1 --pipe >/dev/null 2>&1
}

run_regime() { # $1 = ex threads, $2 = label
  local EX=$1 IO=$((16-$1)) LBL=$2 RUN=$J/dbgreload_$2 DBGPID
  pkill -9 -x $NAME 2>/dev/null; sleep 0.5
  rm -rf $RUN; mkdir -p $RUN
  taskset -c "$SERVER_CORES" $J/$NAME --port $PORT --dir $RUN --tomokv-nodes 2 --tomokv-pin-mode ccd --tomokv-thread-io "$IO" \
    --tomokv-thread-ex "$EX" --save '' --appendonly no --protected-mode no \
    --enable-debug-command local --logfile $RUN/server.log >/dev/null 2>&1 &
  DBGPID=$!
  for i in $(seq 1 100); do timeout 2 $CLI -p $PORT ping 2>/dev/null | grep -q PONG && break; sleep 0.3; done
  if ! timeout 2 $CLI -p $PORT ping 2>/dev/null | grep -q PONG; then rec "$LBL-boot" FAIL "no PONG"; return; fi
  preflight_assert_standard_boot "$RUN/server.log" "$DBGPID" "$IO" "$EX" || { rec "$LBL-pin" FAIL "standard 2x16c assertion"; return; }

  fill $PORT $NKEYS
  local before after
  before=$($CLI -p $PORT dbsize 2>/dev/null)
  if [ "$before" != "$NKEYS" ]; then rec "$LBL-fill" FAIL "dbsize=$before want=$NKEYS"; return; fi

  # sample a few keys so we can prove the VALUES survive, not just the count
  local s1 s2 s3
  s1=$($CLI -p $PORT get k:0); s2=$($CLI -p $PORT hget h:2 f1); s3=$($CLI -p $PORT zscore z:3 b)

  # THE TEST: three consecutive reloads. Pre-fix this panics on the FIRST one.
  local r ok=1
  for r in 1 2 3; do
    if ! timeout 180 $CLI -p $PORT debug reload 2>/dev/null | grep -q OK; then
      rec "$LBL-reload$r" FAIL "DEBUG RELOAD did not return OK"; ok=0; break
    fi
    if ! timeout 2 $CLI -p $PORT ping 2>/dev/null | grep -q PONG; then
      rec "$LBL-reload$r" FAIL "server died during reload #$r"; ok=0; break
    fi
    after=$($CLI -p $PORT dbsize 2>/dev/null)
    if [ "$after" != "$NKEYS" ]; then
      rec "$LBL-reload$r" FAIL "dbsize=$after want=$NKEYS"; ok=0; break
    fi
    rec "$LBL-reload$r" PASS "dbsize=$after"
  done
  [ $ok = 1 ] || return

  # data must be intact and still routed to the shard the dispatcher will look in
  local a1 a2 a3
  a1=$($CLI -p $PORT get k:0); a2=$($CLI -p $PORT hget h:2 f1); a3=$($CLI -p $PORT zscore z:3 b)
  if [ "$a1" = "$s1" ] && [ "$a2" = "$s2" ] && [ "$a3" = "$s3" ]; then
    rec "$LBL-values" PASS ""
  else
    rec "$LBL-values" FAIL "k:0=$a1/$s1 h:2=$a2/$s2 z:3=$a3/$s3"
  fi
  # every key must be READABLE through normal dispatch (routing survived the reload)
  local miss
  miss=$(taskset -c "$LOAD_CORES" python3 -c "
import socket,sys
n=int('$NKEYS'); port=int('$PORT')
s=socket.create_connection(('127.0.0.1',port)); s.settimeout(30)
ks=[('k:%d'%i) for i in range(0,n,4)][:2000]
o=b''.join(b'*2\r\n\$3\r\nGET\r\n\$%d\r\n%s\r\n'%(len(k.encode()),k.encode()) for k in ks)
s.sendall(o); d=b''
while d.count(b'\r\n')<2*len(ks):
    c=s.recv(1<<20)
    if not c: break
    d+=c
print(d.count(b'\$-1'))" 2>/dev/null)
  if [ "$miss" = "0" ]; then rec "$LBL-readback" PASS ""
  else rec "$LBL-readback" FAIL "missing=$miss"; fi

  # a real sharded FLUSHALL must still work after a reload (shard flush not broken by the fix)
  $CLI -p $PORT flushall >/dev/null 2>&1; sleep 1
  after=$($CLI -p $PORT dbsize 2>/dev/null)
  if [ "$after" = "0" ]; then rec "$LBL-flushall" PASS ""
  else rec "$LBL-flushall" FAIL "dbsize=$after want=0"; fi
  pkill -9 -x $NAME 2>/dev/null
}

run_regime 1 dict
run_regime 4 flat

P=$(grep -c "	PASS	" $OUT || true); F=$(grep -c "	FAIL	" $OUT || true)
echo "=== DEBUG RELOAD (sharded keyspace) ==="
cat $OUT
echo "debug_reload: $P passed / $F failed"
[ "$F" = "0" ] && [ "$P" -ge 12 ]
