#!/usr/bin/env python3
"""Arm-C io_uring discriminator for nested processEventsWhileBlocked()."""

import argparse
import re
import select
import socket
import sys
import time


def encode(*parts):
    out = bytearray(b"*%d\r\n" % len(parts))
    for part in parts:
        if isinstance(part, str):
            part = part.encode()
        elif isinstance(part, int):
            part = str(part).encode()
        out += b"$%d\r\n%s\r\n" % (len(part), part)
    return bytes(out)


class RespError(Exception):
    pass


class Client:
    def __init__(self, port, timeout=5.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = bytearray()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, *parts):
        self.sock.sendall(encode(*parts))

    def _fill(self, count, deadline):
        while len(self.buf) < count:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("RESP body timed out")
            self.sock.settimeout(left)
            data = self.sock.recv(1 << 16)
            if not data:
                raise ConnectionError("server closed the connection")
            self.buf.extend(data)

    def _line(self, deadline):
        while True:
            end = self.buf.find(b"\r\n")
            if end >= 0:
                line = bytes(self.buf[:end])
                del self.buf[: end + 2]
                return line
            self._fill(len(self.buf) + 1, deadline)

    def recv(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        self._fill(1, deadline)
        kind = chr(self.buf[0])
        del self.buf[0]
        if kind == "+":
            return self._line(deadline)
        if kind == "-":
            raise RespError(self._line(deadline).decode(errors="replace"))
        if kind == ":":
            return int(self._line(deadline))
        if kind == "$":
            length = int(self._line(deadline))
            if length == -1:
                return None
            self._fill(length + 2, deadline)
            value = bytes(self.buf[:length])
            if self.buf[length : length + 2] != b"\r\n":
                raise ValueError("bad bulk terminator")
            del self.buf[: length + 2]
            return value
        if kind == "*":
            count = int(self._line(deadline))
            return [self.recv(max(0.001, deadline - time.monotonic()))
                    for _ in range(count)]
        raise ValueError("unsupported RESP type %r" % kind)

    def cmd(self, *parts, timeout=5.0):
        self.send(*parts)
        return self.recv(timeout)

    def readable(self):
        return bool(self.buf) or bool(select.select([self.sock], [], [], 0)[0])


def main_owned_clients(port, needed=3, attempts=512):
    selected = []
    for _ in range(attempts):
        client = Client(port)
        info = client.cmd("CLIENT", "INFO")
        match = re.search(rb"(?:^| )io-thread=(\d+)(?: |$)", info or b"")
        if match and int(match.group(1)) == 0:
            selected.append(client)
            if len(selected) == needed:
                return selected
        else:
            client.close()
    for client in selected:
        client.close()
    raise RuntimeError("could not acquire %d stable io-thread=0 clients in %d attempts" %
                       (needed, attempts))


def info_counter(payload, name):
    match = re.search(rb"(?:^|\r\n)" + re.escape(name.encode()) +
                      rb":([0-9]+)(?:\r\n|$)", payload)
    return int(match.group(1)) if match else -1


def run(port):
    script, probe, killer = main_owned_clients(port)
    try:
        # The loop becomes killable only after lua-time-limit expires.  Its
        # owner is main, so every reply observed before SCRIPT KILL necessarily
        # traversed main's nested processEventsWhileBlocked event loop.
        script.send("EVAL", "while true do end", 0)
        time.sleep(0.15)
        if script.readable():
            raise RuntimeError("infinite script returned before the PEWB probe")

        nested_reply = None
        try:
            nested_reply = probe.cmd("PING", timeout=5.0)
        except RespError as error:
            # BUSY is also a valid nested reply; the proof is that it arrived
            # while the infinite script still owned the outer command frame.
            nested_reply = str(error).encode()
        if not nested_reply:
            raise RuntimeError("nested PING produced an empty reply")

        killed = killer.cmd("SCRIPT", "KILL", timeout=5.0)
        if killed != b"OK":
            raise RuntimeError("SCRIPT KILL returned %r" % (killed,))
        try:
            script.recv(5.0)
            raise RuntimeError("killed script returned a non-error reply")
        except RespError as error:
            if "kill" not in str(error).lower():
                raise RuntimeError("unexpected killed-script error: %s" % error)

        if probe.cmd("PING", timeout=5.0) != b"PONG":
            raise RuntimeError("post-PEWB PING failed")

        stats = killer.cmd("INFO", "STATS", timeout=5.0)
        multishot = info_counter(stats, "tomokv_uring_multishot_cqes")
        nocopy = info_counter(stats, "tomokv_uring_send_nocopy")
        if multishot <= 0:
            raise RuntimeError("multishot receive never engaged (counter=%d)" % multishot)
        if nocopy <= 0:
            raise RuntimeError("guarded direct send never engaged (counter=%d)" % nocopy)
        return "nested=%r multishot_cqes=%d send_nocopy=%d" % (
            nested_reply[:80], multishot, nocopy)
    finally:
        script.close()
        probe.close()
        killer.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    try:
        detail = run(args.port)
    except Exception as error:
        print("FAIL\t%s: %s" % (type(error).__name__, error))
        return 1
    print("PASS\t" + detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
