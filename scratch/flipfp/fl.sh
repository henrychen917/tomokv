#!/bin/bash
# fl.sh -- lane t-flipfp geometry, box gate, guards. Source me.
#   my cores = physical 48-51 + SMT siblings 176-179, ports 8240-8249, never kill by pattern.
#   Server and load generator never share a physical core.
SP=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
FP=$SP/flipfp
WT=/home/user/Projects/wt-flipfp
WT_BASE=/home/user/Projects/wt-flipfp-base
POST_BIN=$FP/bin/tomokv-flipfp-post
PRE_BIN=$FP/bin/tomokv-flipfp-pre
GUARD_BIN=$SP/bin/tomokv-flipguard
MY_CPUS="48 49 50 51 176 177 178 179"
MY_MASK=48-51,176-179
# 4-thread cells: server 48,49 + siblings; loadgen 50,51 + siblings.
SRV4=48,49,176,177; LG4=50,51,178,179
# 6-thread cells (the 28:4 analogue this allocation can hold): server 48-50 + siblings; loadgen 51 + sibling.
SRV6=48,49,50,176,177,178; LG6=51,179
PORT_SLOPE=8240; PORT_ON=8241; PORT_TM=8242; PORT_CTL=8243; PORT_BAT=8244; PORT_DIFF=8245; PORT_ORACLE=8246; PORT_GATE=8247
KEYMAX=200000
MY_PIDS=""
CLI=/tmp/claude-1000/redis74/src/redis-cli
LG(){ echo "$(date +%T) $*"; }

expand_mask() { local IFS=,; for r in $1; do if [[ $r == *-* ]]; then seq "${r%-*}" "${r#*-}"; else echo "$r"; fi; done; }
# The marker must EXIST and be older than 180 s (explicit age arithmetic; find -mmin is vacuous).
quiet_ok() { local f=$SP/quiet.done; [ -f "$f" ] && [ $(( $(date +%s) - $(stat -c %Y "$f") )) -ge 180 ]; }
# Any tomokv/memtier that is not mine and whose affinity touches my cores or their siblings.
intruders() {
  local p mask cpu hit
  for p in $(ps -eo pid,comm | awk '$2=="memtier_benchma" || $2 ~ /^(tomokv|tkv)/ {print $1}'); do
    case " $MY_PIDS " in *" $p "*) continue;; esac
    [ "$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')" = "$$" ] && continue
    mask=$(taskset -cp "$p" 2>/dev/null | sed 's/.*: //'); [ -z "$mask" ] && continue
    hit=0
    for cpu in $(expand_mask "$mask"); do case " $MY_CPUS " in *" $cpu "*) hit=1; break;; esac; done
    [ "$hit" = 1 ] && echo "pid $p ($(ps -o comm= -p "$p")) affinity $mask"
  done
}
gate_ok() { quiet_ok && [ -z "$(intruders)" ]; }
wait_gate(){ local n=0; while ! gate_ok; do [ $((n%10)) = 0 ] && LG "paused: $(intruders | tr '\n' ';')$(quiet_ok || echo ' quiet.done missing/young')"; n=$((n+1)); sleep 30; done; }
port_free() { ! ss -lntH 2>/dev/null | grep -q ":$1 "; }
# boot BIN PORT LOGTAG args... -> prints PID; kills by PID on failure. SRV_CPUS selects the cores.
boot() {
  local bin=$1 port=$2 tag=$3; shift 3
  port_free "$port" || { echo "PORT $port BUSY: $(ss -lntpH | grep ":$port ")" >&2; return 1; }
  taskset -c "$SRV_CPUS" "$bin" --port "$port" --save '' --enable-debug-command yes "$@" \
      >"$FP/srv-$tag.log" 2>&1 &
  local pid=$! i
  MY_PIDS="$MY_PIDS $pid"
  for i in $(seq 200); do $CLI -p "$port" ping 2>/dev/null | grep -q PONG && { echo "$pid"; return 0; }; sleep 0.1; done
  echo "BOOT FAILED ($bin $*)" >&2; tail -5 "$FP/srv-$tag.log" >&2; kill -9 "$pid" 2>/dev/null; return 1
}
stop() { # stop PID PORT
  kill -TERM "$1" 2>/dev/null; wait "$1" 2>/dev/null
  local i; for i in $(seq 150); do port_free "$2" && break; sleep 0.1; done
}
preload() { # preload PORT THREADS -- fill KEYMAX keys so GET/MGET hit (dbsize == keymax)
  local t=${2:-4}
  taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$1" --protocol=redis -t "$t" -c 8 \
      --pipeline=32 --ratio=1:0 --key-pattern=P:P -d 32 --key-minimum=1 --key-maximum=$KEYMAX \
      -n $((KEYMAX/(t*8))) --hide-histogram >/dev/null 2>&1
  local n; n=$($CLI -p "$1" dbsize | tr -d '\r'); [ "$n" -ge $((KEYMAX-1)) ] || echo "PRELOAD SHORT: dbsize=$n" >&2
}
K8="__key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__"
M8="__key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__"
mk_load() { # mk_load PORT SECS THREADS [extra memtier args] -- 8-key MGET/MSET 1:1
  local port=$1 secs=$2 t=$3; shift 3
  taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$port" --protocol=redis -t "$t" -c 32 --pipeline=32 \
    --command="MGET $K8" --command-ratio=1 --command-key-pattern=R \
    --command="MSET $M8" --command-ratio=1 --command-key-pattern=R \
    -d 32 --key-minimum=1 --key-maximum=$KEYMAX --test-time="$secs" --distinct-client-seed --hide-histogram "$@"
}
sk_load() { # sk_load PORT SECS THREADS RATIO [extra] -- single-key SET/GET
  local port=$1 secs=$2 t=$3 ratio=$4; shift 4
  taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$port" --protocol=redis -t "$t" -c 32 --pipeline=32 \
    --ratio="$ratio" --key-pattern=R:R -d 32 --key-minimum=1 --key-maximum=$KEYMAX --test-time="$secs" \
    --distinct-client-seed --hide-histogram "$@"
}
infog() { echo "$1" | sed -n "s/^$2://p" | head -1; }
flipinfo() { $CLI -p "$1" info flipctl 2>/dev/null | tr -d '\r'; }
mt_rate() { tr '\r' '\n' <"$1" | awk '/^Totals/{print $2}' | tail -1; }
