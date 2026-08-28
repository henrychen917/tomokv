#!/usr/bin/env python3
"""Directed AOF physical-framing gate: a control frame must never land inside a large record.

  tests/aof_frame_order.py HOST PORT /path/to/appendonlydir

The AOF writer holds a per-producer lock on the physical stream for the duration of a large record
(a record too big for one 64 KiB frame, written as LargeBegin .. LargeEnd frames).  Every recovery
path -- the writer's short-write rollback, its shutdown ftruncate, and the loader's rewind -- drops
the file from the large record's first byte onward, so a GCMT control frame written inside that
byte range would be dropped with it even though the group it commits was already acknowledged.
The loader refuses to start on such a file ("AOF control record interleaves a large record").

This battery drives the window deliberately and proves BOTH halves:
  phase 1  negative control -- cross-shard groups with no large record in flight.  The deferral
           counter must stay at zero, so a non-zero reading in phase 2 means something.
  phase 2  a large-value writer and a cross-shard group writer running against each other until
           the writer reports it held a ready GCMT back because a large record was open
           (aof_control_frames_deferred > 0).  That counter firing is the proof that the interleave
           window was entered, not merely that nothing broke.
  phase 3  a frame-level walk of the produced file: it must contain large records AND control
           frames (otherwise the walk is vacuous) and zero interleaves.
"""

import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aof_frames  # noqa: E402  (in-tree frame reader, reused so there is one walker)

if len(sys.argv) != 4:
    raise SystemExit("usage: tests/aof_frame_order.py HOST PORT AOF_DIR")
HOST, PORT, AOF_DIR = sys.argv[1], int(sys.argv[2]), sys.argv[3]

# 70000 bytes is two frames at the 64 KiB staging chunk -- the same shape the gate's own AOF
# battery produces (s:large) and the shape the defect was first caught on. A SHORT lock taken very
# often is what opens the window: the group whose GCMT gets held must have had its fragments
# written just before the lock started, and a long lock instead starves those fragments.
# The sizes are cycled rather than fixed: how long the lock outlives a writer pass depends on how
# many frames a record spans against how fast the producer posts them, and a single size only
# enters the window in some thread geometries.
LARGE_SIZES = (70000, 120000, 260000, 520000)
LARGE_PER_ROUND = 128             # split over LARGE_CONNS writers
LARGE_CONNS = 8                   # several producers holding the stream lock at once
GROUPS_PER_ROUND = 128
ROUNDS = 200
DEADLINE_S = 90.0
MAX_AOF_BYTES = 512 * 1024 * 1024  # bound the file this battery is allowed to write

# A cross-owner script write is the group source: it produces a GCMT under --atomic 0 as well as
# --atomic 1, where a cross-shard MSET produces one only under --atomic 1.
GROUP_SCRIPT = "redis.call('SET', KEYS[1], ARGV[1]); redis.call('SET', KEYS[2], ARGV[2]); return 2"


def wire(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return bytes(out)


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=60)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.stream = self.sock.makefile("rb")

    def send(self, *args):
        self.sock.sendall(wire(*args))

    def read(self):
        line = self.stream.readline()
        if not line:
            raise EOFError("server closed the connection")
        kind = line[:1]
        if kind == b"+":
            return line[1:-2]
        if kind == b"-":
            raise RuntimeError(line[1:-2].decode(errors="replace"))
        if kind == b":":
            return int(line[1:-2])
        if kind == b"$":
            size = int(line[1:-2])
            if size == -1:
                return None
            value = self.stream.read(size)
            if self.stream.read(2) != b"\r\n":
                raise AssertionError("bad bulk trailer")
            return value
        if kind == b"*":
            count = int(line[1:-2])
            return None if count == -1 else [self.read() for _ in range(count)]
        raise AssertionError("invalid RESP reply %r" % line[:40])

    def cmd(self, *args):
        self.send(*args)
        return self.read()


def info(client):
    body = client.cmd("INFO", "Persistence").decode()
    values = {}
    for line in body.splitlines():
        if ":" in line and line.startswith("aof_"):
            key, value = line.split(":", 1)
            value = value.strip()
            if value.isdigit():
                values[key] = int(value)
    return values


def assert_surface(client):
    if client.cmd("CONFIG", "GET", "appendonly") != [b"appendonly", b"yes"]:
        raise AssertionError("aof_frame_order needs a purpose boot with appendonly yes")
    if client.cmd("CONFIG", "GET", "enable-debug-command") not in (
            [b"enable-debug-command", b"yes"], [b"enable-debug-command", b"local"]):
        raise AssertionError("aof_frame_order needs DEBUG SHARD to place keys")
    stats = info(client)
    if "aof_control_frames_deferred" not in stats:
        raise AssertionError(
            "INFO Persistence has no aof_control_frames_deferred counter: this server cannot "
            "report whether it holds control frames out of an open large record")


def one_key_per_shard(client, prefix, probes=1024):
    """A key on EVERY shard the server routes to. The window needs a group fragment and a large
    record to reach the SAME producer channel; producers are per ex thread while keys are placed
    per shard, so covering every shard is what guarantees the two roles share threads. The shard
    set is discovered by probing rather than read from a config surface."""
    placed = {}
    for candidate in range(probes):
        key = "%s:%d" % (prefix, candidate)
        shard = client.cmd("DEBUG", "SHARD", key)
        if not isinstance(shard, int):
            raise AssertionError("DEBUG SHARD failed for %s" % key)
        placed.setdefault(shard, key)
    if len(placed) < 2:
        raise AssertionError("only %d shard(s) reachable: no cross-owner group is possible"
                             % len(placed))
    return [placed[shard] for shard in sorted(placed)]


def group_args(keys, index, tag):
    left = keys[index % len(keys)]
    right = keys[(index * 7 + 3) % len(keys)]
    if left == right:
        right = keys[(index + 1) % len(keys)]
    return ["EVAL", GROUP_SCRIPT, "2", left, right, "%s-l" % tag, "%s-r" % tag]


def main():
    control = Resp()
    assert_surface(control)
    keys = one_key_per_shard(control, "frameorder:group")
    shards = len(keys)

    # ---- phase 1: negative control. Groups, no large records, counter must stay at zero. -----
    base = info(control)
    for round_index in range(40):
        control.cmd(*group_args(keys, round_index, "control-%d" % round_index))
    time.sleep(0.5)
    after = info(control)
    if after["aof_groups_committed"] <= base["aof_groups_committed"]:
        raise AssertionError(
            "negative control wrote no atomic groups (committed %d -> %d): the workload cannot "
            "produce a control frame, so the rest of this battery would be vacuous" % (
                base["aof_groups_committed"], after["aof_groups_committed"]))
    if after["aof_control_frames_deferred"] != base["aof_control_frames_deferred"]:
        raise AssertionError(
            "deferral counter moved with no large record in flight (%d -> %d): it is not "
            "measuring the interleave window" % (base["aof_control_frames_deferred"],
                                                 after["aof_control_frames_deferred"]))
    groups_control = after["aof_groups_committed"] - base["aof_groups_committed"]

    # ---- phase 2: drive large records and groups against each other. ------------------------
    writers = [Resp() for _ in range(LARGE_CONNS)]
    large_keys = one_key_per_shard(control, "frameorder:large")
    payloads = [b"L" * size for size in LARGE_SIZES]
    start = info(control)
    began = time.monotonic()
    fired = 0
    rounds_run = 0
    for round_index in range(ROUNDS):
        rounds_run = round_index + 1
        # Pipelined, not ping-pong. The window needs the writer to run BEHIND the producers: a
        # request-response cadence lets it catch up between rounds and the window never opens.
        # The large records go out first so their frames are on the stream while the groups commit.
        for slot in range(LARGE_PER_ROUND):
            writers[slot % LARGE_CONNS].send(
                "SET", large_keys[(round_index + slot) % len(large_keys)],
                payloads[(round_index + slot) % len(payloads)])
        for slot in range(GROUPS_PER_ROUND):
            control.send(*group_args(keys, round_index * GROUPS_PER_ROUND + slot,
                                     "window-%d-%d" % (round_index, slot)))
        for slot in range(LARGE_PER_ROUND):
            writers[slot % LARGE_CONNS].read()
        for _ in range(GROUPS_PER_ROUND):
            control.read()
        probe = info(control)
        fired = probe["aof_control_frames_deferred"]
        if fired > start["aof_control_frames_deferred"]:
            break
        if time.monotonic() - began > DEADLINE_S:
            break
        if probe.get("aof_current_size", 0) > MAX_AOF_BYTES:
            break
    stats = info(control)
    fired = stats["aof_control_frames_deferred"] - start["aof_control_frames_deferred"]
    groups_window = stats["aof_groups_committed"] - start["aof_groups_committed"]
    if fired <= 0:
        raise AssertionError(
            "the writer never reported holding a ready GCMT out of an open large record after "
            "%d rounds (%d groups committed, %d AOF bytes, %.1fs): the interleave window was not "
            "entered, so a clean frame walk would prove nothing" % (
                rounds_run, groups_window, stats.get("aof_current_size", 0),
                time.monotonic() - began))

    # ---- phase 3: frame-level walk of every increment in the directory. ---------------------
    time.sleep(0.5)
    segments = sorted(name for name in os.listdir(AOF_DIR) if name.endswith(".incr.tomo"))
    if not segments:
        raise AssertionError("no AOF increments under %s" % AOF_DIR)
    total_frames = total_large = total_control = total_bytes = 0
    failures = []
    for name in segments:
        frames, size, _truncated = aof_frames.read_frames(os.path.join(AOF_DIR, name))
        violations = aof_frames.walk(frames)
        total_frames += len(frames)
        total_bytes += size
        total_large += sum(1 for f in frames if f.flags & aof_frames.LARGE_BEGIN)
        total_control += sum(1 for f in frames if f.control)
        for kind, frame, open_frame in violations:
            failures.append(name)
            print("VIOLATION %s in %s at frame #%d offset %d (%s seq=%d flags=%s)" % (
                kind, name, frame.index, frame.offset, frame.stream, frame.sequence,
                frame.flag_text()))
            if open_frame is not None:
                print("   open large record: frame #%d offset %d %s seq=%d" % (
                    open_frame.index, open_frame.offset, open_frame.stream, open_frame.sequence))
    if total_large == 0 or total_control == 0:
        raise AssertionError(
            "increments hold %d large records and %d control frames: nothing for the invariant "
            "to be violated by" % (total_large, total_control))
    if failures:
        raise AssertionError("%d frame-order violations under %s" % (len(failures), AOF_DIR))

    print("AOF FRAME ORDER PASS: negative-control groups=%d deferrals=0; window rounds=%d "
          "groups=%d deferrals=%d; segments=%d bytes=%d frames=%d large_records=%d "
          "control_frames=%d interleaves=0" % (
              groups_control, rounds_run, groups_window, fired, len(segments), total_bytes,
              total_frames, total_large, total_control))


main()
