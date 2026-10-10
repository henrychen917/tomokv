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
  phase 2  pause the writer with the existing AOF-REWRITE-PAUSE after-manifest hook; queue a
           complete group, then LargeBegin on its last producer. The pause's status file witnesses
           both before release. The large record exceeds even the 256-frame drain-all budget,
           so the next pass MUST see a ready GCMT while the physical stream is still held.
           aof_control_frames_deferred > 0 remains mandatory.
  phase 3  a frame-level walk of the produced file: it must contain large records AND control
           frames (otherwise the walk is vacuous) and zero interleaves.
"""

import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aof_frames  # noqa: E402  (in-tree frame reader, reused so there is one walker)
import _lib  # noqa: E402

# 273 frames including the record header: larger than either ordinary (16) or idle-sweep (256)
# writer budget. Only LargeBegin needs to be queued at release; the producer can fill its 64-slot
# channel and block until the writer resumes. No timing delay stands in for that observation.
LARGE_BYTES = 272 * 64 * 1024
DEADLINE_S = 60.0
EXPECTED_ENGINE = "epoll"

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
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=DEADLINE_S)
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

    def close(self):
        self.stream.close()
        self.sock.close()


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
    for name, value in (("appendfsync", "no"), ("net-io", EXPECTED_ENGINE),
                        ("auto-aof-rewrite-percentage", "0"), ("aof-timestamp-enabled", "no"),
                        ("key-lb", "0"), ("client-lb", "0"), ("flip-auto", "0")):
        if client.cmd("CONFIG", "GET", name) != [name.encode(), value.encode()]:
            raise AssertionError("aof_frame_order needs --%s %s" % (name, value))
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


def wait_for(probe, accept, label, deadline):
    last = None
    while time.monotonic() < deadline:
        last = probe()
        if accept(last):
            return last
        time.sleep(0.002)
    raise AssertionError("%s was not witnessed within the bound (last=%r)" % (label, last))


def frame_state(directory):
    path = Path(directory) / "debug-aof-frame-state"
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None  # the armed writer has not published its first observation yet
    fields = text.split()
    if len(fields) != 3 or any(not field.isascii() or not field.isdigit() for field in fields):
        raise AssertionError("invalid debug-aof-frame-state: %r" % text)
    state = [int(field) for field in fields]
    return state  # writer thread, pending chunks, posted sequence (independent observations)


def usable_connection(host, port, blocked_tids):
    deadline = time.monotonic() + DEADLINE_S
    while time.monotonic() < deadline:
        client = Resp(host, port)
        try:
            if client.cmd("DEBUG", "IO-THREAD") not in blocked_tids:
                return client
        except Exception:
            client.close()
            raise
        client.close()
    raise AssertionError("no connection outside blocked threads %r" % sorted(blocked_tids))


def ordered_pair(client, keys, writer_tid):
    routes = _lib.shards_of(client, keys)
    choices = sorted((owner, sid, key) for key, (sid, owner) in zip(keys, routes)
                     if owner != writer_tid)
    if not choices or choices[0][0] == choices[-1][0]:
        raise AssertionError("framing schedule needs two shard owners outside the AOF writer")
    # The writer scans producer channels in ascending thread-id order. All fragments and the
    # commit are already queued; the large record follows the final fragment on the last owner.
    return [choices[0][2], choices[-1][2]]


def marker_stage(marker):
    try:
        return marker.read_text()
    except FileNotFoundError:
        return None


def release_pause(control, marker):
    failed = sys.exc_info()[0] is not None
    errors = []
    try:
        marker.unlink(missing_ok=True)
    except Exception as error:
        errors.append(error)
    try:
        if control.cmd("DEBUG", "AOF-REWRITE-PAUSE", "off") != b"OK":
            raise AssertionError("could not release AOF rewrite pause")
    except Exception as error:
        errors.append(error)
    if errors:
        if not failed:
            raise errors[0]
        for error in errors:
            print("AOF rewrite pause cleanup failed: %s" % error, file=sys.stderr)


def directed_window(control, writer, keys, aof_dir, writer_tid):
    marker = Path(aof_dir) / "debug-aof-rewrite-stage"
    if marker.exists() or (Path(aof_dir) / "debug-aof-frame-state").exists():
        raise AssertionError("stale AOF rewrite marker before arming")
    start = info(control)
    deadline = time.monotonic() + DEADLINE_S
    began = time.monotonic()
    sent = False
    try:
        if control.cmd("DEBUG", "AOF-REWRITE-PAUSE", "after-manifest") != b"OK":
            raise AssertionError("could not arm AOF rewrite pause")
        if control.cmd("BGREWRITEAOF") != b"Background append only file rewriting started":
            raise AssertionError("could not schedule AOF rewrite pause")
        wait_for(lambda: marker_stage(marker), lambda stage: stage == "after-manifest\n",
                 "writer pause after manifest", deadline)
        state = wait_for(lambda: frame_state(aof_dir), lambda now: now is not None,
                         "paused writer queue observation", deadline)
        if state[0] != writer_tid or state[1] != 0:
            raise AssertionError("paused writer did not drain the old increment: %r" % state)
        if control.cmd(*group_args(keys, 0, "directed-window")) != 2:
            raise AssertionError("directed group did not return 2")
        wait_for(lambda: frame_state(aof_dir),
                 lambda now: now is not None and now[1] == 3 and now[2] == state[2] + 3,
                 "two group fragments and GCMT queued", deadline)
        # Same shard as the last group fragment: AofProducer preserves its record order. A
        # separate connection leaves the control connection usable while SET fills the channel.
        writer.send("SET", keys[1], b"L" * LARGE_BYTES)
        sent = True
        queued = wait_for(lambda: frame_state(aof_dir),
                          lambda now: now is not None and now[1] >= 4 and now[2] >= state[2] + 4,
                          "LargeBegin queued behind the complete group", deadline)
        if marker_stage(marker) != "after-manifest\n":
            raise AssertionError("writer pause ended before LargeBegin was witnessed")
    finally:
        # File release also works if the producer is blocked on a full channel. Clear the arm
        # on every failure, including failure to reach the marker; no retry can hide bad data.
        release_pause(control, marker)
    if not sent or writer.read() != b"OK":
        raise AssertionError("large SET did not complete after releasing the writer")
    stats = wait_for(lambda: info(control),
                     lambda now: now["aof_rewrites"] > start["aof_rewrites"]
                     and now["aof_groups_committed"] > start["aof_groups_committed"],
                     "rewrite and queued group completion", deadline)
    fired = stats["aof_control_frames_deferred"] - start["aof_control_frames_deferred"]
    if fired <= 0:
        raise AssertionError("ready GCMT was never held out of the open large record; "
                             "queued=%r, deferrals=%d" % (queued, fired))
    if (control.cmd("GET", keys[0]) != b"directed-window-l" or
            control.cmd("STRLEN", keys[1]) != LARGE_BYTES):
        raise AssertionError("queued writes did not survive the directed window")
    return fired, stats["aof_groups_committed"] - start["aof_groups_committed"], time.monotonic() - began


def main(host, port, aof_dir):
    connections = []
    try:
        bootstrap = Resp(host, port)
        connections.append(bootstrap)
        assert_surface(bootstrap)
        topo = _lib.topology(bootstrap)
        serving = [tid for tid, role in topo.roles.items() if role in ("io", "fused")]
        if len(serving) < 2:
            raise AssertionError("framing schedule needs a control thread outside the writer")
        # Server::init binds the last serving thread as AOF writer. The armed status file below
        # must confirm that identity before any group/large record is queued.
        writer_tid = max(serving)
        keys = one_key_per_shard(bootstrap, "frameorder:group")
        pair = ordered_pair(bootstrap, keys, writer_tid)
        large_owner = _lib.shards_of(bootstrap, pair)[1][1]
        # In fused mode the large record's producer also serves connections. Its channel can
        # fill while the writer is paused, so keep the observer off BOTH blocked threads.
        control = usable_connection(host, port, {writer_tid, large_owner})
        connections.append(control)
        writer = usable_connection(host, port, {writer_tid})
        connections.append(writer)
        run(control, writer, writer_tid, pair, aof_dir)
    finally:
        for client in reversed(connections):
            client.close()


def run(control, writer, writer_tid, pair, aof_dir):
    assert_surface(control)

    # ---- phase 1: negative control. Groups, no large records, counter must stay at zero. -----
    base = info(control)
    for round_index in range(40):
        if control.cmd(*group_args(pair, round_index, "control-%d" % round_index)) != 2:
            raise AssertionError("negative-control group did not return 2")
    wait_for(lambda: info(control),
             lambda now: now["aof_groups_committed"] == base["aof_groups_committed"] + 40,
             "all negative-control groups committed", time.monotonic() + DEADLINE_S)
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

    # ---- phase 2: force the interleave opportunity, with all group fragments already queued. --
    fired, groups_window, elapsed = directed_window(control, writer, pair, aof_dir, writer_tid)

    # ---- phase 3: frame-level walk of every increment in the directory. ---------------------
    segments = sorted(name for name in os.listdir(aof_dir) if name.endswith(".incr.tomo"))
    if not segments:
        raise AssertionError("no AOF increments under %s" % aof_dir)
    total_frames = total_large = total_control = total_bytes = 0
    failures = []
    for name in segments:
        frames, size, truncated = aof_frames.read_frames(os.path.join(aof_dir, name))
        if truncated:
            raise AssertionError("truncated frame in drained increment %s" % name)
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
        raise AssertionError("%d frame-order violations under %s" % (len(failures), aof_dir))

    print("AOF FRAME ORDER PASS: negative-control groups=%d deferrals=0; window seconds=%.3f "
          "groups=%d deferrals=%d; segments=%d bytes=%d frames=%d large_records=%d "
          "control_frames=%d interleaves=0" % (
              groups_control, elapsed, groups_window, fired, len(segments), total_bytes,
              total_frames, total_large, total_control))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("aof_dir")
    parser.add_argument("--engine", choices=("epoll", "uring"), default="epoll")
    args = parser.parse_args()
    EXPECTED_ENGINE = args.engine
    main(args.host, args.port, args.aof_dir)
