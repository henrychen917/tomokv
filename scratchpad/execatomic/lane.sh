#!/bin/bash
# Lane helper for t-execatomic: boot/stop by LISTENER pid only.  Never pkill by name/pattern.
# Cores 32-47 = server, 48-63 = contention spinners, ports 7019 (target) / 7020 (oracle).
LANE_CORES=${LANE_CORES:-32-47}
LANE_PORT=${LANE_PORT:-7019}

listener_pid() { # $1 = port
    ss -lntpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2
}

lane_free() { # $1 = port -> 0 if nobody is listening
    [ -z "$(listener_pid "$1")" ]
}

lane_boot() { # $1 = binary  $2 = port  $3.. = extra args ; sets LANE_PID / LANE_LOG
    local bin=$1 port=$2; shift 2
    if ! lane_free "$port"; then
        echo "REFUSE: port $port already has a listener (pid $(listener_pid "$port"))" >&2
        return 1
    fi
    LANE_LOG=$(mktemp /tmp/claude-1000/execatomic/lane-srv.XXXXXX)
    taskset -c "$LANE_CORES" "$bin" --port "$port" --bind 127.0.0.1 --shards 16 --ratio ${RATIO:-6:10} \
        "$@" > "$LANE_LOG" 2>&1 &
    LANE_PID=$!
    for _ in $(seq 1 100); do
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
    for _ in $(seq 1 100); do
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
