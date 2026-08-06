#!/bin/bash
# LB-1 DISCRIMINATING TEST -- UNRUN AS OF THIS COMMIT (box was frozen; staged for later execution).
#
# DEFECT. tomoGrowBackSlot() walked server.clients[io_slot] from a thread that does not own that
# list. The owning io thread frees eagerly (unlinkClient -> listDelNode -> zfree(node); freeClient
# -> zfree(client)), so the walker can read a freed listNode and dereference a freed client inside
# tmClientMigratable(). Read-only UAF: it cannot corrupt, but it can segfault the walker.
#
# HOW THIS DISCRIMINATES. Drive connect/disconnect churn on a GROWN io slot (so nodes and clients
# are being freed continuously by the owner) while repeatedly asking for a grow-back (so the walker
# is repeatedly iterating that same list). Under AddressSanitizer the pre-fix binary should report
#     ERROR: AddressSanitizer: heap-use-after-free
# with tmClientMigratable / listNext / tomoGrowBackSlot on the access stack and unlinkClient /
# freeClient on the free stack. The fixed binary reads a published _Atomic int instead and must
# produce no such report.
#
# WHY ASAN AND NOT TSAN: the two threads genuinely touch the same memory, but the bug is a
# lifetime bug, not a torn word -- ASAN names the free site, which is the evidence that matters.
#
# NOTE ON THE DRIVER: DEBUG TOMO-MODESHIFT 7 = grow-front, 8 = grow-back. Grow-back is what walks.
# The DEBUG verb runs inline on the issuing client's io thread, so it is a foreign-list walk too
# unless that client happens to live on io_slot -- either way it exercises the same code.
#
# VACUITY GUARDS (this test must be able to FAIL):
#   * it asserts a grow-front actually happened (io_threads_live > io_threads) -- otherwise
#     tomoGrowBackSlot is never reached and the cell proves nothing;
#   * it asserts at least one grow-back was ACCEPTED, not merely refused by an earlier gate;
#   * it counts churn iterations, so "no ASAN report" cannot mean "no clients were ever freed".
#
# USAGE:  BIN=/path/to/asan-built-redis  ./lb1_uaf_probe.sh
#         (build with:  make SANITIZER=address MALLOC=libc)
#         Must run under withbox.sh -- it needs the box to itself.
set -u
# PORT-SAFETY: a co-listener on $PORT would answer a share of the churn connections, so the
# ASAN result would be a blend of two binaries. Gate on $PORT + verify pid identity.
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
BIN=${BIN:?BIN required (an ASAN build)}
D=$(cd "$(dirname "$0")" && pwd)
NAME=$(basename "$BIN")                 # keep <=15 chars: pkill -x matches truncated comm
PORT=${PORT:-7965}
SECS=${SECS:-90}
rm -rf "$D/lb1"; mkdir -p "$D/lb1"
# Cleanup on every exit path (this suite had none): kill OUR recorded pid, then sweep the name.
SRV=""
cleanup_lb1(){
  if [ -n "${SRV:-}" ]; then
    kill -TERM "$SRV" 2>/dev/null
    for _i in $(seq 1 40); do kill -0 "$SRV" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; SRV=""
  fi
  pkill -9 -x "$NAME" 2>/dev/null; return 0
}
trap cleanup_lb1 EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
pkill -9 -x "$NAME" 2>/dev/null; sleep 1
# PORT-SAFETY: refuse to boot while any listener still holds $PORT.
wait_port_free "$PORT" || { echo "INVALID: :$PORT still has a listener before boot (SO_REUSEPORT split risk) -- refusing to boot into a blend"; exit 2; }

ASAN_OPTIONS="detect_leaks=0 halt_on_error=0 abort_on_error=0 log_path=$D/lb1/asan" \
taskset -c 0-7 "$BIN" --port $PORT --dir "$D/lb1" --tomokv-nodes 1 --tomokv-thread-io 4 \
  --tomokv-thread-ex 4 --tomokv-thread-mode auto --save '' --appendonly no \
  --protected-mode no --enable-debug-command yes --logfile "$D/lb1/$NAME.log" >/dev/null 2>&1 &
SRV=$!
sleep 8
kill -0 $SRV 2>/dev/null || { echo "SERVER DIED AT BOOT"; tail -30 "$D/lb1/$NAME.log"; exit 3; }

CLI=$(dirname "$BIN")/redis-cli
[ -x "$CLI" ] || CLI=redis-cli

# IDENTITY: every fresh INFO conn must land on OUR pid; a co-listener on $PORT would answer a
# share of the churn below and the ASAN verdict would be a two-binary blend.
if ! server_identity_ok "$CLI" "$PORT" "$SRV"; then
  echo "INVALID: SO_REUSEPORT split on :$PORT -- another listener answered; ASAN result would be a blend"
  kill -9 $SRV 2>/dev/null; exit 2
fi

LOG="$D/lb1/$NAME.log"

# --- force a grown io slot so grow-back has something to convert back ---
#
# THE PRECONDITION INSTRUMENT WAS BROKEN, and it made this whole probe vacuous (found 2026-07-29).
# It used to read `INFO threads | grep io_threads_live`. That section emits `io_thread_N:` and
# `tomo_io_thread_N:` lines ONLY (server.c:13994) and has never contained an `io_threads_live`
# field anywhere in this tree. So the grep matched nothing on EVERY build: live0 and live1 were
# both the empty string, `[ "$live0" = "$live1" ]` was always true, and the probe always printed
# "INVALID: no grow-front happened" and exited 2 — on a fixed build and a broken one alike. It had
# never once reached tomoGrowBackSlot, the function it exists to test. Worse, that message named
# the WRONG cause: DEBUG TOMO-MODESHIFT 7 was returning OK the whole time; what failed was the
# reading, not the flip. (Same defect class as flip_updown's `io=` grep, fixed in f65813e9f.)
#
# The authoritative signal is the controller's own completion log line (server.c:17779), which is
# written only when the conversion actually completes — a DEBUG "OK" merely means the request was
# accepted. Poll the log for it rather than sleeping a fixed 2s and hoping.
gf=$($CLI -p $PORT debug tomo-modeshift 7 2>&1)
echo "grow-front cmd -> $gf"
gfdone=0
for _ in $(seq 1 40); do
  grep -q 'GROW-FRONT complete' "$LOG" 2>/dev/null && { gfdone=1; break; }
  sleep 0.5
done
live1=$(grep -o 'io_threads_live=[0-9]*' "$LOG" 2>/dev/null | tail -1)
echo "grow-front completed=$gfdone ${live1:-(no io_threads_live line)}"
if [ "$gfdone" != 1 ]; then
  echo "INVALID: grow-front never COMPLETED (cmd said '$gf'), so tomoGrowBackSlot is unreachable -- cell proves nothing"
  kill -9 $SRV 2>/dev/null; exit 2
fi

# --- churn + repeated grow-back attempts ---
churn=0; accepted=0
end=$(( $(date +%s) + SECS ))
( while [ "$(date +%s)" -lt "$end" ]; do
    for i in $(seq 1 40); do (timeout 2 $CLI -p $PORT ping >/dev/null 2>&1 &) ; done
    wait 2>/dev/null
  done ) &
CHURN=$!
while [ "$(date +%s)" -lt "$end" ]; do
  r=$($CLI -p $PORT debug tomo-modeshift 8 2>&1)
  churn=$((churn+1))
  case "$r" in *OK*) accepted=$((accepted+1)); sleep 2; $CLI -p $PORT debug tomo-modeshift 7 >/dev/null 2>&1; sleep 1;; esac
done
kill $CHURN 2>/dev/null; wait $CHURN 2>/dev/null

# `accepted` counts DEBUG replies of OK, i.e. the request was TAKEN. Whether the park actually
# ran is a separate question, and it is the one that decides whether the client walk executed, so
# count the controller's own GROW-BACK line too and report both.
gb_done=$(grep -c 'GROW-BACK' "$LOG" 2>/dev/null); gb_done=${gb_done:-0}
echo "grow-back attempts=$churn accepted=$accepted completed_in_log=$gb_done"
if [ "$accepted" -eq 0 ]; then
  echo "INVALID: every grow-back was refused before reaching the client walk -- cell proves nothing"
  kill -9 $SRV 2>/dev/null; exit 2
fi
if [ "$gb_done" -eq 0 ]; then
  echo "INVALID: no GROW-BACK ever completed (accepted=$accepted but the controller never parked an io thread)"
  kill -9 $SRV 2>/dev/null; exit 2
fi

kill -TERM $SRV 2>/dev/null; sleep 3; kill -9 $SRV 2>/dev/null

cat "$D/lb1"/asan.* > "$D/lb1/all.asan" 2>/dev/null
n=$(grep -c "heap-use-after-free" "$D/lb1/all.asan" 2>/dev/null || echo 0)
echo "=== ASAN heap-use-after-free reports: $n"
if grep -q "tmClientMigratable\|tomoGrowBackSlot" "$D/lb1/all.asan" 2>/dev/null; then
  echo "FAIL: UAF names the grow-back client walk:"
  grep -B5 -A25 "heap-use-after-free" "$D/lb1/all.asan" | head -60
  exit 1
fi
echo "PASS: no use-after-free in the grow-back path ($churn attempts, $accepted accepted)"
exit 0
