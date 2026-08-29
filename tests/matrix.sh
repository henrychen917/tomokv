#!/bin/bash
# matrix.sh — the four-way comparison: tomokv vs redis vs valkey vs dragonfly.
#
# GEOMETRY. Every arm gets the SAME 32 server cores and the same 32 loadgen cores, and each is
# configured to use them as well as that server knows how. Anything else compares a server against
# the harness rather than against another server.
#
# CELL DESIGN. Single-key and multi-key commands have OPPOSITE responses to pipeline depth on this
# tree: GET/SET gain ~2.5x from p1 to p128, while MGET/MSET LOSE ~36% over the same range and become
# unstable on the way down (see NOTES / the congestion-collapse finding). So each family is measured
# where it peaks -- single-key at p128 and p1, multi-key at p8. Running multi-key at p128 next to
# GET/SET would understate this tree by a third and would do it with 4.5% run-to-run noise.
#
# WHAT THIS SCRIPT REFUSES TO DO. It aborts rather than produce a number it cannot defend:
#   - an arm whose --version does not match its pin  (a pinned SOURCE is not a pinned BINARY)
#   - a populate that does not leave dbsize == key-maximum  (unpopulated keys inflate GET)
#   - a cell where the loadgen is busier than the server  (that measures memtier, not the server)
set -u

SP=${MATRIX_OUT:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/matrix}
SRV_CPUS=${MATRIX_SRV_CPUS:-0-31}
LG_CPUS=${MATRIX_LG_CPUS:-64-95}
PORT=${MATRIX_PORT:-7870}
ROUNDS=${MATRIX_ROUNDS:-3}
KEYMAX=${MATRIX_KEYMAX:-1000000}
DSIZE=${MATRIX_DSIZE:-64}
SECS=${MATRIX_SECS:-8}
NTHREADS=$(taskset -c "$SRV_CPUS" nproc)
mkdir -p "$SP"

TOMOKV=${MATRIX_TOMOKV:-/home/user/Projects/tomokv-cpp-perthread/build/tomokv}
REDIS=${MATRIX_REDIS:-/tmp/claude-1000/redis74/src/redis-server}
VALKEY=${MATRIX_VALKEY:-/home/user/Projects/valkey/src/valkey-server}
DRAGONFLY=${MATRIX_DRAGONFLY:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/dragonfly-x86_64}

ARMS=${MATRIX_ARMS:-"tomokv redis valkey dragonfly"}

die() { printf '\nABORT: %s\n' "$1" >&2; exit 1; }

# ---- version pins -------------------------------------------------------------------------------
# A pinned source is not a pinned binary: a previous round of this program compared a dragonfly
# binary at v1.39.0 against a tag that said v1.40.1. Every arm states its expected version and the
# run dies if the binary disagrees.
version_of() {
  case "$1" in
    tomokv)    "$TOMOKV" --help 2>&1 | grep -oiE 'tomokv[ /-]v?[0-9][0-9.]*' | head -1 ;;
    redis)     "$REDIS" --version 2>&1 | grep -oE 'v=[0-9][0-9.]*' | head -1 ;;
    valkey)    "$VALKEY" --version 2>&1 | grep -oE 'v=[0-9][0-9.]*' | head -1 ;;
    dragonfly) "$DRAGONFLY" --version 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -oE 'v[0-9][0-9.]*' | head -1 ;;
  esac
}
expected_version() {
  case "$1" in
    redis)     echo "v=7.4.2" ;;
    valkey)    echo "v=9.1.1" ;;
    dragonfly) echo "v1.40.1" ;;
    tomokv)    echo "" ;;        # built from this worktree; provenance is the git sha below
  esac
}

boot_arm() { # arm -> starts server on $PORT pinned to $SRV_CPUS, sets SRV_PID
  local arm=$1 log="$SP/srv.$1.log"
  SRV_PID=0
  case "$arm" in
    tomokv)
      taskset -c "$SRV_CPUS" "$TOMOKV" --port "$PORT" --bind 127.0.0.1 \
          --shards $((NTHREADS * 2)) --ratio 18:14 > "$log" 2>&1 & ;;
    redis)
      # redis 7.4 offloads only reads/writes to io-threads; the command itself stays on one core.
      # That is redis's own ceiling, not a harness limit -- give it the threads and report what it does.
      taskset -c "$SRV_CPUS" "$REDIS" --port "$PORT" --bind 127.0.0.1 --save '' --appendonly no \
          --protected-mode no --io-threads "$NTHREADS" > "$log" 2>&1 & ;;
    valkey)
      taskset -c "$SRV_CPUS" "$VALKEY" --port "$PORT" --bind 127.0.0.1 --save '' --appendonly no \
          --protected-mode no --io-threads "$NTHREADS" > "$log" 2>&1 & ;;
    dragonfly)
      taskset -c "$SRV_CPUS" "$DRAGONFLY" --port "$PORT" --bind 127.0.0.1 \
          --proactor_threads "$NTHREADS" --dbfilename '' --logtostderr > "$log" 2>&1 & ;;
  esac
  SRV_PID=$!
  for _ in $(seq 120); do
    if (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then
      # Resolve the pid from the LISTENING SOCKET, never from $!. Backgrounding a redirected command
      # inside a function+case can leave $! pointing at a wrapper rather than the exec'd server, and
      # that wrapper has a few MB of RSS -- which silently reported redis as 63MB at 1M keys when it
      # actually holds 153MB. Every memory number in this table depends on this being the real pid.
      local resolved
      resolved=$(ss -lptnH "sport = :$PORT" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
      [ -n "${resolved:-}" ] && SRV_PID=$resolved
      [ -r /proc/$SRV_PID/status ] || die "cannot resolve server pid for $arm on port $PORT"
      return 0
    fi
    sleep 0.25
  done
  tail -5 "$log" >&2; return 1
}
stop_arm() {
  redis-cli -p "$PORT" shutdown nosave >/dev/null 2>&1
  sleep 1
  # `pgrep -x` matches /proc/<pid>/comm, which the kernel truncates to 15 chars -- "dragonfly-x86_64"
  # is 16 and can never match, and pgrep says so loudly on every call. Kill the pid we launched, then
  # sweep the short names only.
  [ "${SRV_PID:-0}" -gt 0 ] && kill -9 "$SRV_PID" 2>/dev/null
  for pat in tomokv redis-server valkey-server dragonfly-x86; do
    pgrep -x "$pat" 2>/dev/null | while read -r p; do kill -9 "$p" 2>/dev/null; done
  done
  # dragonfly has been observed to squat its port after SIGKILL; wait for the port, not the process.
  for _ in $(seq 60); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null || return 0; sleep 0.5; done
  die "port $PORT still accepting after teardown"
}

rss_mb() { [ "${SRV_PID:-0}" -gt 0 ] && awk '/VmRSS/{printf "%.0f", $2/1024}' /proc/"$SRV_PID"/status 2>/dev/null || echo 0; }

fill() { # low high -- write keys [low,high] and leave them there
  taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$PORT" --protocol=redis \
      -t 16 -c 8 --pipeline=32 --ratio=1:0 --key-pattern=P:P \
      --key-minimum="$1" --key-maximum="$2" -n allkeys -d "$DSIZE" --hide-histogram >/dev/null 2>&1
}

populate() {
  # MARGINAL bytes/key, measured as a SLOPE across two fills.
  #
  # Subtracting the empty baseline is not enough. A freshly loaded server's RSS also carries costs
  # that scale with CONNECTIONS (256 of them during populate, each with buffers) and with the hash
  # table's CAPACITY, which grows in large steps and so is mostly a rounding artifact at any given
  # key count. Charging all of that to the keys reported ~649 B/key for a store whose real per-key
  # cost is ~109. Filling half, measuring, filling the rest and measuring again cancels every fixed
  # cost: what is left between the two points is what one more key actually costs.
  local half=$(( KEYMAX / 2 ))
  # Assert dbsize AT EVERY SAMPLE POINT, not just at the end. A silent undercount in either fill
  # produces a memory table that looks plausible and is wrong by 2x -- which is exactly what happened
  # when only the final count was checked. Sampling after the dbsize round-trip also guarantees the
  # server has settled, which the old "sample the instant the port accepts" empty reading did not.
  dbsize_now() { redis-cli -p "$PORT" dbsize 2>/dev/null | tr -dc '0-9'; }
  local db
  db=$(dbsize_now); [ "${db:-x}" = "0" ] || die "server not empty at boot: dbsize=$db"
  RSS_EMPTY=$(rss_mb)

  fill 1 "$half"
  db=$(dbsize_now)
  [ "${db:-0}" = "$half" ] || die "first fill wrote dbsize=$db, expected $half -- memory slope invalid"
  RSS_HALF=$(rss_mb)

  fill $((half + 1)) "$KEYMAX"
  db=$(dbsize_now)
  [ "${db:-0}" = "$KEYMAX" ] || die "second fill wrote dbsize=$db, expected $KEYMAX (hit-rate trap: an unpopulated keyspace inflates GET)"
  RSS_FULL=$(rss_mb)
}

# Snapshots live in SHELL VARIABLES, not temp files. The file-based version of this silently read
# stale snapshots -- with the cp error suppressed -- and reported an identical, fictitious busy
# percentage for every cell, which made the saturation guard cry wolf on all of them. A guard that
# fires always is worse than no guard: it trains you to ignore it.
cpu_snapshot() { grep -E '^cpu[0-9]' /proc/stat; }
cpu_busy() { # cpulist "before" "after" -> mean %busy over the listed cpus
  awk -v list="$1" -v before="$2" -v after="$3" '
    BEGIN{
      n = split(list, L, ","); for (j = 1; j <= n; j++) want[L[j]] = 1
      split(before, B, "\n"); split(after, A, "\n")
      for (i in B) { split(B[i], f, " "); if (f[1] ~ /^cpu[0-9]/) {
          c = substr(f[1],4); t = 0; for (x = 2; x <= 11; x++) t += f[x]; bt[c] = t; bi[c] = f[5] + f[6] } }
      for (i in A) { split(A[i], f, " "); if (f[1] ~ /^cpu[0-9]/) {
          c = substr(f[1],4); if (!(c in want) || !(c in bt)) continue
          t = 0; for (x = 2; x <= 11; x++) t += f[x]
          dt = t - bt[c]; di = (f[5] + f[6]) - bi[c]
          if (dt > 0) { s += 100 * (dt - di) / dt; k++ } } }
      printf "%.1f", (k ? s / k : -1)
    }'; }
expand() { python3 -c "
import sys
out=[]
for part in sys.argv[1].split(','):
    if '-' in part:
        a,b=part.split('-'); out += [str(x) for x in range(int(a),int(b)+1)]
    else: out.append(part)
print(','.join(out))" "$1"; }
SRV_LIST=$(expand "$SRV_CPUS"); LG_LIST=$(expand "$LG_CPUS")

run_cell() { # arm name pipe command -> appends ops/s, guards saturation
  local arm=$1 name=$2 pipe=$3 cmd=$4
  local before after v
  before=$(cpu_snapshot)
  v=$(taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$PORT" --protocol=redis \
        -t 32 -c 8 --pipeline="$pipe" --command="$cmd" --command-key-pattern=R -d "$DSIZE" \
        --key-minimum=1 --key-maximum="$KEYMAX" --test-time="$SECS" --distinct-client-seed \
        --hide-histogram 2>/dev/null | tr -d '\r' | awk '/^Totals/{print $2; exit}')
  after=$(cpu_snapshot)
  local sb lb; sb=$(cpu_busy "$SRV_LIST" "$before" "$after"); lb=$(cpu_busy "$LG_LIST" "$before" "$after")
  # The question is whether the LOADGEN is the limiter, not whether it is a hair busier. At p128 both
  # sides sit near 72% and neither is saturated; warning on a 2-point gap fires on every cell and
  # teaches you to ignore the guard. Warn only when the loadgen is actually near its ceiling, or
  # dominates the server by a margin no measurement noise explains.
  awk -v s="$sb" -v l="$lb" -v n="$name" -v a="$arm" 'BEGIN{
    if (l >= 90.0)        printf "  WARN %s/%s: loadgen %.1f%% busy -- at its ceiling, cell may be loadgen-bound\n", a, n, l
    else if (l - s > 15.0) printf "  WARN %s/%s: loadgen %.1f%% vs server %.1f%% -- loadgen dominates\n", a, n, l, s
  }' >&2
  echo "${v:-0}" >> "$SP/$arm.$name"
  echo "$sb $lb" >> "$SP/$arm.$name.cpu"
}

MG="MGET __key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__"
MS="MSET __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__"
# name:pipeline:command   -- single-key at its peak (p128) and at p1; multi-key at ITS peak (p8)
CELLS=( "GET_p128:128:GET __key__" "SET_p128:128:SET __key__ __data__"
        "GET_p1:1:GET __key__"     "SET_p1:1:SET __key__ __data__"
        "MGET8_p8:8:$MG"           "MSET8_p8:8:$MS" )

echo "=== MATRIX: $ARMS ==="
echo "    server cores $SRV_CPUS ($NTHREADS), loadgen $LG_CPUS, ${ROUNDS} rounds x ${SECS}s, keyspace $KEYMAX, d=$DSIZE"
echo "    tomokv sha: $(git -C /home/user/Projects/tomokv-cpp-perthread rev-parse --short HEAD)"
for arm in $ARMS; do
  got=$(version_of "$arm"); want=$(expected_version "$arm")
  if [ -n "$want" ] && [ "$got" != "$want" ]; then die "$arm binary reports '$got', pin expects '$want'"; fi
  printf "    %-10s %s\n" "$arm" "${got:-<from worktree>}"
  # Truncate EVERY per-arm result file, the rss ledger included. Leaving $arm.rss to accumulate meant
  # each run's table averaged this run's rows together with every previous run's -- including smoke
  # runs at a different keyspace -- and reported 99MB where the server actually held 158MB.
  for c in "${CELLS[@]}"; do : > "$SP/$arm.${c%%:*}"; : > "$SP/$arm.${c%%:*}.cpu"; done
  : > "$SP/$arm.rss"
done

for r in $(seq "$ROUNDS"); do
  for arm in $ARMS; do
    stop_arm
    boot_arm "$arm" || die "$arm failed to boot"
    populate
    for c in "${CELLS[@]}"; do
      name="${c%%:*}"; rest="${c#*:}"; pipe="${rest%%:*}"; cmd="${rest#*:}"
      run_cell "$arm" "$name" "$pipe" "$cmd"
    done
    # Memory: RSS with the SAME keyspace loaded in every arm, so bytes/key is comparable.
    # Use the pid we launched. `pgrep -x` cannot be given several patterns, and would miss
    # `dragonfly-x86_64` regardless -- comm is truncated at 15 chars and that name is 16.
    if [ "${SRV_PID:-0}" -gt 0 ] && [ -r /proc/$SRV_PID/status ]; then
      echo "${RSS_FULL:-0} ${RSS_HALF:-0} ${RSS_EMPTY:-0}" >> "$SP/$arm.rss"
    else
      echo "  WARN $arm: could not read RSS for pid ${SRV_PID:-none}" >&2
    fi
  done
  echo "  round $r done"
done
stop_arm

# Report each arm as a MULTIPLE OF TOMOKV. "vs best" was useless the moment tomokv was best in every
# cell -- it printed +0.00% and said nothing about the margin over anyone.
printf "\n%-10s" "cell"; for arm in $ARMS; do printf " %14s" "$arm"; done
printf "  |"; for arm in $ARMS; do [ "$arm" = tomokv ] && continue; printf " %10s" "tomo/$arm"; done; echo
for c in "${CELLS[@]}"; do
  name="${c%%:*}"; printf "%-10s" "$name"
  tm=$(awk '{s+=$1;n++} END{printf "%.0f", (n? s/n : 0)}' "$SP/tomokv.$name" 2>/dev/null || echo 0)
  for arm in $ARMS; do
    printf " %14s" "$(awk '{s+=$1;n++} END{printf "%.0f", (n? s/n : 0)}' "$SP/$arm.$name")"
  done
  printf "  |"
  for arm in $ARMS; do
    [ "$arm" = tomokv ] && continue
    om=$(awk '{s+=$1;n++} END{printf "%.0f", (n? s/n : 0)}' "$SP/$arm.$name")
    awk -v t="$tm" -v o="$om" 'BEGIN{ printf " %10s", (o>0 ? sprintf("%.2fx", t/o) : "n/a") }'
  done
  # spread across rounds: a cell whose own arms are noisy cannot support a ratio claim
  printf "   CoV(tomo) %s\n" "$(awk '{s+=$1;q[NR]=$1} END{if(NR<2){print "n/a";exit} m=s/NR;
      for(i=1;i<=NR;i++)v+=(q[i]-m)^2; printf "%.2f%%", 100*sqrt(v/NR)/m}' "$SP/tomokv.$name")"
done
printf "\n%-10s" "RSS empty"; for arm in $ARMS; do
  printf " %14s" "$(awk '{s+=$3;n++} END{printf "%.0f MB", (n? s/n : 0)}' "$SP/$arm.rss" 2>/dev/null)"; done; echo
printf "%-10s" "RSS half";  for arm in $ARMS; do
  printf " %14s" "$(awk '{s+=$2;n++} END{printf "%.0f MB", (n? s/n : 0)}' "$SP/$arm.rss" 2>/dev/null)"; done; echo
printf "%-10s" "RSS full";  for arm in $ARMS; do
  printf " %14s" "$(awk '{s+=$1;n++} END{printf "%.0f MB", (n? s/n : 0)}' "$SP/$arm.rss" 2>/dev/null)"; done; echo
printf "%-10s" "B/key";     for arm in $ARMS; do
  printf " %14s" "$(awk -v k="$KEYMAX" '{d+=($1-$2);n++} END{printf "%.1f", (n&&k? d/n*1048576/(k/2) : 0)}' "$SP/$arm.rss" 2>/dev/null)"; done
printf "   MARGINAL: (full-half)/(keys/2)\n"
