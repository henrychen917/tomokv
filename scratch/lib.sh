#!/bin/bash
# lib.sh -- lane geometry, box gate, guards. Source me. Lane t-flipdamp, owner rules 2026-09-05:
#   my cores = physical 52-57 + SMT siblings 180-185, ports 8220-8229, never kill by pattern.
#   Server and load generator never share a physical core: server 52,53 (+180,181), loadgen 54-57
#   (+182-185). Geometry chosen so the SERVER is the bottleneck (memtier and tomokv cost about the
#   same per core on MK8, so the loadgen gets 2x the cores).
SP=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
WT=/home/user/Projects/wt-flipdamp
FIX_BIN=$WT/build/tomokv
BASE_BIN=/home/user/Projects/wt-flipdamp-base/build/tomokv
SRV_CPUS=52,53,180,181
LG_CPUS=54,55,56,57,182,183,184,185
MY_CPUS="52 53 54 55 56 57 180 181 182 183 184 185"
PORT_AB=8220; PORT_HOLD=8221; PORT_SIG=8222; PORT_SPLIT=8223; PORT_BAT=8224
SRV_RATIO=${SRV_RATIO:-2:2}          # 4 threads: splits 1:3 / 2:2 / 3:1 -- 2:2 ~ the owner's 18:14
LG_THREADS=${LG_THREADS:-8}; LG_CONNS=${LG_CONNS:-32}; LG_PIPE=${LG_PIPE:-32}
KEYMAX=200000
MY_PIDS=""

expand_mask() { local IFS=,; for r in $1; do if [[ $r == *-* ]]; then seq "${r%-*}" "${r#*-}"; else echo "$r"; fi; done; }
quiet_ok() { find "$SP" -maxdepth 1 -name quiet.done -mmin +3 2>/dev/null | grep -q .; }
# Any tomokv/memtier that is not mine and whose affinity touches my cores or their siblings.
intruders() {
  local p mask cpu hit
  for p in $(ps -eo pid,comm | awk '$2=="memtier_benchma"||$2=="tomokv"{print $1}'); do
    case " $MY_PIDS " in *" $p "*) continue;; esac
    mask=$(taskset -cp "$p" 2>/dev/null | sed 's/.*: //'); [ -z "$mask" ] && continue
    hit=0
    for cpu in $(expand_mask "$mask"); do case " $MY_CPUS " in *" $cpu "*) hit=1; break;; esac; done
    [ "$hit" = 1 ] && echo "pid $p affinity $mask"
  done
}
gate_ok() { quiet_ok && [ -z "$(intruders)" ]; }
# Abort the calling script if the box is not quiet: the owner's measurement removes quiet.done.
require_gate() {
  if ! quiet_ok; then echo "GATE: quiet.done missing or younger than 3 min -- stop"; return 3; fi
  local i; i=$(intruders); if [ -n "$i" ]; then echo "GATE: intruder on my cores: $i -- stop"; return 3; fi
  return 0
}
port_free() { ! ss -lntH 2>/dev/null | grep -q ":$1 "; }
# boot BIN PORT LOGTAG args... -> prints PID; kills by PID on failure.
boot() {
  local bin=$1 port=$2 tag=$3; shift 3
  port_free "$port" || { echo "PORT $port BUSY: $(ss -lntpH | grep ":$port ")" >&2; return 1; }
  taskset -c "$SRV_CPUS" "$bin" --port "$port" --save '' --enable-debug-command yes "$@" \
      >"$SP/fd-srv-$tag.log" 2>&1 &
  local pid=$! i
  MY_PIDS="$MY_PIDS $pid"
  for i in $(seq 200); do redis-cli -p "$port" ping 2>/dev/null | grep -q PONG && { echo "$pid"; return 0; }; sleep 0.1; done
  echo "BOOT FAILED ($bin $*)" >&2; tail -5 "$SP/fd-srv-$tag.log" >&2; kill -9 "$pid" 2>/dev/null; return 1
}
stop() { # stop PID PORT
  kill -9 "$1" 2>/dev/null; wait "$1" 2>/dev/null
  local i; for i in $(seq 150); do port_free "$2" && break; sleep 0.1; done
}
preload() { # preload PORT -- fill KEYMAX keys so GET/MGET hit (dbsize == keymax)
  taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$1" --protocol=redis -t 8 -c 8 \
      --pipeline=32 --ratio=1:0 --key-pattern=P:P -d 32 --key-minimum=1 --key-maximum=$KEYMAX \
      -n $((KEYMAX/64)) --hide-histogram >/dev/null 2>&1
}
# Per-role busy fraction over a window: lbsnap PORT > file; lbbusy FILE_BEFORE FILE_AFTER -> "io=0.97 ex=0.99"
lbsnap() { redis-cli -p "$1" debug lbsignals 2>/dev/null; }
lbbusy() {
  awk '$1=="thread"{ key=$3; b=$7; i=$8; if (FILENAME==ARGV[1]) {B0[key]+=b; I0[key]+=i} else {B1[key]+=b; I1[key]+=i} }
       END{ for (k in B1) { db=B1[k]-B0[k]; di=I1[k]-I0[k]; if (db+di>0) printf "%s=%.3f ", k, db/(db+di) } }' "$1" "$2"
}
infog() { echo "$1" | sed -n "s/^$2://p" | head -1; }
