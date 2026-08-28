#!/usr/bin/env python3
"""Frame-level reader for the TomoKV AOF physical stream.

Usage:
  tests/aof_frames.py dump  FILE [--around OFFSET] [--context N]
  tests/aof_frames.py check FILE

`dump` prints one line per physical frame: byte offset, logical stream (shard id or CTRL for the
physical control stream), the shard frame sequence, the large-record flags, and the payload size.
Control frames additionally print the GCMT ticket and the (sid, sequence) fragments it names.

`check` re-implements the loader's frame walk (src/persist/aof.cc aof_read_plan) and prints every
place the physical stream breaks a loader invariant.  It exits 1 when it finds one and 0 when the
file is clean, so it is usable both as a detector and as its own negative control: a file the
server loads must produce "interleaved_control=0".

Exit codes: 0 clean, 1 invariant violated, 2 usage/format error.
"""

import signal
import sys

# `tests/aof_frames.py dump ... | head` is the normal way to read a long dump; let the shell close
# the pipe instead of turning it into a traceback.
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

FILE_MAGIC = b"TOMOAOF\0"
FILE_HEADER_BYTES = 80
FRAME_HEADER_BYTES = 40
FRAME_TAG = 0x4D524641  # "AFRM"
RECORD_HEADER_BYTES = 40
RECORD_TAG = 0x43524F41  # "AORC"
CONTROL_SID = 0xFFFFFFFF
LARGE_BEGIN = 1 << 0
LARGE_END = 1 << 1
KIND_NAMES = {1: "PUT", 2: "DEL", 3: "FLUSH", 4: "TS", 5: "GPUT", 6: "GDEL", 7: "GCMT"}


def u32(data, pos):
    return int.from_bytes(data[pos:pos + 4], "little")


def u64(data, pos):
    return int.from_bytes(data[pos:pos + 8], "little")


class Frame:
    __slots__ = ("index", "offset", "sid", "sequence", "flags", "length", "payload")

    def __init__(self, index, offset, sid, sequence, flags, length, payload):
        self.index = index
        self.offset = offset
        self.sid = sid
        self.sequence = sequence
        self.flags = flags
        self.length = length
        self.payload = payload

    @property
    def control(self):
        return self.sid == CONTROL_SID

    @property
    def stream(self):
        return "CTRL" if self.control else "sid%-3d" % self.sid

    def flag_text(self):
        text = ""
        text += "B" if self.flags & LARGE_BEGIN else "-"
        text += "E" if self.flags & LARGE_END else "-"
        extra = self.flags & ~(LARGE_BEGIN | LARGE_END)
        return text + ("+%#x" % extra if extra else "")

    def records(self):
        """Decode the record headers inside this frame's payload; best effort."""
        out = []
        pos = 0
        while pos + RECORD_HEADER_BYTES <= len(self.payload):
            if u32(self.payload, pos) != RECORD_TAG:
                break
            kind = self.payload[pos + 4]
            key_len = u32(self.payload, pos + 8)
            payload_len = u64(self.payload, pos + 16)
            ticket = u64(self.payload, pos + 32)
            key = self.payload[pos + RECORD_HEADER_BYTES:pos + RECORD_HEADER_BYTES + key_len]
            out.append((kind, key, payload_len, ticket, pos))
            step = RECORD_HEADER_BYTES + key_len + payload_len
            if step <= 0 or pos + step > len(self.payload):
                break
            pos += step
        return out

    def summary(self):
        if self.control:
            parts = []
            for kind, _key, payload_len, ticket, pos in self.records():
                names = []
                base = pos + RECORD_HEADER_BYTES
                count = u32(self.payload, base) if payload_len >= 4 else 0
                for index in range(count):
                    dep = base + 4 + index * 8
                    names.append("(sid%d,seq%d)" % (u32(self.payload, dep),
                                                    u32(self.payload, dep + 4)))
                parts.append("%s ticket=%d names=%s" % (
                    KIND_NAMES.get(kind, "?%d" % kind), ticket, ",".join(names) or "-"))
            return "; ".join(parts) or "(no decodable record)"
        pieces = []
        for kind, key, payload_len, ticket, _pos in self.records()[:3]:
            pieces.append("%s key=%s len=%d%s" % (
                KIND_NAMES.get(kind, "?%d" % kind),
                key[:28].decode("latin1").replace("\n", "."), payload_len,
                " ticket=%d" % ticket if ticket else ""))
        if not pieces:
            return "(large-record continuation bytes)"
        return "; ".join(pieces)


def read_frames(path):
    with open(path, "rb") as stream:
        data = stream.read()
    if len(data) < FILE_HEADER_BYTES or data[:8] != FILE_MAGIC:
        raise SystemExit("not a TomoKV AOF: %s" % path)
    frames = []
    pos = FILE_HEADER_BYTES
    index = 0
    truncated = None
    while pos < len(data):
        if len(data) - pos < FRAME_HEADER_BYTES:
            truncated = pos
            break
        if u32(data, pos) != FRAME_TAG:
            raise SystemExit("bad frame tag at offset %d" % pos)
        offset = pos
        sid = u32(data, pos + 4)
        sequence = u32(data, pos + 8)
        flags = u32(data, pos + 12)
        length = u32(data, pos + 16)
        pos += FRAME_HEADER_BYTES
        if len(data) - pos < length:
            truncated = offset
            break
        frames.append(Frame(index, offset, sid, sequence, flags, length,
                            data[pos:pos + length]))
        index += 1
        pos += length
    return frames, len(data), truncated


def walk(frames):
    """The loader's frame walk. Returns the list of invariant violations."""
    violations = []
    active_large = False
    large_sid = None
    large_frame = None
    for frame in frames:
        if frame.control and active_large:
            violations.append(("interleaved_control", frame, large_frame))
            continue
        if not active_large:
            if frame.flags & LARGE_END:
                violations.append(("end_without_begin", frame, None))
            if frame.flags & LARGE_BEGIN:
                if frame.control:
                    violations.append(("control_is_large", frame, None))
                    continue
                active_large = True
                large_sid = frame.sid
                large_frame = frame
        elif frame.sid != large_sid or (frame.flags & LARGE_BEGIN):
            violations.append(("interleaved_large", frame, large_frame))
        if active_large and (frame.flags & LARGE_END):
            active_large = False
            large_sid = None
            large_frame = None
    return violations


def line(frame):
    return "#%-5d @%-10d %-7s seq=%-6d flags=%-4s len=%-7d %s" % (
        frame.index, frame.offset, frame.stream, frame.sequence, frame.flag_text(),
        frame.length, frame.summary())


def main(argv):
    if len(argv) < 3 or argv[1] not in ("dump", "check"):
        raise SystemExit(__doc__)
    mode, path = argv[1], argv[2]
    frames, size, truncated = read_frames(path)
    violations = walk(frames)

    if mode == "dump":
        around = None
        context = 6
        if "--around" in argv:
            around = int(argv[argv.index("--around") + 1])
        if "--context" in argv:
            context = int(argv[argv.index("--context") + 1])
        selected = frames
        if around is not None:
            center = 0
            for frame in frames:
                if frame.offset <= around:
                    center = frame.index
            low = max(0, center - context)
            selected = frames[low:center + context + 1]
        print("file=%s bytes=%d frames=%d%s" % (
            path, size, len(frames),
            " TORN-TAIL-AT=%d" % truncated if truncated is not None else ""))
        for frame in selected:
            print(line(frame))

    # large_records/control_frames are printed on every line, clean or not: "0 interleaves" in a
    # file with no large record or no control frame proves nothing.
    print("frames=%d large_records=%d control_frames=%d interleaved_control=%d "
          "other_violations=%d" % (
              len(frames),
              sum(1 for f in frames if f.flags & LARGE_BEGIN),
              sum(1 for f in frames if f.control),
              sum(1 for kind, _f, _l in violations if kind == "interleaved_control"),
              sum(1 for kind, _f, _l in violations if kind != "interleaved_control")))
    for kind, frame, open_frame in violations:
        print("VIOLATION %s at frame #%d offset %d (%s seq=%d flags=%s)" % (
            kind, frame.index, frame.offset, frame.stream, frame.sequence, frame.flag_text()))
        if open_frame is not None:
            print("          open large record began at frame #%d offset %d (%s seq=%d): %s" % (
                open_frame.index, open_frame.offset, open_frame.stream, open_frame.sequence,
                open_frame.summary()))
        print("          %s" % frame.summary())
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
