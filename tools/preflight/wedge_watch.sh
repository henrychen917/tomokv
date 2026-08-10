#!/bin/bash
# wedge_watch.sh -- catch a server that still ANSWERS but no longer SERVES, and capture why.
#
# Written for docs/BUGS.md N, where run 4 of stress_validation showed the exact signature this
# watches for: memtier got nothing for 140 s, lanes timed out, the flip controller stopped printing
# its 5-second line -- and a fresh PING answered instantly the whole time. That combination is not
# "the server died", it is "the data plane stopped while the accept path kept working", and it is
# why `fail()`'s PING control was the wrong control (see docs/BUGS.md N and M).
#
# PING is served on an IO thread and needs no worker, so PING liveness says nothing about whether
# workers are running. total_commands_processed does. This polls the counter, and when it stops
# advancing while PING still answers, it grabs every server thread's stack -- which is the evidence
# a timeout alone can never give you.
#
# usage: wedge_watch.sh <server-pid> <port> [outdir] [stall-secs] [max-captures]
#   backgrounded next to a soak:  tools/preflight/wedge_watch.sh $PID 7911 /tmp/w 10 3 &
set -u

PID=${1:?usage: wedge_watch.sh <server-pid> <port> [outdir] [stall-secs] [max-captures]}
PORT=${2:?usage: wedge_watch.sh <server-pid> <port> [outdir] [stall-secs] [max-captures]}
OUT=${3:-$(mktemp -d "${TMPDIR:-/tmp}/wedge.XXXXXX")}
STALL=${4:-10}          # seconds of zero command progress before we call it a wedge
MAXCAP=${5:-3}          # stop after this many captures; a wedge that repeats is still one story
POLL=${6:-2}

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CLI=$DIR/../../src/redis-cli
[ -x "$CLI" ] || CLI=$(command -v redis-cli)
mkdir -p "$OUT"

info_field() {  # info_field <section> <field>
    timeout 5 "$CLI" -p "$PORT" info "$1" 2>/dev/null | tr -d '\r' \
        | awk -F: -v f="$2" '$1==f {print $2; exit}'
}

# SELF-PERTURBATION, and it is not a detail: polling INFO is itself a command, so
# total_commands_processed advances on every poll BY OUR OWN DOING. A first version compared
# cur != last and therefore could never observe a stall -- it reported healthy against a server
# with literally zero client traffic. Require the counter to move by MORE than our own probes
# could account for. redis-cli also sends CLIENT SETINFO on connect, so budget a few per poll;
# the discrimination is unharmed either way, because a serving server does millions per second
# and a wedged one does exactly ours.
SELF_ALLOWANCE=${SELF_ALLOWANCE:-50}

echo "wedge_watch: pid=$PID port=$PORT stall=${STALL}s self_allowance=$SELF_ALLOWANCE out=$OUT" >&2
last=""; last_change=$(date +%s); caps=0

while kill -0 "$PID" 2>/dev/null && [ "$caps" -lt "$MAXCAP" ]; do
    sleep "$POLL"
    cur=$(info_field stats total_commands_processed)
    now=$(date +%s)

    if [ -z "$cur" ]; then
        # INFO itself timed out. That is a HARDER symptom than the one we are hunting, not a
        # softer one: INFO is served inline on an IO thread, so an unanswerable INFO means that
        # thread is gone too.
        #
        # An earlier version logged this line and `continue`d -- which skipped the capture block
        # below entirely. On 2026-08-03 it recorded "INFO did not answer" 18 times across ten
        # minutes of a genuine wedge and captured NOTHING, because the only path to the stack dump
        # ran through the branch it had just jumped over. The diagnosis had to be taken by hand
        # afterwards. Falling through is the whole point: this is the case we most want a stack for.
        echo "$(date +%H:%M:%S) INFO did not answer" >>"$OUT/timeline"
        unanswerable=1
    else
        unanswerable=0
        if [ -z "$last" ]; then last=$cur; last_change=$now; continue; fi
        if [ $((cur - last)) -gt "$SELF_ALLOWANCE" ]; then last=$cur; last_change=$now; continue; fi
        last=$cur
    fi

    stalled=$((now - last_change))
    [ "$stalled" -lt "$STALL" ] && continue

    # Commands have not advanced for $stalled s. Is it wedged, or just idle? An idle server is
    # boring and must not trigger: ask whether anyone is actually WAITING on it. Skip that question
    # entirely when INFO is unanswerable -- we cannot ask it, and "the server stopped answering"
    # is never the idle case.
    if [ "$unanswerable" = 0 ]; then
        conns=$(info_field clients connected_clients); conns=${conns:-0}
        if [ "${conns:-0}" -le 1 ]; then last_change=$now; continue; fi   # nobody but us: idle
    else
        conns="unknown (INFO unanswerable)"
    fi

    caps=$((caps + 1))
    snap=$OUT/wedge-$caps.txt
    echo "$(date +%H:%M:%S) WEDGE: commands flat at $cur (<=$SELF_ALLOWANCE/poll, i.e. only our own probes) for ${stalled}s with $conns clients -> $snap" | tee -a "$OUT/timeline" >&2
    {
        echo "### wedge capture $caps at $(date -Is)"
        echo "### total_commands_processed flat at $cur for ${stalled}s, connected_clients=$conns"
        echo; echo "--- PING (the control that lies: it needs no worker) ---"
        timeout 5 "$CLI" -p "$PORT" ping 2>&1 | tr -d '\r'
        echo; echo "--- a command that DOES need a worker ---"
        timeout 5 "$CLI" -p "$PORT" set wedgeprobe 1 2>&1 | tr -d '\r'
        timeout 5 "$CLI" -p "$PORT" get wedgeprobe 2>&1 | tr -d '\r'
        echo; echo "--- INFO tomokv (resize/flip state) ---"
        timeout 5 "$CLI" -p "$PORT" info tomokv 2>&1 | tr -d '\r'
        echo; echo "--- INFO clients / persistence ---"
        timeout 5 "$CLI" -p "$PORT" info clients 2>&1 | tr -d '\r'
        timeout 5 "$CLI" -p "$PORT" info persistence 2>&1 | tr -d '\r' | grep -E '^(loading|async_loading|rdb_)'
        echo; echo "--- CLIENT LIST ---"
        timeout 8 "$CLI" -p "$PORT" client list 2>&1 | tr -d '\r' | head -40
        echo; echo "--- threads ---"
        ps -L -o tid,pcpu,stat,wchan:28,comm -p "$PID" 2>&1 | head -60
    } >"$snap" 2>&1

    # ALL-THREAD STACKS, without ptrace. gdb cannot attach here: yama ptrace_scope is 1 and the
    # server is our SIBLING, not our descendant, so `gdb -p` dies with "Could not attach" -- which
    # is silent unless you look, and cost a whole capture the first time. Raising ptrace_scope
    # needs a sudo password, so instead use the server's own facility: debug.c's SIGALRM handler
    # explicitly supports an EXPLICITLY SENT alarm ("SIGALRM can be sent explicitly ... to get the
    # stacktraces") and calls logStackTrace(..., current_thread=0), which routes to
    # writeStacktraces() and walks EVERY thread via the ThreadsManager. The stacks land in the
    # server's own log, so slice them out if we were told where that is.
    log_before=0
    [ -n "${SERVER_LOG:-}" ] && [ -f "${SERVER_LOG:-}" ] && log_before=$(wc -l <"$SERVER_LOG")
    kill -ALRM "$PID" 2>/dev/null && echo "  sent SIGALRM for an all-thread stack dump" >>"$snap"
    sleep 3
    {
        echo; echo "--- ALL THREAD STACKS (via SIGALRM -> writeStacktraces) ---"
        if [ -n "${SERVER_LOG:-}" ] && [ -f "${SERVER_LOG:-}" ]; then
            tail -n +$((log_before + 1)) "$SERVER_LOG"
        else
            echo "SERVER_LOG not set -- stacks are in the server's log around $(date -Is)"
        fi
        # best effort only; expected to fail under ptrace_scope=1, kept because it costs nothing
        # and is the better output on a box where it IS permitted.
        if timeout 20 gdb -p "$PID" -batch -nx -ex 'set pagination off' -ex 'thread apply all bt 20' \
                >"$OUT/.gdb.$caps" 2>&1 && ! grep -q 'Could not attach' "$OUT/.gdb.$caps"; then
            echo; echo "--- gdb (also available) ---"; tail -200 "$OUT/.gdb.$caps"
        fi
        rm -f "$OUT/.gdb.$caps"
    } >>"$snap" 2>&1
    last_change=$(date +%s)
done
echo "wedge_watch: done (captures=$caps) $OUT" >&2
