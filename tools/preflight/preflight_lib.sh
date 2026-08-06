# preflight_lib.sh — shared port-safety helpers (defeat SO_REUSEPORT silent split).
#
# THE BUG THESE DEFEAT. Every IO thread holds its own SO_REUSEPORT listener on the
# server's port. If a leaked or co-scheduled server is still alive on that port when a
# suite boots its own, the kernel silently load-balances NEW connections across BOTH —
# the suite then measures a blend of two binaries. A bind never fails, so the split is
# invisible. The authority is the PORT, not the process name: suites stage binaries
# under private names, so pgrep-by-name misses a leaker. These helpers gate on the port.
#
# Source-able with no side effects. POSIX-bash, no `set -e`, self-contained.

# port_has_listener <port>: 0 (true) if anything is LISTENing on the TCP port.
port_has_listener() { ss -ltn "sport = :$1" 2>/dev/null | grep -q ":$1"; }

# wait_port_free <port>: block until the port has no listener (up to ~10s); return 1 if
# it never frees. Call this BEFORE launching so a leaked server cannot join our accept
# group under SO_REUSEPORT.
wait_port_free() { local p=$1 i; for i in $(seq 1 100); do port_has_listener "$p" || return 0; sleep 0.1; done; return 1; }

# server_identity_ok <cli> <port> <pid>: N fresh INFO conns must ALL land on our pid.
# If any connection is answered by a different process_id, a second listener is stealing
# a share of our traffic (the silent split) and every measurement on this port is void.
server_identity_ok() { local cli=$1 port=$2 pid=$3 i got; for i in $(seq 1 8); do
  got=$(timeout 2 "$cli" -p "$port" info server 2>/dev/null | tr -d '\r' | sed -n 's/^process_id://p')
  [ "$got" = "$pid" ] || { echo "SO_REUSEPORT split: conn hit pid=$got not $pid on :$port" >&2; return 1; }
  done; return 0; }
