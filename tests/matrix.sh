#!/bin/bash
# matrix.sh — the five-way comparison: tomokv vs redis vs valkey vs dragonfly vs garnet.
#
# GEOMETRY. Every arm gets the same server cores and the same loadgen cores, and each is configured
# to use them as well as that server knows how. Anything else compares a server against the harness.
#
# RATIO IS PER CELL. tomokv's io:ex split is a boot flag, and no single value serves the whole table.
# Measured at 32 cores:
#     ratio    GET p1     GET p128   MGET8 p8
#     18:14    1.65M      25.34M     2.13M
#     28:4     2.42M      10.22M     0.82M
# p1 is network-bound and wants IO threads (gate_refs pins 7:1 for exactly this reason); p128 and
# multi-key are execution-bound and want EX threads. Running p1 at the p128 shape reported tomokv 22%
# BEHIND dragonfly when the correct shape is ~1.1x AHEAD. Cells are grouped by ratio and the server
# rebooted per group. Competitor arms ignore the ratio but get identical boot/populate treatment, so
# the procedure is the same for everyone.
#
# ATOMICS ON. dragonfly and garnet are atomic on multi-key. tomokv defaults --atomic 0, so an
# unmatched run would flatter us by doing less work. Every tomokv boot here is --atomic 1.
#
# CELL DEPTH. Single-key and multi-key have OPPOSITE responses to pipeline depth on this tree:
# GET/SET gain ~2.5x from p1 to p128 while MGET/MSET LOSE ~36% and grow unstable. Each family is
# measured where it peaks -- single-key at p128 and p1, multi-key at p8.
#
# memtier's --ratio is SET:GET, not read:write. A 9:1 READ-heavy mix is --ratio=1:9.
#
# WHAT THIS REFUSES TO DO. It aborts rather than print a number it cannot defend:
#   - an arm whose version does not match its pin   (a pinned SOURCE is not a pinned BINARY)
#   - a fill that leaves holes in the keyspace      (unpopulated keys inflate GET)
#   - a server pid it cannot resolve from the port  ($! can be a wrapper, and wrappers have small RSS)
set -u

SP=${MATRIX_OUT:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/matrix}
SRV_CPUS=${MATRIX_SRV_CPUS:-0-31}
LG_CPUS=${MATRIX_LG_CPUS:-64-127}
PORT=${MATRIX_PORT:-7870}
ROUNDS=${MATRIX_ROUNDS:-3}
KEYMAX=${MATRIX_KEYMAX:-1000000}
DSIZE=${MATRIX_DSIZE:-64}
SECS=${MATRIX_SECS:-8}
NET=${MATRIX_NET:-loopback}          # loopback | nic
NTHREADS=$(taskset -c "$SRV_CPUS" nproc)
mkdir -p "$SP"

TOMOKV=${MATRIX_TOMOKV:-/home/user/Projects/tomokv-cpp-perthread/build/tomokv}
REDIS=${MATRIX_REDIS:-/tmp/claude-1000/redis74/src/redis-server}
VALKEY=${MATRIX_VALKEY:-/home/user/Projects/valkey/src/valkey-server}
DRAGONFLY=${MATRIX_DRAGONFLY:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/dragonfly-x86_64}
DOTNET=${MATRIX_DOTNET:-/home/user/.dotnet/dotnet}
GARNET=${MATRIX_GARNET:-/home/user/Projects/garnet/main/GarnetServer/bin/Release/net10.0/GarnetServer.dll}
ARMS=${MATRIX_ARMS:-"tomokv redis valkey dragonfly garnet"}

# ---- network mode -------------------------------------------------------------------------------
# NIC mode runs the server in serverns and the loadgen in clientns so traffic crosses a real 25GbE
# link. Loopback hides send-path behaviour and carries no NIC tax; the two paths differ by ~12% at
# p128/32c, so a loopback-only table misstates the headline.
if [ "$NET" = nic ]; then
  SRV_WRAP=(sudo -n ip netns exec serverns setpriv --reuid=1000 --regid=1000 --clear-groups)
  LG_WRAP=(sudo -n ip netns exec clientns setpriv --reuid=1000 --regid=1000 --clear-groups)
  BIND_IP=10.200.0.2; TARGET_IP=10.200.0.2
else
  SRV_WRAP=(); LG_WRAP=(); BIND_IP=127.0.0.1; TARGET_IP=127.0.0.1
fi
srv() { if [ ${#SRV_WRAP[@]} -gt 0 ]; then "${SRV_WRAP[@]}" "$@"; else "$@"; fi; }
lg()  { if [ ${#LG_WRAP[@]}  -gt 0 ]; then "${LG_WRAP[@]}"  "$@"; else "$@"; fi; }
cli() { if [ "$NET" = nic ]; then lg redis-cli -h "$TARGET_IP" -p "$PORT" "$@"; else redis-cli -p "$PORT" "$@"; fi; }
port_open() { if [ "$NET" = nic ]; then lg bash -c "exec 3<>/dev/tcp/$TARGET_IP/$PORT" 2>/dev/null;
              else (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; fi; }

die() { printf '\nABORT: %s\n' "$1" >&2; exit 1; }

version_of() {
  case "$1" in
    redis)     "$REDIS" --version 2>&1 | grep -oE 'v=[0-9][0-9.]*' | head -1 ;;
    valkey)    "$VALKEY" --version 2>&1 | grep -oE 'v=[0-9][0-9.]*' | head -1 ;;
    dragonfly) "$DRAGONFLY" --version 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -oE 'v[0-9][0-9.]*' | head -1 ;;
  esac
}
expected_version() {
  case "$1" in
    redis) echo "v=7.4.2" ;; valkey) echo "v=9.1.1" ;; dragonfly) echo "v1.40.1" ;;
    garnet) echo "" ;;   # no --version; banner-checked after boot
    tomokv) echo "" ;;   # built from this worktree; provenance is the git sha printed below
  esac
}

boot_arm() { # arm ratio -> server on $PORT, sets SRV_PID
  local arm=$1 ratio=$2 log="$SP/srv.$1.log"
  SRV_PID=0
  case "$arm" in
    tomokv)    # --protected-mode no: tomokv implements redis's rule that a non-loopback peer with no
               # password is DENIED, so every NIC cell fails without it. redis and valkey get the
               # same flag below; this is compatibility, not a tuning choice.
               srv taskset -c "$SRV_CPUS" "$TOMOKV" --port "$PORT" --bind "$BIND_IP" \
                   --protected-mode no --shards $((NTHREADS * 2)) --ratio "$ratio" --atomic 1 > "$log" 2>&1 & ;;
    redis)     srv taskset -c "$SRV_CPUS" "$REDIS" --port "$PORT" --bind "$BIND_IP" --save '' \
                   --appendonly no --protected-mode no --io-threads "$NTHREADS" > "$log" 2>&1 & ;;
    valkey)    srv taskset -c "$SRV_CPUS" "$VALKEY" --port "$PORT" --bind "$BIND_IP" --save '' \
                   --appendonly no --protected-mode no --io-threads "$NTHREADS" > "$log" 2>&1 & ;;
    dragonfly) srv taskset -c "$SRV_CPUS" "$DRAGONFLY" --port "$PORT" --bind "$BIND_IP" \
                   --proactor_threads "$NTHREADS" --dbfilename '' --logtostderr > "$log" 2>&1 & ;;
    garnet)    srv taskset -c "$SRV_CPUS" "$DOTNET" "$GARNET" --port "$PORT" --bind "$BIND_IP" \
                   --no-pubsub --minthreads "$NTHREADS" --maxthreads "$NTHREADS" > "$log" 2>&1 & ;;
  esac
  SRV_PID=$!
  for _ in $(seq 160); do
    if port_open; then
      # Resolve the pid from the LISTENING SOCKET. $! can name a wrapper (taskset/netns/setpriv),
      # and a wrapper's few-MB RSS silently reported redis as 63MB where it actually held 153MB.
      local resolved
      resolved=$(srv ss -lptnH "sport = :$PORT" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
      [ -n "${resolved:-}" ] && SRV_PID=$resolved
      [ -r /proc/$SRV_PID/status ] || die "cannot resolve server pid for $arm on port $PORT"
      if [ "$arm" = garnet ]; then
        local gv; gv=$(sed 's/\x1b\[[0-9;]*m//g' "$log" | grep -oiE 'Garnet [0-9][0-9.]*' | head -1)
        [ "$gv" = "Garnet 2.1.4" ] || die "garnet banner reports '${gv:-nothing}', pin expects 'Garnet 2.1.4'"
      fi
      return 0
    fi
    sleep 0.25
  done
  tail -5 "$log" >&2; return 1
}

stop_arm() {
  cli shutdown nosave >/dev/null 2>&1
  sleep 1
  [ "${SRV_PID:-0}" -gt 0 ] && kill -9 "$SRV_PID" 2>/dev/null
  # `pgrep -x` matches comm, truncated to 15 chars -- "dragonfly-x86_64" is 16 and can never match.
  pgrep -f "GarnetServer.dll" 2>/dev/null | while read -r p; do kill -9 "$p" 2>/dev/null; done
  for pat in tomokv redis-server valkey-server dragonfly-x86; do
    pgrep -x "$pat" 2>/dev/null | while read -r p; do kill -9 "$p" 2>/dev/null; done
  done
  for _ in $(seq 60); do port_open || return 0; sleep 0.5; done
  die "port $PORT still accepting after teardown"
}

rss_mb() { [ "${SRV_PID:-0}" -gt 0 ] && awk '/VmRSS/{printf "%.0f", $2/1024}' /proc/"$SRV_PID"/status 2>/dev/null || echo 0; }
fill() { lg taskset -c "$LG_CPUS" memtier_benchmark -s "$TARGET_IP" -p "$PORT" --protocol=redis \
      -t 16 -c 8 --pipeline=32 --ratio=1:0 --key-pattern=P:P \
      --key-minimum="$1" --key-maximum="$2" -n allkeys -d "$DSIZE" --hide-histogram >/dev/null 2>&1; }

covered() { # low high -- sample the range; every sampled key must exist
  local lo=$1 hi=$2 k miss=0
  for k in "$lo" $(( lo + (hi-lo)/4 )) $(( lo + (hi-lo)/2 )) $(( hi - (hi-lo)/4 )) "$hi"; do
    [ "$(cli exists "memtier-$k" 2>/dev/null | tr -dc '0-9')" = "1" ] || miss=$((miss+1))
  done
  [ "$miss" -eq 0 ]
}
populate() { # arm -- fills in two halves so bytes/key is a SLOPE, not a total
  # Subtracting the empty baseline is not enough: a loaded server's RSS also carries per-connection
  # buffers and hash-table capacity rounding. Charging those to the keys reported 649 B/key for a
  # store that costs ~120. (full - half) / (keys/2) cancels every fixed cost.
  local half=$(( KEYMAX / 2 ))
  [ "$(cli dbsize 2>/dev/null | tr -dc '0-9')" = "0" ] || die "$1 not empty at boot (stale server on $PORT?)"
  RSS_EMPTY=$(rss_mb)
  fill 1 "$half";  covered 1 "$half"   || die "$1: first fill left holes in [1,$half]"
  RSS_HALF=$(rss_mb)
  fill $((half+1)) "$KEYMAX"; covered 1 "$KEYMAX" || die "$1: second fill left holes in [1,$KEYMAX]"
  RSS_FULL=$(rss_mb)
}

cpu_snapshot() { grep -E '^cpu[0-9]' /proc/stat; }
cpu_busy() { awk -v list="$1" -v before="$2" -v after="$3" '
    BEGIN{ n=split(list,L,","); for(j=1;j<=n;j++) want[L[j]]=1
      split(before,B,"\n"); split(after,A,"\n")
      for(i in B){split(B[i],f," "); if(f[1]~/^cpu[0-9]/){c=substr(f[1],4);t=0;for(x=2;x<=11;x++)t+=f[x];bt[c]=t;bi[c]=f[5]+f[6]}}
      for(i in A){split(A[i],f," "); if(f[1]~/^cpu[0-9]/){c=substr(f[1],4); if(!(c in want)||!(c in bt))continue
        t=0;for(x=2;x<=11;x++)t+=f[x]; dt=t-bt[c]; di=(f[5]+f[6])-bi[c]; if(dt>0){s+=100*(dt-di)/dt;k++}}}
      printf "%.1f",(k?s/k:-1) }'; }
expand() { python3 -c "
import sys
out=[]
for part in sys.argv[1].split(','):
    if '-' in part:
        a,b=part.split('-'); out += [str(x) for x in range(int(a),int(b)+1)]
    else: out.append(part)
print(','.join(out))" "$1"; }
SRV_LIST=$(expand "$SRV_CPUS"); LG_LIST=$(expand "$LG_CPUS")

run_cell() { # arm name pipeline argv(|-separated)
  local arm=$1 name=$2 pipe=$3 argvs=$4
  local -a extra=(); local oldifs="$IFS"; IFS='|'; read -ra extra <<< "$argvs"; IFS="$oldifs"
  local before after v
  before=$(cpu_snapshot)
  # 64 threads x 8 = 512 connections, matching gate_refs.txt. At p1 throughput is Little's law --
  # connections divided by latency -- so 256 connections reported 1.86M where 512 gives 2.42M at the
  # same ratio. The connection count is part of the cell, not an incidental harness detail.
  v=$(lg taskset -c "$LG_CPUS" memtier_benchmark -s "$TARGET_IP" -p "$PORT" --protocol=redis \
        -t 64 -c 8 --pipeline="$pipe" -d "$DSIZE" --key-minimum=1 --key-maximum="$KEYMAX" \
        --test-time="$SECS" --distinct-client-seed --hide-histogram "${extra[@]}" 2>/dev/null \
        | tr -d '\r' | awk '/^Totals/{print $2; exit}')
  after=$(cpu_snapshot)
  local sb lb; sb=$(cpu_busy "$SRV_LIST" "$before" "$after"); lb=$(cpu_busy "$LG_LIST" "$before" "$after")
  awk -v s="$sb" -v l="$lb" -v n="$name" -v a="$arm" 'BEGIN{
    if (l >= 90.0)         printf "  WARN %s/%s: loadgen %.1f%% busy -- at its ceiling, cell is a FLOOR\n", a, n, l
    else if (l - s > 15.0) printf "  WARN %s/%s: loadgen %.1f%% vs server %.1f%% -- loadgen dominates\n", a, n, l, s }' >&2
  echo "${v:-0}" >> "$SP/$arm.$name"
  echo "$sb $lb" >> "$SP/$arm.$name.cpu"
}

MG="MGET __key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__"
MS="MSET __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__"
BLEND="--command=GET __key__|--command-ratio=1|--command-key-pattern=R|--command=SET __key__ __data__|--command-ratio=1|--command-key-pattern=R|--command=$MG|--command-ratio=1|--command-key-pattern=R|--command=$MS|--command-ratio=1|--command-key-pattern=R"
# name ; pipeline ; tomokv ratio ; memtier argv   (';' because ratios contain ':')
CELLS=(
  "GET_p128;128;18:14;--command=GET __key__|--command-key-pattern=R"
  "SET_p128;128;18:14;--command=SET __key__ __data__|--command-key-pattern=R"
  "MGET8_p8;8;18:14;--command=$MG|--command-key-pattern=R"
  "MSET8_p8;8;18:14;--command=$MS|--command-key-pattern=R"
  "MIX9to1_p128;128;18:14;--ratio=1:9|--key-pattern=R:R"
  "MIX1to1_p128;128;18:14;--ratio=1:1|--key-pattern=R:R"
  "BLEND1111_p8;8;18:14;$BLEND"
  "GET_p1;1;28:4;--command=GET __key__|--command-key-pattern=R"
  "SET_p1;1;28:4;--command=SET __key__ __data__|--command-key-pattern=R"
)
RATIOS=$(for c in "${CELLS[@]}"; do echo "$c" | cut -d';' -f3; done | awk '!seen[$0]++')
FIRST_RATIO=$(echo "$RATIOS" | head -1)

echo "=== MATRIX ($NET): $ARMS ==="
echo "    server $SRV_CPUS ($NTHREADS threads), loadgen $LG_CPUS, ${ROUNDS}x${SECS}s, keys $KEYMAX, d=$DSIZE"
echo "    tomokv sha: $(git -C /home/user/Projects/tomokv-cpp-perthread rev-parse --short HEAD), --atomic 1"
echo "    tomokv ratios in play: $(echo $RATIOS | tr '\n' ' ')"
for arm in $ARMS; do
  got=$(version_of "$arm"); want=$(expected_version "$arm")
  if [ -n "$want" ] && [ "$got" != "$want" ]; then die "$arm reports '$got', pin expects '$want'"; fi
  printf "    %-10s %s\n" "$arm" "${got:-<from worktree>}"
  for c in "${CELLS[@]}"; do n="${c%%;*}"; : > "$SP/$arm.$n"; : > "$SP/$arm.$n.cpu"; done
  : > "$SP/$arm.rss"
done

for r in $(seq "$ROUNDS"); do
  for arm in $ARMS; do
    for ratio in $RATIOS; do
      stop_arm
      boot_arm "$arm" "$ratio" || die "$arm failed to boot at ratio $ratio"
      populate "$arm"
      for c in "${CELLS[@]}"; do
        n="${c%%;*}"; rest="${c#*;}"; pipe="${rest%%;*}"; rest="${rest#*;}"
        cr="${rest%%;*}"; argv="${rest#*;}"
        [ "$cr" = "$ratio" ] || continue
        run_cell "$arm" "$n" "$pipe" "$argv"
      done
      # Record RSS once per arm per round, from the first ratio group.
      [ "$ratio" = "$FIRST_RATIO" ] && echo "${RSS_FULL:-0} ${RSS_HALF:-0} ${RSS_EMPTY:-0}" >> "$SP/$arm.rss"
    done
  done
  echo "  round $r done"
done
stop_arm

printf "\n%-14s" "cell"; for arm in $ARMS; do printf " %13s" "$arm"; done
printf "  |"; for arm in $ARMS; do [ "$arm" = tomokv ] && continue; printf " %11s" "t/$arm"; done; echo
for c in "${CELLS[@]}"; do
  n="${c%%;*}"; printf "%-14s" "$n"
  tm=$(awk '{s+=$1;k++} END{printf "%.0f",(k?s/k:0)}' "$SP/tomokv.$n" 2>/dev/null || echo 0)
  for arm in $ARMS; do printf " %13s" "$(awk '{s+=$1;k++} END{printf "%.0f",(k?s/k:0)}' "$SP/$arm.$n")"; done
  printf "  |"
  for arm in $ARMS; do [ "$arm" = tomokv ] && continue
    om=$(awk '{s+=$1;k++} END{printf "%.0f",(k?s/k:0)}' "$SP/$arm.$n")
    awk -v t="$tm" -v o="$om" 'BEGIN{printf " %11s",(o>0?sprintf("%.2fx",t/o):"n/a")}'; done
  printf "   CoV %s\n" "$(awk '{s+=$1;q[NR]=$1} END{if(NR<2){print "n/a";exit} m=s/NR;
      for(i=1;i<=NR;i++)v+=(q[i]-m)^2; printf "%.2f%%",100*sqrt(v/NR)/m}' "$SP/tomokv.$n")"
done
printf "\n%-14s" "RSS empty"; for arm in $ARMS; do printf " %13s" "$(awk '{s+=$3;k++} END{printf "%.0f MB",(k?s/k:0)}' "$SP/$arm.rss")"; done; echo
printf "%-14s" "RSS full";   for arm in $ARMS; do printf " %13s" "$(awk '{s+=$1;k++} END{printf "%.0f MB",(k?s/k:0)}' "$SP/$arm.rss")"; done; echo
printf "%-14s" "B/key";      for arm in $ARMS; do printf " %13s" "$(awk -v k="$KEYMAX" '{d+=($1-$2);n++} END{printf "%.1f",(n&&k?d/n*1048576/(k/2):0)}' "$SP/$arm.rss")"; done
printf "   MARGINAL (full-half)/(keys/2)\n"
