#!/bin/bash
# Permanent unified-binary parity cell.
#
# Compare the candidate booted with tomokv-thread-wb=0 against the last authoritative two-stage
# binary (219ec74cc). The order is B,C,C,B: two samples per arm, interleaved while cancelling most
# warm-box drift. This is one canonical p16 GET cell, not a benchmark sweep.
#
# Required:
#   TOMO_BIN=/path/to/unified/redis-server
#   TOMO_WB0_BASELINE_BIN=/path/to/219ec74cc/redis-server
# Optional:
#   TOMO_RESULT_FILE, TOMO_PORT, TOMO_SERVER_CORES, TOMO_LOADGEN_CORES,
#   TOMO_WB0_DURATION, TOMO_WB0_OPS_TOL_PCT, TOMO_WB0_RSS_TOL_PCT,
#   TOMO_WB0_RSS_TOL_KB, TOMO_REDIS_CLI
#
# The baseline is intentionally external: keeping a second executable in git would make the
# source tree enormous and would hide compiler/build-option drift. Full preflight requires the
# caller to name the known-good artifact explicitly.
set -u

SD=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SD/preflight_lib.sh"

OUT=${TOMO_RESULT_FILE:-/tmp/tomo_wb0_parity.out}
CANDIDATE=${TOMO_BIN:-}
BASELINE=${TOMO_WB0_BASELINE_BIN:-}
PORT=${TOMO_PORT:-5982}
SERVER_CORES=${TOMO_SERVER_CORES:-0-7}
LOADGEN_CORES=${TOMO_LOADGEN_CORES:-16-23}
SMOKE=${SMOKE:-0}
DURATION=${TOMO_WB0_DURATION:-$([ "$SMOKE" = 1 ] && echo 3 || echo 8)}
FILL_DURATION=${TOMO_WB0_FILL_DURATION:-$([ "$SMOKE" = 1 ] && echo 1 || echo 2)}
OPS_TOL_PCT=${TOMO_WB0_OPS_TOL_PCT:-3}
RSS_TOL_PCT=${TOMO_WB0_RSS_TOL_PCT:-2}
RSS_TOL_KB=${TOMO_WB0_RSS_TOL_KB:-1024}

mkdir -p "$(dirname -- "$OUT")"
: > "$OUT"
FAILS=0
pass(){ printf 'PASS\t%s\n' "$1" | tee -a "$OUT"; }
fail(){ printf 'FAIL\t%s\n' "$1" | tee -a "$OUT"; FAILS=$((FAILS+1)); }
note(){ printf 'NOTE\t%s\n' "$1" | tee -a "$OUT"; }

if [ ! -x "$CANDIDATE" ]; then
  fail "candidate missing or not executable: ${CANDIDATE:-unset}"
  exit 1
fi
if [ ! -x "$BASELINE" ]; then
  fail "TOMO_WB0_BASELINE_BIN must name an executable built from 219ec74cc"
  exit 1
fi
if ! command -v memtier_benchmark >/dev/null 2>&1; then
  fail "memtier_benchmark is required"
  exit 1
fi
if ! command -v taskset >/dev/null 2>&1; then
  fail "taskset is required"
  exit 1
fi

CLI_BIN=${TOMO_REDIS_CLI:-$(dirname -- "$CANDIDATE")/redis-cli}
if [ ! -x "$CLI_BIN" ]; then
  CLI_BIN=$(command -v redis-cli 2>/dev/null || true)
fi
if [ -z "$CLI_BIN" ] || [ ! -x "$CLI_BIN" ]; then
  fail "redis-cli was not found beside TOMO_BIN or on PATH"
  exit 1
fi

candidate_sha=$(sha256sum "$CANDIDATE" | awk '{print $1}')
baseline_sha=$(sha256sum "$BASELINE" | awk '{print $1}')
if [ "$candidate_sha" = "$baseline_sha" ]; then
  fail "candidate and baseline binaries are identical; parity comparison would be vacuous"
  exit 1
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/tomo-wb0-parity.XXXXXX") || exit 1
SERVER_PID=
LOAD_PID=
stop_server(){
  if [ -n "${LOAD_PID:-}" ] && kill -0 "$LOAD_PID" 2>/dev/null; then
    kill "$LOAD_PID" 2>/dev/null || true
    wait "$LOAD_PID" 2>/dev/null || true
  fi
  LOAD_PID=
  if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    for _stop_i in $(seq 1 40); do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$SERVER_PID" 2>/dev/null; then kill -9 "$SERVER_PID" 2>/dev/null || true; fi
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  SERVER_PID=
}
cleanup(){ stop_server; rm -rf -- "$WORK"; }
trap cleanup EXIT
trap 'exit 130' TERM INT HUP

# Private comm names prevent this cell and the preflight reaper from touching a shared server.
if ! cp "$BASELINE" "$WORK/redis-wb0b" || ! cp "$CANDIDATE" "$WORK/redis-wb0c"; then
  fail "could not stage the parity binaries"
  exit 1
fi
chmod +x "$WORK/redis-wb0b" "$WORK/redis-wb0c"

CLI=("$CLI_BIN" -p "$PORT")
rss_kb(){
  awk '/^VmRSS:/{print $2; found=1; exit} END{if (!found) print 0}' "/proc/$1/status" 2>/dev/null
}

run_cell(){ # role round
  # Assign positional parameters before deriving paths. In one compound `local` statement bash
  # expands the path RHS before the sibling role/round assignments take effect; under `set -u`
  # that aborted the suite with no scored check and bypassed its normal RESULT discipline.
  local role round bin data log bench
  local -a extra=()
  role=$1
  round=$2
  data="$WORK/data-$role-$round"
  log="$WORK/$role-$round.log"
  bench="$WORK/$role-$round.memtier"
  local up=0 idle peak rss ops alive crash cfg rc=0
  stop_server
  if ! wait_port_free "$PORT"; then
    fail "$role/$round port $PORT already has a listener"
    return 1
  fi
  mkdir -p "$data"
  if [ "$role" = candidate ]; then
    bin="$WORK/redis-wb0c"
    extra=(--tomokv-thread-wb 0)
  else
    bin="$WORK/redis-wb0b"
  fi

  taskset -c "$SERVER_CORES" "$bin" \
    --port "$PORT" --dir "$data" --save '' --appendonly no --protected-mode no \
    --logfile "$log" --loglevel notice \
    --tomokv-nodes 1 --tomokv-cores-per-node 8 \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-thread-mode static \
    --tomokv-pin-mode float --tomokv-pipeline-depth 16 --tomokv-io-uring 0 \
    --tomokv-key-lb 0 --tomokv-client-lb no "${extra[@]}" \
    >/dev/null 2>&1 &
  SERVER_PID=$!
  for _boot_i in $(seq 1 80); do
    timeout 2 "${CLI[@]}" ping 2>/dev/null | grep -q PONG && { up=1; break; }
    kill -0 "$SERVER_PID" 2>/dev/null || break
    sleep 0.1
  done
  if [ "$up" != 1 ]; then
    fail "$role/$round did not boot; log=$log"
    stop_server
    return 1
  fi
  if ! server_identity_ok "$CLI_BIN" "$PORT" "$SERVER_PID" >/dev/null 2>&1; then
    fail "$role/$round failed the SO_REUSEPORT identity check"
    stop_server
    return 1
  fi

  cfg=$(timeout 2 "${CLI[@]}" config get tomokv-thread-wb 2>/dev/null | tr -d '\r')
  if [ "$role" = baseline ]; then
    if [ -n "$cfg" ]; then
      fail "baseline exposes tomokv-thread-wb; expected the authoritative 219ec74cc binary"
    fi
  elif [ "$(printf '%s\n' "$cfg" | tail -1)" != 0 ]; then
    fail "candidate did not report effective tomokv-thread-wb=0"
  fi

  idle=$(rss_kb "$SERVER_PID")
  timeout 30 taskset -c "$LOADGEN_CORES" memtier_benchmark \
    -s 127.0.0.1 -p "$PORT" --hide-histogram --test-time "$FILL_DURATION" \
    --ratio=1:0 --data-size=32 --key-pattern=R:R --key-minimum=1 --key-maximum=200000 \
    -t 4 -c 16 --pipeline 16 >/dev/null 2>&1 || rc=$?
  if [ "$rc" -ne 0 ]; then
    fail "$role/$round prefill failed (exit $rc)"
    stop_server
    return 1
  fi

  timeout "$((DURATION + 20))" taskset -c "$LOADGEN_CORES" memtier_benchmark \
    -s 127.0.0.1 -p "$PORT" --hide-histogram --test-time "$DURATION" \
    --ratio=0:1 --data-size=32 --key-pattern=R:R --key-minimum=1 --key-maximum=200000 \
    -t 8 -c 25 --pipeline 16 >"$bench" 2>&1 &
  LOAD_PID=$!
  peak=$idle
  for _rss_i in $(seq 1 "$(((DURATION + 20) * 10))"); do
    kill -0 "$LOAD_PID" 2>/dev/null || break
    rss=$(rss_kb "$SERVER_PID")
    [ "${rss:-0}" -gt "${peak:-0}" ] 2>/dev/null && peak=$rss
    sleep 0.1
  done
  wait "$LOAD_PID" || rc=$?
  LOAD_PID=
  ops=$(awk '/^Totals/{print int($2); exit}' "$bench")
  alive=$(timeout 2 "${CLI[@]}" ping 2>/dev/null | tr -d '\r')
  crash=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED' "$log" 2>/dev/null || true)

  if [ ! -s "$WORK/$role.info" ]; then
    timeout 3 "${CLI[@]}" info all 2>/dev/null | tr -d '\r' > "$WORK/$role.info"
  fi
  if [ "$rc" -ne 0 ] || [ "${ops:-0}" -le 1000 ] 2>/dev/null ||
     [ "$alive" != PONG ] || [ "${crash:-0}" -ne 0 ]; then
    fail "$role/$round invalid: memtier_rc=$rc ops=${ops:-missing} alive=${alive:-no} crashes=${crash:-0}"
  else
    printf '%s\t%s\t%s\t%s\t%s\n' "$role" "$round" "$ops" "$idle" "$peak" >> "$WORK/samples.tsv"
    note "$role/$round ops=$ops idle_rss_kb=$idle peak_rss_kb=$peak"
  fi
  stop_server
  wait_port_free "$PORT" || fail "$role/$round left port $PORT occupied"
}

# Thermal-balanced two-sample interleave.
run_cell baseline 1 || true
run_cell candidate 1 || true
run_cell candidate 2 || true
run_cell baseline 2 || true

if [ ! -f "$WORK/samples.tsv" ] || [ "$(awk 'END{print NR}' "$WORK/samples.tsv" 2>/dev/null)" -ne 4 ]; then
  fail "parity metrics incomplete; expected four valid samples"
else
  mean_metric(){
    awk -F '\t' -v role="$1" -v col="$2" '$1==role{s+=$col;n++} END{if(n)printf "%.2f",s/n;else print 0}' "$WORK/samples.tsv"
  }
  base_ops=$(mean_metric baseline 3); cand_ops=$(mean_metric candidate 3)
  base_idle=$(mean_metric baseline 4); cand_idle=$(mean_metric candidate 4)
  base_peak=$(mean_metric baseline 5); cand_peak=$(mean_metric candidate 5)
  ops_delta=$(awk -v b="$base_ops" -v c="$cand_ops" 'BEGIN{d=c-b;if(d<0)d=-d;printf "%.2f",b?100*d/b:100}')
  if awk -v d="$ops_delta" -v t="$OPS_TOL_PCT" 'BEGIN{exit !(d<=t)}'; then
    pass "p16get mean parity: baseline=$base_ops candidate=$cand_ops delta=${ops_delta}% tolerance=${OPS_TOL_PCT}%"
  else
    fail "p16get mean drift: baseline=$base_ops candidate=$cand_ops delta=${ops_delta}% tolerance=${OPS_TOL_PCT}%"
  fi

  check_rss(){ # label baseline candidate
    local label=$1 b=$2 c=$3 delta allowed
    delta=$(awk -v b="$b" -v c="$c" 'BEGIN{d=c-b;if(d<0)d=-d;printf "%.0f",d}')
    allowed=$(awk -v b="$b" -v p="$RSS_TOL_PCT" -v k="$RSS_TOL_KB" \
      'BEGIN{x=b*p/100;if(x<k)x=k;printf "%.0f",x}')
    if awk -v d="$delta" -v a="$allowed" 'BEGIN{exit !(d<=a)}'; then
      pass "$label RSS parity: baseline=${b}KB candidate=${c}KB delta=${delta}KB allowed=${allowed}KB"
    else
      fail "$label RSS drift: baseline=${b}KB candidate=${c}KB delta=${delta}KB allowed=${allowed}KB"
    fi
  }
  check_rss idle "$base_idle" "$cand_idle"
  check_rss load-peak "$base_peak" "$cand_peak"
fi

if [ -s "$WORK/baseline.info" ] && [ -s "$WORK/candidate.info" ]; then
  awk -F: '/^[A-Za-z0-9_]+:/{print $1}' "$WORK/baseline.info" | sort -u > "$WORK/baseline.keys"
  awk -F: '/^[A-Za-z0-9_]+:/{print $1}' "$WORK/candidate.info" | sort -u > "$WORK/candidate.keys"
  comm -23 "$WORK/baseline.keys" "$WORK/candidate.keys" > "$WORK/removed.keys"
  comm -13 "$WORK/baseline.keys" "$WORK/candidate.keys" > "$WORK/added.keys"
  # Consolidation-deliberate INFO surface changes vs the pre-unification 219ec74cc baseline:
  # the atomic ship stack replaced its counter set (old commit_wait/stamp_full fields removed,
  # owner-epoch/prune/reclaim/read-slow fields added), the decref-race fence added its witness
  # counter, the passive u1 substrate added its three gauges, r10 added its seven climb witnesses,
  # the m1 shadow added its five gauges and model mode added four actuation witnesses,
  # and the prefetch knob deletion removed the io/ex prefetch counters. Anything OUTSIDE these
  # named sets is still drift and fails.
  grep -vE '^tomokv_wb_|^tomokv_u1_(sigma|windows|settle_ticks_last)$|^tomokv_r10_(episodes|dead_arm_episodes|rungs_climbed_last|anchor_io_n[01]|cmp_better|cmp_flat)$|^tomokv_m1_(target_io_n[01]|cio|cex|depth|moves_total|target_changes|arm_refusals|holds)$|^tomokv_atomic_(commit_ts|commit_ts_lag|owner_epochs_queued|owner_pending|owner_pending_max|owner_versions_queued|prune_batch_allocs|prune_node_allocs|prune_qsbr_wait_passes|prune_snapshot_wait_passes|read_slow_gate_closed_other|read_slow_inflight_conflict|reclaim_bytes|reclaim_limit|reclaim_pressure|reclaim_stalls|reclaim_worker_bytes|reclaim_worker_max|stragglers|window_effective)$|^tomokv_freeback_stale_owner_drains$' \
    "$WORK/added.keys" > "$WORK/unexpected-added.keys" || true
  grep -vE '^tomokv_atomic_(commit_wait_drains|stamp_full)$|^tomokv_prefetch_(ex|io)_xnode_issued$|^tomo_prefetch_issued$' \
    "$WORK/removed.keys" > "$WORK/unexpected-removed.keys" || true
  mv "$WORK/unexpected-removed.keys" "$WORK/removed.keys"
  if [ -s "$WORK/removed.keys" ] || [ -s "$WORK/unexpected-added.keys" ]; then
    fail "INFO key-set drift outside allowed observability additions: removed=$(tr '\n' ',' < "$WORK/removed.keys") added=$(tr '\n' ',' < "$WORK/unexpected-added.keys")"
  else
    pass "INFO key set matches baseline modulo named observability additions"
  fi
  wb_nonzero=$(awk -F: '$1 ~ /^tomokv_wb_/ {v=$2; gsub(/\r/,"",v); if (v !~ /^0([.]0+)?$/) print $1 "=" v}' "$WORK/candidate.info")
  if [ -n "$wb_nonzero" ]; then
    fail "wb=0 INFO exposes non-zero WB state: $(printf '%s' "$wb_nonzero" | tr '\n' ' ')"
  else
    pass "all candidate tomokv_wb_* fields are zero at wb=0"
  fi
else
  fail "missing INFO snapshots"
fi

note "candidate_sha256=$candidate_sha baseline_sha256=$baseline_sha order=B,C,C,B"
if [ "$FAILS" -eq 0 ]; then
  printf 'RESULT\tPASS\n' | tee -a "$OUT"
  exit 0
fi
printf 'RESULT\tFAIL\t%s check(s)\n' "$FAILS" | tee -a "$OUT"
exit 1
