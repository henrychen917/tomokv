#!/bin/bash
# Lane helper for t-execfix: boot/stop by LISTENER pid only.  Never pkill by name/pattern.
# Cores 0-5 = server (2 io + 4 ex, one thread per core), 6-7 = loadgen/oracle.
# Ports 7080 (target) / 7081 (oracle) only.
LANE_CORES=${LANE_CORES:-0-5}
LANE_PORT=${LANE_PORT:-7080}
LANE_RATIO=${LANE_RATIO:-2:4}
LANE_LOGDIR=${LANE_LOGDIR:-/tmp/claude-1000/execfix}

listener_pid() { # $1 = port
    ss -lntpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2
}

lane_free() { # $1 = port -> 0 if nobody is listening
    [ -z "$(listener_pid "$1")" ]
}

lane_boot() { # $1 = binary  $2 = port  $3.. = extra args ; sets LANE_PID / LANE_LOG
    local bin=$1 port=$2; shift 2
    mkdir -p "$LANE_LOGDIR"
    if ! lane_free "$port"; then
        echo "REFUSE: port $port already has a listener (pid $(listener_pid "$port"))" >&2
        return 1
    fi
    LANE_LOG=$(mktemp "$LANE_LOGDIR/lane-srv.XXXXXX")
    taskset -c "$LANE_CORES" "$bin" --port "$port" --bind 127.0.0.1 \
        --shards ${SHARDS:-16} --ratio "$LANE_RATIO" "$@" > "$LANE_LOG" 2>&1 &
    LANE_PID=$!
    for _ in $(seq 1 150); do
        if (exec 3<>/dev/tcp/127.0.0.1/"$port") 2>/dev/null; then exec 3<&- 3>&-; break; fi
        sleep 0.1
    done
    if ! kill -0 "$LANE_PID" 2>/dev/null; then
        echo "BOOT FAILED, log:" >&2; cat "$LANE_LOG" >&2; return 1
    fi
    local lp; lp=$(listener_pid "$port")
    if [ "$lp" != "$LANE_PID" ]; then
        echo "WARNING: listener pid $lp != spawned $LANE_PID on port $port" >&2
    fi
    return 0
}

lane_stop() { # $1 = port  (resolves pid FROM the listener, verifies it is gone)
    local port=$1 pid
    pid=$(listener_pid "$port")
    [ -z "$pid" ] && return 0
    kill -TERM "$pid" 2>/dev/null
    for _ in $(seq 1 150); do
        lane_free "$port" && break
        sleep 0.1
    done
    if ! lane_free "$port"; then
        pid=$(listener_pid "$port"); kill -KILL "$pid" 2>/dev/null
        for _ in $(seq 1 50); do lane_free "$port" && break; sleep 0.1; done
    fi
    if ! lane_free "$port"; then
        echo "STOP FAILED: port $port still has listener pid $(listener_pid "$port")" >&2
        return 1
    fi
    wait "$pid" 2>/dev/null
    return 0
}

oracle_boot() { # redis 7.4 oracle on 7081, core 6
    local redis=${REDIS:-/tmp/claude-1000/redis74/src/redis-server}
    mkdir -p "$LANE_LOGDIR"
    if ! lane_free 7081; then
        echo "oracle already listening on 7081 (pid $(listener_pid 7081))" >&2; return 0
    fi
    # LC_ALL=C: the oracle's collation locale otherwise shows up as phantom SORT ... ALPHA diffs
    # that are the ORACLE's, not ours (reported by lane t-edgeenc).
    # setsid: the oracle outlives this shell, so a lane script exiting cannot take it down mid-run.
    LC_ALL=C setsid taskset -c 6 "$redis" --port 7081 --bind 127.0.0.1 --save '' --appendonly no \
        --protected-mode no > "$LANE_LOGDIR/redis-oracle.log" 2>&1 < /dev/null &
    for _ in $(seq 1 100); do
        if (exec 3<>/dev/tcp/127.0.0.1/7081) 2>/dev/null; then exec 3<&- 3>&-; break; fi
        sleep 0.1
    done
    [ -n "$(listener_pid 7081)" ] || { echo "oracle boot failed" >&2; return 1; }
}
