#!/usr/bin/env bash
# Bench quiescence guard (source me, then call bench_guard_wait). This box may run OTHER agents
# (e.g. Codex) whose builds/benches contaminate timings — a concurrent load spike once faked a
# persistent multi-key-write "wedge" and +-30% same-code drift. Refuses to proceed until:
#   - no foreign redis-server / memtier processes (i.e. none besides those on MY_PORTS), and
#   - 1-min loadavg <= BG_MAXLOAD (default 1.5) on two consecutive checks 15s apart.
# Gives up (returns 1, loudly) after BG_TIMEOUT seconds (default 1800) so callers can bail.
# Usage:  source harness/bench_guard.sh; MY_PORTS="6520 6521" bench_guard_wait || exit 1
bench_guard_wait(){
  local maxload=${BG_MAXLOAD:-1.5} timeout=${BG_TIMEOUT:-1800} myports=" ${MY_PORTS:-} "
  local t0=$SECONDS ok=0
  while [ $((SECONDS-t0)) -lt "$timeout" ]; do
    local busy=""
    # foreign redis-server/memtier: any whose cmdline doesn't mention one of MY_PORTS
    while read -r pid cmd; do
      [ -z "$pid" ] && continue
      local mine=0 p
      for p in $myports; do case "$cmd" in *"$p"*) mine=1;; esac; done
      [ $mine = 0 ] && busy="$busy [$pid:$(echo "$cmd"|cut -c1-40)]"
    done < <(pgrep -a 'redis-server|memtier' 2>/dev/null)
    local load; load=$(awk '{print $1}' /proc/loadavg)
    if [ -n "$busy" ]; then ok=0; echo "bench_guard: foreign bench procs:$busy — waiting"; sleep 15; continue; fi
    if awk -v l="$load" -v m="$maxload" 'BEGIN{exit !(l<=m)}'; then
      ok=$((ok+1))
      [ $ok -ge 2 ] && { echo "bench_guard: quiet (load=$load) — proceeding"; return 0; }
      echo "bench_guard: load=$load ok($ok/2) — confirming"; sleep 15
    else
      ok=0; echo "bench_guard: load=$load > $maxload — waiting"; sleep 15
    fi
  done
  echo "bench_guard: TIMED OUT after ${timeout}s (still busy) — DO NOT trust timings" >&2
  return 1
}
