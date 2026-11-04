#!/usr/bin/env python3
"""XACCT regression battery. Usage: tests/xacct.py HOST PORT [--release-build]

The server must be purpose-booted with --enable-debug-command yes (or local):
DEBUG RELOAD is the cold full-recomputation oracle for stream-group accounting.
"""

import socket
import statistics
import sys
import time


RELEASE_BUILD = "--release-build" in sys.argv[1:]
ARGS = [arg for arg in sys.argv[1:] if arg != "--release-build"]
HOST, PORT = ARGS[0], int(ARGS[1])
FAIL = 0


def note(label, ok, detail=""):
    global FAIL
    print(("  ok   " if ok else "  FAIL ") + label +
          ((" " + detail) if detail else ""), flush=True)
    FAIL += not ok


def growth(label, small, large, bound):
    if not RELEASE_BUILD:
        print("  NOT RUN " + label + " -- requires --release-build; correctness checks remain active",
              flush=True)
        return
    ratio = large / small
    note(label, ratio < bound, "small=%.3fus large=%.3fus ratio=%.2fx bound<%.2fx" %
         (small, large, ratio, bound))


def frame(*args):
    values = [arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]
    return (b"*%d\r\n" % len(values) +
            b"".join(b"$%d\r\n" % len(value) + value + b"\r\n"
                     for value in values))


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=120)
        self.sock.settimeout(120)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        kind, value = line[:1], line[1:-2]
        if kind == b"+": return value
        if kind == b"-": raise RuntimeError(value.decode(errors="replace"))
        if kind == b":": return int(value)
        if kind == b"$":
            size = int(value)
            if size == -1: return None
            payload = self.file.read(size)
            if self.file.read(2) != b"\r\n": raise ValueError("bad bulk trailer")
            return payload
        if kind == b"*":
            count = int(value)
            return None if count == -1 else [self.read() for _ in range(count)]
        raise ValueError("unsupported RESP prefix %r" % kind)

    def cmd(self, *args):
        self.sock.sendall(frame(*args))
        return self.read()

    def pipeline(self, commands):
        self.sock.sendall(b"".join(frame(*command) for command in commands))
        return [self.read() for _ in commands]


def chunks(client, commands, width=2000):
    for start in range(0, len(commands), width):
        replies = client.pipeline(commands[start:start + width])
        if len(replies) != min(width, len(commands) - start):
            raise AssertionError("short pipeline")


admin = Resp()
invalidator = Resp()


def prepare_pel(depth):
    admin.cmd("FLUSHDB")
    count = max(depth, 1)
    chunks(admin, [("XADD", "xacct:pel", "%d-0" % (index + 1), "f", "v")
                   for index in range(count)])
    admin.cmd("XGROUP", "CREATE", "xacct:pel", "g", "0" if depth else "$")
    if depth:
        delivered = admin.cmd("XREADGROUP", "GROUP", "g", "c", "COUNT", depth,
                              "STREAMS", "xacct:pel", ">")
        if len(delivered) != 1 or len(delivered[0][1]) != depth:
            raise AssertionError("PEL setup did not deliver %d entries" % depth)
    pending = admin.cmd("XPENDING", "xacct:pel", "g")[0]
    if pending != depth:
        raise AssertionError("PEL depth %r, wanted %d" % (pending, depth))
    return count + 1, pending


def xadd_latency(depth):
    next_id, pending = prepare_pel(depth)
    ops = 2000
    samples = []
    for _ in range(5):
        commands = [("XADD", "xacct:pel", "%d-0" % ident, "f", "bench")
                    for ident in range(next_id, next_id + ops)]
        next_id += ops
        started = time.perf_counter_ns() if RELEASE_BUILD else None
        replies = admin.pipeline(commands)
        elapsed = time.perf_counter_ns() - started if RELEASE_BUILD else None
        if len(replies) != ops or not all(isinstance(reply, bytes) for reply in replies):
            raise AssertionError("bad XADD reply")
        if RELEASE_BUILD:
            samples.append(elapsed / ops / 1000.0)
    return statistics.median(samples) if samples else None, pending


shallow_us, shallow_pending = xadd_latency(0)
deep_us, deep_pending = xadd_latency(10000)
note("stream detector negative control has PEL=0", shallow_pending == 0)
note("stream detector fired with PEL=10000", deep_pending == 10000)
growth("XADD cost growth is bounded across a 10k PEL", shallow_us, deep_us, 4.0)


def queue_sets(count, repeat):
    for base in range(0, count, 2000):
        commands = [("SET", "xacct:tx:%d:%d" % (repeat, index), "v")
                    for index in range(base, min(count, base + 2000))]
        replies = admin.pipeline(commands)
        if not all(reply == b"QUEUED" for reply in replies):
            raise AssertionError("SET did not queue")


# Negative control: without invalidation, WATCH must not abort and the write must execute.
admin.cmd("FLUSHDB")
admin.cmd("WATCH", "xacct:watch-control")
admin.cmd("MULTI")
admin.cmd("SET", "xacct:watch-control-result", "ran")
clean_exec = admin.cmd("EXEC")
note("WATCH abort detector negative control reports no abort",
     clean_exec == [b"OK"] and admin.cmd("GET", "xacct:watch-control-result") == b"ran")


def aborted_exec_latency(count):
    samples = []
    fired = 0
    for repeat in range(5):
        admin.cmd("FLUSHDB")
        admin.cmd("WATCH", "xacct:watched")
        invalidator.cmd("SET", "xacct:watched", repeat)
        admin.cmd("MULTI")
        queue_sets(count, repeat)
        started = time.perf_counter_ns() if RELEASE_BUILD else None
        reply = admin.cmd("EXEC")
        elapsed = time.perf_counter_ns() - started if RELEASE_BUILD else None
        if reply is None and admin.cmd("DBSIZE") == 1:
            fired += 1
        if RELEASE_BUILD:
            samples.append(elapsed / 1000.0)
    return statistics.median(samples) if samples else None, fired


small_us, small_aborts = aborted_exec_latency(2000)
large_us, large_aborts = aborted_exec_latency(10000)
note("dirty WATCH fired before writes in every measured EXEC",
     small_aborts == 5 and large_aborts == 5,
     "small=%d/5 large=%d/5" % (small_aborts, large_aborts))
growth("MULTI prepare growth is bounded for 5x queued write keys", small_us, large_us, 15.0)

# The hash index is only a membership accelerator: first-occurrence dedup and command order stay
# observable through the child replies and the final value.
admin.cmd("FLUSHDB")
admin.cmd("MULTI")
for value in ("first", "second", "third"):
    if admin.cmd("SET", "xacct:duplicate", value) != b"QUEUED":
        raise AssertionError("duplicate-key SET did not queue")
duplicate_reply = admin.cmd("EXEC")
note("write-key hash dedup preserves transaction order and replies",
     duplicate_reply == [b"OK", b"OK", b"OK"] and
     admin.cmd("GET", "xacct:duplicate") == b"third")


# Build two byte-identical streams. The no-group delta is the zero control. The target then visits
# every group-accounting mutation family, including both reassignment sites. DEBUG RELOAD rebuilds
# bytes_ from decoded maps and checks it against the cold full traversal; subtracting the untouched
# twin removes any stream-node capacity change from the comparison.
debug_mode = admin.cmd("CONFIG", "GET", "enable-debug-command")
note("DEBUG recomputation oracle is armed",
     debug_mode in ([b"enable-debug-command", b"yes"],
                    [b"enable-debug-command", b"local"]), repr(debug_mode))
admin.cmd("FLUSHDB")
target, control = "xacct:account:a", "xacct:account:b"
for ident in range(1, 9):
    for key in (target, control):
        admin.cmd("XADD", key, "%d-0" % ident, "field", "value-%d" % ident)

target_plain = admin.cmd("MEMORY", "USAGE", target)
control_plain = admin.cmd("MEMORY", "USAGE", control)
note("stream-accounting delta control is zero", target_plain - control_plain == 0,
     "delta=%d" % (target_plain - control_plain))

admin.cmd("XGROUP", "CREATE", target, "g", "0")
admin.cmd("XREADGROUP", "GROUP", "g", "a", "COUNT", "8", "STREAMS", target, ">")
claim_consumer = "claim-" + "x" * 80
auto_consumer = "auto-" + "y" * 160
admin.cmd("XCLAIM", target, "g", claim_consumer, "0", "1-0", "2-0")
admin.cmd("XAUTOCLAIM", target, "g", auto_consumer, "0", "3-0", "COUNT", "1", "JUSTID")
admin.cmd("XACK", target, "g", "4-0")
admin.cmd("XDEL", target, "5-0")
admin.cmd("XDEL", control, "5-0")
deleted = admin.cmd("XAUTOCLAIM", target, "g", "delete-scan", "0", "5-0", "COUNT", "1")
admin.cmd("XGROUP", "CREATECONSUMER", target, "g", "temporary-" + "z" * 70)
admin.cmd("XGROUP", "DELCONSUMER", target, "g", "temporary-" + "z" * 70)
admin.cmd("XGROUP", "DELCONSUMER", target, "g", "a")
admin.cmd("XGROUP", "CREATE", target, "ephemeral", "$")
admin.cmd("XGROUP", "DESTROY", target, "ephemeral")
pending_before = admin.cmd("XPENDING", target, "g")[0]
before_delta = admin.cmd("MEMORY", "USAGE", target) - admin.cmd("MEMORY", "USAGE", control)

reload_reply = admin.cmd("DEBUG", "RELOAD")
pending_after = admin.cmd("XPENDING", target, "g")[0]
after_delta = admin.cmd("MEMORY", "USAGE", target) - admin.cmd("MEMORY", "USAGE", control)
deleted_fired = isinstance(deleted, list) and len(deleted) == 3 and deleted[2] == [b"5-0"]
note("pending delete/reassignment accounting paths fired",
     deleted_fired and pending_before == 3 and pending_after == 3,
     "deleted=%r pending=%r/%r" % (deleted, pending_before, pending_after))
note("MEMORY USAGE group bytes equal cold recomputation",
     reload_reply == b"OK" and before_delta > 0 and before_delta == after_delta,
     "before=%d after=%d reload=%r" % (before_delta, after_delta, reload_reply))


admin.file.close()
admin.sock.close()
invalidator.file.close()
invalidator.sock.close()

if FAIL:
    raise SystemExit("%d XACCT checks failed" % FAIL)
print("XACCT directed battery passed", flush=True)
