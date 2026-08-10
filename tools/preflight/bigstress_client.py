#!/usr/bin/env python3
"""Binary-safe RESP2 acceptance client used by tools/preflight/bigstress.sh.

The program deliberately has no redis-py dependency.  Qualification must exercise
the candidate's wire protocol, and a client library which retries, reconnects, or
coerces replies can hide exactly the failures these cases are meant to report.

Out-of-spec results, by subcommand:

* fidelity: any SET/MSET reply other than OK, any missing/wrong GET/MGET byte,
  failure to complete an exact SCAN MATCH of the stable canary namespace, fewer
  than eight concurrent traffic clients, a protocol error, or a socket timeout.
* migration: a wrong/missing canary reply during pipelined traffic or final
  verification, zero completed GETs, a bad local XXH64 mirror, failure to
  publish a requested readiness marker after all eight exact readers run, or
  any selected canary which did not begin on the decision's logged source, or
  (in --verify-only mode) any deterministic canary in the explicit
  --moved-lo/--moved-hi range which does not route away from --moved-src to
  --moved-dst. Full mode proves one canary per ownership bucket; QUICK reports
  its stride-four sampling and never calls that coverage complete.
* lifecycle: any long-lived connection disconnecting or returning a wrong byte,
  zero connect/SET/GET/disconnect churn, failure to get an accepted
  DEBUG TOMO-MODESHIFT 6 request, or no surviving socket reporting a changed
  CLIENT INFO io-thread owner before the bounded run ends.  An accepted request
  alone is not evidence that a live socket completed a handoff.

Success is one compact, key-sorted JSON object on stdout.  Diagnostics go to
stderr and failure exits nonzero.  Every connect, send, and reply read has a
socket timeout; worker joins also have an outer deadline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import socket
import struct
import sys
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


HOST = "127.0.0.1"
NCLIENTS = 8
VALUE_SIZES = (32, 4096, 65536)
TOMO_BUCKETS = 16384
MIGRATION_LO = 2048
MIGRATION_HI = 4096
MIGRATION_QUICK_STRIDE = 4
CONNECT_TIMEOUT = 5.0
QUICK_COMMAND_TIMEOUT = 12.0
FULL_COMMAND_TIMEOUT = 30.0
MAX_RESP_LINE = 64 * 1024
MAX_RESP_BULK = 512 * 1024 * 1024
MAX_RESP_ARRAY = 1_000_000
MAX_RESP_DEPTH = 128


class ConformanceError(RuntimeError):
    """A conformance failure with a concise user-facing message."""


class RespProtocolError(ConformanceError):
    """Malformed, truncated, timed-out, or otherwise unusable RESP."""


class RespServerError(ConformanceError):
    """A syntactically valid RESP error reply."""

    def __init__(self, payload: bytes):
        self.payload = payload
        super().__init__(payload.decode("utf-8", "backslashreplace"))


class RespSimpleString(bytes):
    """A RESP '+' value; kept distinct from a bulk string."""


class RespBulkString(bytes):
    """A non-null RESP '$' value; kept distinct from a simple string."""


_RESP_INT = re.compile(br"-?(?:0|[1-9][0-9]*)\Z")
_CLIENT_ID = re.compile(br"(?:^| )id=([0-9]+)(?= |$)")
_CLIENT_IO_THREAD = re.compile(br"(?:^| )io-thread=([0-9]+)(?= |$)")


def _parse_resp_int(raw: bytes, what: str) -> int:
    if not _RESP_INT.fullmatch(raw):
        raise RespProtocolError(f"invalid RESP {what}: {raw!r}")
    return int(raw)


def _arg_bytes(arg: bytes | bytearray | memoryview | str | int) -> bytes:
    if isinstance(arg, bytes):
        return arg
    if isinstance(arg, (bytearray, memoryview)):
        return bytes(arg)
    if isinstance(arg, str):
        return arg.encode("utf-8")
    if isinstance(arg, int) and not isinstance(arg, bool):
        return str(arg).encode("ascii")
    raise TypeError(f"RESP argument has unsupported type {type(arg).__name__}")


def encode_command(args: Sequence[bytes | bytearray | memoryview | str | int]) -> bytes:
    if not args:
        raise ValueError("cannot encode an empty command")
    out = [b"*", str(len(args)).encode("ascii"), b"\r\n"]
    for arg in args:
        value = _arg_bytes(arg)
        out.extend(
            (
                b"$",
                str(len(value)).encode("ascii"),
                b"\r\n",
                value,
                b"\r\n",
            )
        )
    return b"".join(out)


class RespConnection:
    """A strict, non-reconnecting RESP2 connection."""

    def __init__(self, port: int, timeout: float, label: str):
        self.port = port
        self.timeout = timeout
        self.label = label
        self._buf = bytearray()
        try:
            self._sock = socket.create_connection(
                (HOST, port), timeout=min(timeout, CONNECT_TIMEOUT)
            )
            self._sock.settimeout(timeout)
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, TimeoutError) as exc:
            raise RespProtocolError(
                f"{label}: connect to {HOST}:{port} failed within "
                f"{min(timeout, CONNECT_TIMEOUT):.1f}s: {exc}"
            ) from exc

    def __enter__(self) -> "RespConnection":
        return self

    def __exit__(self, _typ: Any, _value: Any, _tb: Any) -> None:
        self.close()

    def close(self) -> None:
        sock = getattr(self, "_sock", None)
        if sock is not None:
            self._sock = None  # type: ignore[assignment]
            try:
                sock.close()
            except OSError:
                pass

    def _recv(self) -> None:
        try:
            chunk = self._sock.recv(65536)
        except socket.timeout as exc:
            raise RespProtocolError(
                f"{self.label}: reply timeout after {self.timeout:.1f}s"
            ) from exc
        except OSError as exc:
            raise RespProtocolError(f"{self.label}: receive failed: {exc}") from exc
        if not chunk:
            raise RespProtocolError(f"{self.label}: server closed the connection")
        self._buf.extend(chunk)

    def _readline(self) -> bytes:
        while True:
            end = self._buf.find(b"\r\n")
            if end >= 0:
                if end > MAX_RESP_LINE:
                    raise RespProtocolError(
                        f"{self.label}: RESP line exceeds {MAX_RESP_LINE} bytes"
                    )
                first_lf = self._buf.find(b"\n")
                if first_lf != end + 1:
                    raise RespProtocolError(
                        f"{self.label}: RESP line contains a bare LF"
                    )
                line = bytes(self._buf[:end])
                del self._buf[: end + 2]
                return line
            if b"\n" in self._buf:
                raise RespProtocolError(
                    f"{self.label}: RESP line used LF without a preceding CR"
                )
            if len(self._buf) > MAX_RESP_LINE:
                raise RespProtocolError(
                    f"{self.label}: RESP line exceeds {MAX_RESP_LINE} bytes"
                )
            self._recv()

    def _readexact(self, length: int) -> bytes:
        while len(self._buf) < length:
            self._recv()
        value = bytes(self._buf[:length])
        del self._buf[:length]
        return value

    def read_reply(self, depth: int = 0) -> Any:
        if depth > MAX_RESP_DEPTH:
            raise RespProtocolError(
                f"{self.label}: RESP nesting exceeds {MAX_RESP_DEPTH}"
            )
        line = self._readline()
        if not line:
            raise RespProtocolError(f"{self.label}: empty RESP type line")
        kind, payload = line[:1], line[1:]
        if kind == b"+":
            return RespSimpleString(payload)
        if kind == b"-":
            raise RespServerError(payload)
        if kind == b":":
            return _parse_resp_int(payload, "integer")
        if kind == b"$":
            length = _parse_resp_int(payload, "bulk length")
            if length == -1:
                return None
            if length < 0 or length > MAX_RESP_BULK:
                raise RespProtocolError(
                    f"{self.label}: invalid RESP bulk length {length}"
                )
            framed = self._readexact(length + 2)
            if framed[-2:] != b"\r\n":
                raise RespProtocolError(
                    f"{self.label}: bulk payload lacks trailing CRLF"
                )
            return RespBulkString(framed[:-2])
        if kind == b"*":
            length = _parse_resp_int(payload, "array length")
            if length == -1:
                return None
            if length < 0 or length > MAX_RESP_ARRAY:
                raise RespProtocolError(
                    f"{self.label}: invalid RESP array length {length}"
                )
            return [self.read_reply(depth + 1) for _ in range(length)]
        raise RespProtocolError(
            f"{self.label}: unsupported RESP2 type byte {kind!r}"
        )

    def send(self, payload: bytes) -> None:
        try:
            self._sock.sendall(payload)
        except socket.timeout as exc:
            raise RespProtocolError(
                f"{self.label}: send timeout after {self.timeout:.1f}s"
            ) from exc
        except OSError as exc:
            raise RespProtocolError(f"{self.label}: send failed: {exc}") from exc

    def command(self, *args: bytes | bytearray | memoryview | str | int) -> Any:
        self.send(encode_command(args))
        return self.read_reply()

    def pipeline(
        self,
        commands: Sequence[
            Sequence[bytes | bytearray | memoryview | str | int]
        ],
    ) -> list[Any]:
        if not commands:
            return []
        self.send(b"".join(encode_command(command) for command in commands))
        return [self.read_reply() for _ in commands]


def _describe_bytes(value: Any) -> str:
    if value is None:
        return "nil"
    if not isinstance(value, bytes):
        return f"{type(value).__name__}({value!r})"
    digest = hashlib.sha256(value).hexdigest()[:16]
    return (
        f"{type(value).__name__} {len(value)} bytes "
        f"sha256={digest}"
    )


def expect_status(reply: Any, expected: bytes, context: str) -> None:
    if not isinstance(reply, RespSimpleString) or reply != expected:
        raise ConformanceError(
            f"{context}: expected status {expected!r}, got {_describe_bytes(reply)}"
        )


def expect_exact(reply: Any, expected: bytes, context: str) -> None:
    if not isinstance(reply, RespBulkString) or reply != expected:
        raise ConformanceError(
            f"{context}: expected {_describe_bytes(expected)}, "
            f"got {_describe_bytes(reply)}"
        )


def expect_array(reply: Any, length: int, context: str) -> list[Any]:
    if not isinstance(reply, list) or len(reply) != length:
        actual = len(reply) if isinstance(reply, list) else type(reply).__name__
        raise ConformanceError(
            f"{context}: expected array length {length}, got {actual}"
        )
    return reply


def client_identity(
    conn: RespConnection, context: str, owner_max_slot: int
) -> tuple[int, int]:
    """Return the server-side id and current IO owner of this exact socket."""

    reply = conn.command(b"CLIENT", b"INFO")
    if not isinstance(reply, RespBulkString):
        raise ConformanceError(
            f"{context}: CLIENT INFO expected a bulk string, "
            f"got {_describe_bytes(reply)}"
        )
    id_match = _CLIENT_ID.search(reply)
    owner_match = _CLIENT_IO_THREAD.search(reply)
    if id_match is None or owner_match is None:
        raise ConformanceError(
            f"{context}: CLIENT INFO lacks numeric id/io-thread fields"
        )
    client_id = int(id_match.group(1))
    owner = int(owner_match.group(1))
    if client_id <= 0:
        raise ConformanceError(
            f"{context}: CLIENT INFO returned invalid id={client_id}"
        )
    if owner < 0 or owner > owner_max_slot:
        raise ConformanceError(
            f"{context}: CLIENT INFO io-thread={owner} is outside "
            f"the allocated slot range 0..{owner_max_slot}"
        )
    return client_id, owner


def deterministic_value(label: bytes, size: int) -> bytes:
    """Return binary data of exactly size bytes, stable across Python versions."""

    return hashlib.shake_256(b"bigstress-value-v1\0" + label).digest(size)


def canonical_digest(records: Iterable[tuple[bytes, bytes, bytes]]) -> str:
    """Hash sorted, length-framed records without text/binary ambiguity."""

    digest = hashlib.sha256()
    digest.update(b"bigstress-canonical-v1\0")
    for kind, key, value in sorted(records):
        for field in (kind, key, value):
            digest.update(struct.pack(">Q", len(field)))
            digest.update(field)
    return digest.hexdigest()


def emit_json(result: dict[str, Any]) -> None:
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)


def command_timeout(quick: bool) -> float:
    return QUICK_COMMAND_TIMEOUT if quick else FULL_COMMAND_TIMEOUT


def validate_port(port: int) -> None:
    if not (1 <= port <= 65535):
        raise ConformanceError(f"port is out of range: {port}")


def validate_seconds(seconds: float) -> None:
    if not (1.0 <= seconds <= 3600.0):
        raise ConformanceError(
            f"--seconds must be between 1 and 3600 (got {seconds})"
        )


def validate_ready_file(path: str | None) -> str | None:
    if path is None:
        return None
    if not path:
        raise ConformanceError("--ready-file must not be empty")
    absolute = os.path.abspath(path)
    parent = os.path.dirname(absolute)
    if not os.path.isdir(parent):
        raise ConformanceError(
            f"--ready-file parent directory does not exist: {parent}"
        )
    if os.path.lexists(absolute):
        raise ConformanceError(
            f"--ready-file already exists; refusing a stale marker: {absolute}"
        )
    return absolute


def validate_control_file(path: str | None, option: str) -> str | None:
    """Validate a shell-published control path which must not exist at launch."""

    if path is None:
        return None
    if not path:
        raise ConformanceError(f"{option} must not be empty")
    absolute = os.path.abspath(path)
    parent = os.path.dirname(absolute)
    if not os.path.isdir(parent):
        raise ConformanceError(
            f"{option} parent directory does not exist: {parent}"
        )
    if os.path.lexists(absolute):
        raise ConformanceError(
            f"{option} already exists; refusing a stale control file: {absolute}"
        )
    return absolute


def publish_ready_file(path: str) -> None:
    """Atomically publish an empty existence-only readiness marker."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ConformanceError(
            f"could not atomically create --ready-file {path}: {exc}"
        ) from exc
    os.close(descriptor)


class ErrorBox:
    """First-error publication plus a shared cancellation flag."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self._lock = threading.Lock()
        self._errors: list[str] = []

    def fail(self, where: str, exc: BaseException) -> None:
        with self._lock:
            if not self._errors:
                self._errors.append(f"{where}: {type(exc).__name__}: {exc}")
        self.stop.set()

    def check(self) -> None:
        with self._lock:
            if self._errors:
                raise ConformanceError(self._errors[0])


def wait_for(
    predicate: Any,
    deadline: float,
    errors: ErrorBox,
    description: str,
    interval: float = 0.01,
) -> None:
    while not predicate():
        errors.check()
        if time.monotonic() >= deadline:
            raise ConformanceError(f"timeout waiting for {description}")
        errors.stop.wait(interval)


def join_threads(
    threads: Sequence[threading.Thread],
    deadline: float,
    errors: ErrorBox,
    description: str,
) -> None:
    for thread in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            errors.stop.set()
            raise ConformanceError(f"timeout joining {description}")
        thread.join(remaining)
    alive = [thread.name for thread in threads if thread.is_alive()]
    if alive:
        errors.stop.set()
        raise ConformanceError(
            f"timeout joining {description}; alive={','.join(alive)}"
        )
    errors.check()


def read_migration_selection(path: str | None) -> tuple[int, int, int, int] | None:
    """Read the shell's atomically-published ``lo hi src dst`` selection."""

    if path is None or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as stream:
            raw = stream.read(4097)
    except OSError as exc:
        raise ConformanceError(
            f"could not read migration selection file {path}: {exc}"
        ) from exc
    if len(raw) > 4096:
        raise ConformanceError("migration selection file exceeds 4096 bytes")
    match = re.fullmatch(
        rb"[ \t]*([0-9]+)[ \t]+([0-9]+)[ \t]+([0-9]+)[ \t]+([0-9]+)[ \t]*(?:\r?\n)?",
        raw,
    )
    if match is None:
        raise ConformanceError(
            f"migration selection file has invalid contents: {raw[:160]!r}"
        )
    lo, hi, src, dst = (int(value) for value in match.groups())
    if not (0 <= lo < hi <= TOMO_BUCKETS):
        raise ConformanceError(f"migration selection has invalid range [{lo},{hi})")
    if src < 0 or dst < 0 or src == dst:
        raise ConformanceError(
            f"migration selection has invalid workers {src}->{dst}"
        )
    return lo, hi, src, dst


def _watch_stop_file(
    path: str,
    deadline: float,
    stop: threading.Event,
    observed: threading.Event,
) -> None:
    """Turn an atomically-created stop file into a normal worker-stop request."""

    while not stop.is_set() and time.monotonic() < deadline:
        if os.path.exists(path):
            observed.set()
            stop.set()
            return
        stop.wait(0.05)


def delete_keys(conn: RespConnection, keys: Sequence[bytes]) -> None:
    for offset in range(0, len(keys), 128):
        batch = keys[offset : offset + 128]
        reply = conn.command(b"DEL", *batch)
        if not isinstance(reply, int) or not (0 <= reply <= len(batch)):
            raise ConformanceError(
                f"DEL cleanup batch {offset // 128}: invalid reply {reply!r}"
            )


def mset_pairs(
    conn: RespConnection,
    pairs: Sequence[tuple[bytes, bytes]],
    context: str,
) -> None:
    args: list[bytes] = [b"MSET"]
    for key, value in pairs:
        args.extend((key, value))
    expect_status(conn.command(*args), b"OK", context)


def verify_mget(
    conn: RespConnection,
    pairs: Sequence[tuple[bytes, bytes]],
    context: str,
) -> list[tuple[bytes, bytes]]:
    reply = expect_array(
        conn.command(b"MGET", *(key for key, _value in pairs)),
        len(pairs),
        context,
    )
    actual: list[tuple[bytes, bytes]] = []
    for index, ((key, expected), value) in enumerate(zip(pairs, reply)):
        expect_exact(value, expected, f"{context}[{index}] key={key!r}")
        actual.append((key, value))
    return actual


# ---------------------------------------------------------------------------
# fidelity
# ---------------------------------------------------------------------------


@dataclass
class FidelityShared:
    first_scan: threading.Event
    traffic_release: threading.Event
    scan_done: threading.Event
    progress_lock: threading.Lock
    first_transactions: int = 0


def _fidelity_worker(
    client_id: int,
    port: int,
    timeout: float,
    rounds: int,
    shared: FidelityShared,
    errors: ErrorBox,
    final_maps: list[dict[bytes, bytes] | None],
    tail_gets: list[int],
) -> None:
    local_final: dict[bytes, bytes] = {}
    try:
        with RespConnection(port, timeout, f"fidelity-client-{client_id}") as conn:
            if not shared.first_scan.wait(timeout):
                raise ConformanceError("SCAN did not publish its first nonzero cursor")
            for round_id in range(rounds):
                for size_index, size in enumerate(VALUE_SIZES):
                    one_key = (
                        f"bs:fidelity:data:c{client_id}:s{size}:one".encode("ascii")
                    )
                    one_value = deterministic_value(
                        f"fid:c{client_id}:r{round_id}:s{size}:one".encode("ascii"),
                        size,
                    )
                    expect_status(
                        conn.command(b"SET", one_key, one_value),
                        b"OK",
                        f"fidelity c{client_id} r{round_id} SET {size}",
                    )
                    expect_exact(
                        conn.command(b"GET", one_key),
                        one_value,
                        f"fidelity c{client_id} r{round_id} GET {size}",
                    )
                    local_final[one_key] = one_value

                    multi: list[tuple[bytes, bytes]] = []
                    for item in range(4):
                        key = (
                            f"bs:fidelity:data:c{client_id}:s{size}:multi:{item}"
                        ).encode("ascii")
                        value = deterministic_value(
                            (
                                f"fid:c{client_id}:r{round_id}:s{size}:"
                                f"multi:{item}"
                            ).encode("ascii"),
                            size,
                        )
                        multi.append((key, value))
                        local_final[key] = value
                    mset_pairs(
                        conn,
                        multi,
                        f"fidelity c{client_id} r{round_id} MSET {size}",
                    )
                    verify_mget(
                        conn,
                        multi,
                        f"fidelity c{client_id} r{round_id} MGET {size}",
                    )

                    # Hold the first SCAN cursor open until all eight clients have
                    # completed both single- and multi-key traffic.
                    if round_id == 0 and size_index == 0:
                        with shared.progress_lock:
                            shared.first_transactions += 1
                        if not shared.traffic_release.wait(timeout):
                            raise ConformanceError(
                                "SCAN did not release concurrent traffic"
                            )
                    if errors.stop.is_set():
                        return

            final_maps[client_id] = local_final

            # If the deterministic mutation rounds outrun SCAN, keep exact reads
            # flowing until cursor zero.  This changes no final state or digest.
            ordered = sorted(local_final.items())
            while not shared.scan_done.is_set() and not errors.stop.is_set():
                verify_mget(
                    conn,
                    ordered,
                    f"fidelity c{client_id} concurrent SCAN tail MGET",
                )
                tail_gets[client_id] += len(ordered)
    except BaseException as exc:
        errors.fail(f"fidelity-client-{client_id}", exc)
        shared.traffic_release.set()
        shared.scan_done.set()


def _scan_page(conn: RespConnection, cursor: int) -> tuple[int, list[bytes]]:
    reply = expect_array(
        conn.command(
            b"SCAN",
            cursor,
            b"MATCH",
            b"bs:fidelity:scan:*",
            b"COUNT",
            # COUNT is deliberately large enough to finish over the suite's
            # two-million-key seeded database in bounded time.  The scanner
            # holds the first nonzero cursor at a barrier, so concurrency does
            # not depend on making the pages artificially tiny.
            257,
        ),
        2,
        "fidelity SCAN",
    )
    raw_cursor, raw_keys = reply
    if not isinstance(raw_cursor, RespBulkString) or not raw_cursor.isdigit():
        raise ConformanceError(
            f"fidelity SCAN: invalid cursor {_describe_bytes(raw_cursor)}"
        )
    if not isinstance(raw_keys, list):
        raise ConformanceError(
            f"fidelity SCAN: key collection is {type(raw_keys).__name__}, not array"
        )
    keys: list[bytes] = []
    for index, key in enumerate(raw_keys):
        if not isinstance(key, RespBulkString):
            raise ConformanceError(
                f"fidelity SCAN: key {index} is {type(key).__name__}, not bulk"
            )
        keys.append(key)
    return int(raw_cursor), keys


def _fidelity_scanner(
    port: int,
    timeout: float,
    expected_keys: set[bytes],
    shared: FidelityShared,
    errors: ErrorBox,
    scan_result: dict[str, Any],
) -> None:
    seen: set[bytes] = set()
    calls = 0
    try:
        with RespConnection(port, timeout, "fidelity-scanner") as conn:
            cursor, keys = _scan_page(conn, 0)
            calls += 1
            if cursor == 0:
                raise ConformanceError(
                    "first SCAN returned cursor zero; concurrent scan-bearing "
                    "traffic was not exercised"
                )
            for key in keys:
                if key not in expected_keys:
                    raise ConformanceError(
                        f"SCAN MATCH returned unexpected key {key!r}"
                    )
                seen.add(key)
            shared.first_scan.set()

            wait_for(
                lambda: shared.first_transactions == NCLIENTS,
                time.monotonic() + timeout,
                errors,
                "all eight fidelity clients to transact under an open SCAN cursor",
            )
            shared.traffic_release.set()

            scan_deadline = time.monotonic() + max(120.0, timeout * 4)
            while cursor != 0:
                if errors.stop.is_set():
                    errors.check()
                if calls > 100_000 or time.monotonic() >= scan_deadline:
                    raise ConformanceError(
                        f"SCAN did not reach cursor zero after {calls} calls"
                    )
                cursor, keys = _scan_page(conn, cursor)
                calls += 1
                for key in keys:
                    if key not in expected_keys:
                        raise ConformanceError(
                            f"SCAN MATCH returned unexpected key {key!r}"
                        )
                    seen.add(key)

            missing = sorted(expected_keys - seen)
            if missing:
                preview = b", ".join(missing[:3])
                raise ConformanceError(
                    f"SCAN missed {len(missing)} stable keys; first={preview!r}"
                )
            if seen != expected_keys:
                raise ConformanceError(
                    f"SCAN set mismatch: expected={len(expected_keys)} seen={len(seen)}"
                )
            scan_result["seen"] = seen
            scan_result["calls"] = calls
    except BaseException as exc:
        errors.fail("fidelity-scanner", exc)
    finally:
        shared.first_scan.set()
        shared.traffic_release.set()
        shared.scan_done.set()


def run_fidelity(args: argparse.Namespace) -> None:
    validate_port(args.port)
    timeout = command_timeout(args.quick)
    rounds = 3 if args.quick else 12
    scan_count = 384 if args.quick else 2048
    max_scan_count = 2048
    scan_keys = [
        f"bs:fidelity:scan:{index:05d}".encode("ascii")
        for index in range(scan_count)
    ]
    all_possible_scan_keys = [
        f"bs:fidelity:scan:{index:05d}".encode("ascii")
        for index in range(max_scan_count)
    ]
    scan_values = {
        key: deterministic_value(b"scan:" + key, 32) for key in scan_keys
    }

    # A repeated invocation on one server must not inherit the full profile's
    # extra keys and turn QUICK into a false SCAN failure.
    with RespConnection(args.port, timeout, "fidelity-setup") as setup:
        delete_keys(setup, all_possible_scan_keys)
        for offset in range(0, len(scan_keys), 64):
            pairs = [
                (key, scan_values[key]) for key in scan_keys[offset : offset + 64]
            ]
            mset_pairs(setup, pairs, f"fidelity stable SCAN seed {offset // 64}")

    shared = FidelityShared(
        first_scan=threading.Event(),
        traffic_release=threading.Event(),
        scan_done=threading.Event(),
        progress_lock=threading.Lock(),
    )
    errors = ErrorBox()
    final_maps: list[dict[bytes, bytes] | None] = [None] * NCLIENTS
    tail_gets = [0] * NCLIENTS
    scan_result: dict[str, Any] = {}
    scanner = threading.Thread(
        target=_fidelity_scanner,
        name="fidelity-scanner",
        args=(
            args.port,
            timeout,
            set(scan_keys),
            shared,
            errors,
            scan_result,
        ),
        daemon=True,
    )
    workers = [
        threading.Thread(
            target=_fidelity_worker,
            name=f"fidelity-client-{client_id}",
            args=(
                client_id,
                args.port,
                timeout,
                rounds,
                shared,
                errors,
                final_maps,
                tail_gets,
            ),
            daemon=True,
        )
        for client_id in range(NCLIENTS)
    ]
    scanner.start()
    for worker in workers:
        worker.start()
    threads = [scanner, *workers]
    try:
        join_threads(
            threads,
            time.monotonic() + (180.0 if args.quick else 600.0),
            errors,
            "fidelity threads",
        )
    finally:
        errors.stop.set()
        shared.first_scan.set()
        shared.traffic_release.set()
        shared.scan_done.set()
    errors.check()
    if any(final is None for final in final_maps):
        raise ConformanceError("one or more fidelity clients produced no final map")
    if scan_result.get("seen") != set(scan_keys):
        raise ConformanceError("scanner produced no exact final key set")

    expected_data: dict[bytes, bytes] = {}
    for final in final_maps:
        assert final is not None
        overlap = expected_data.keys() & final.keys()
        if overlap:
            raise ConformanceError(
                f"fidelity clients unexpectedly shared keys: {next(iter(overlap))!r}"
            )
        expected_data.update(final)

    records: list[tuple[bytes, bytes, bytes]] = []
    with RespConnection(args.port, timeout, "fidelity-final") as final_conn:
        data_pairs = sorted(expected_data.items())
        for offset in range(0, len(data_pairs), 32):
            for key, value in verify_mget(
                final_conn,
                data_pairs[offset : offset + 32],
                f"fidelity final data MGET {offset // 32}",
            ):
                records.append((b"data", key, value))
        stable_pairs = sorted(scan_values.items())
        for offset in range(0, len(stable_pairs), 64):
            for key, value in verify_mget(
                final_conn,
                stable_pairs[offset : offset + 64],
                f"fidelity final scan-canary MGET {offset // 64}",
            ):
                records.append((b"scan", key, value))

    per_round = NCLIENTS * len(VALUE_SIZES)
    emit_json(
        {
            "case": "fidelity",
            "clients": NCLIENTS,
            "digest": canonical_digest(records),
            "mget_values": per_round * rounds * 4,
            "mset_values": per_round * rounds * 4,
            "profile": "quick" if args.quick else "full",
            "rounds": rounds,
            "scan_complete": True,
            "scan_keys": scan_count,
            "single_gets": per_round * rounds,
            "single_sets": per_round * rounds,
            "sizes": list(VALUE_SIZES),
        }
    )


# ---------------------------------------------------------------------------
# Tomo seed-0 XXH64 and migration
# ---------------------------------------------------------------------------


_MASK64 = (1 << 64) - 1
_XX_P1 = 0x9E3779B185EBCA87
_XX_P2 = 0xC2B2AE3D27D4EB4F
_XX_P3 = 0x165667B19E3779F9
_XX_P4 = 0x85EBCA77C2B2AE63
_XX_P5 = 0x27D4EB2F165667C5


def _rotl64(value: int, amount: int) -> int:
    return ((value << amount) | (value >> (64 - amount))) & _MASK64


def _xx_round(accumulator: int, word: int) -> int:
    accumulator = (accumulator + word * _XX_P2) & _MASK64
    accumulator = _rotl64(accumulator, 31)
    return (accumulator * _XX_P1) & _MASK64


def _xx_merge(accumulator: int, value: int) -> int:
    value = _xx_round(0, value)
    accumulator ^= value
    return (accumulator * _XX_P1 + _XX_P4) & _MASK64


def xxh64(data: bytes) -> int:
    """Byte-exact mirror of src/server.c xxh64(), fixed at seed zero."""

    length = len(data)
    offset = 0
    if length >= 32:
        v1 = (_XX_P1 + _XX_P2) & _MASK64
        v2 = _XX_P2
        v3 = 0
        v4 = (-_XX_P1) & _MASK64
        while offset + 32 <= length:
            v1 = _xx_round(v1, int.from_bytes(data[offset : offset + 8], "little"))
            offset += 8
            v2 = _xx_round(v2, int.from_bytes(data[offset : offset + 8], "little"))
            offset += 8
            v3 = _xx_round(v3, int.from_bytes(data[offset : offset + 8], "little"))
            offset += 8
            v4 = _xx_round(v4, int.from_bytes(data[offset : offset + 8], "little"))
            offset += 8
        result = (
            _rotl64(v1, 1)
            + _rotl64(v2, 7)
            + _rotl64(v3, 12)
            + _rotl64(v4, 18)
        ) & _MASK64
        result = _xx_merge(result, v1)
        result = _xx_merge(result, v2)
        result = _xx_merge(result, v3)
        result = _xx_merge(result, v4)
    else:
        result = _XX_P5

    result = (result + length) & _MASK64
    while offset + 8 <= length:
        word = int.from_bytes(data[offset : offset + 8], "little")
        result ^= _xx_round(0, word)
        result = (_rotl64(result, 27) * _XX_P1 + _XX_P4) & _MASK64
        offset += 8
    if offset + 4 <= length:
        word32 = int.from_bytes(data[offset : offset + 4], "little")
        result ^= (word32 * _XX_P1) & _MASK64
        result = (_rotl64(result, 23) * _XX_P2 + _XX_P3) & _MASK64
        offset += 4
    while offset < length:
        result ^= (data[offset] * _XX_P5) & _MASK64
        result = (_rotl64(result, 11) * _XX_P1) & _MASK64
        offset += 1
    result ^= result >> 33
    result = (result * _XX_P2) & _MASK64
    result ^= result >> 29
    result = (result * _XX_P3) & _MASK64
    result ^= result >> 32
    return result & _MASK64


def xxh64_selftest() -> None:
    vectors = (
        (b"", 0xEF46DB3751D8E999),
        (b"a", 0xD24EC4F1A98C6E5B),
        (b"abc", 0x44BC2CF5AD770999),
        (b"hot:0", 0x161254E3E3D96BF8),
        (bytes(range(37)), 0xD93FA2DFEE5C24C9),
        (bytes(range(64)), 0xF7C67301DB6713F0),
    )
    for payload, expected in vectors:
        actual = xxh64(payload)
        if actual != expected:
            raise ConformanceError(
                "XXH64 seed-0 self-test failed for "
                f"{payload[:16]!r}: {actual:016x} != {expected:016x}"
            )


def tomo_bucket(key: bytes) -> int:
    return xxh64(key) & (TOMO_BUCKETS - 1)


def generate_migration_canaries(
    quick: bool,
) -> tuple[list[tuple[bytes, bytes, int]], dict[int, tuple[bytes, bytes]]]:
    # Full qualification has one exact canary in every ownership bucket.  A
    # controller role move or post-flip RELEVEL can change the live boundaries
    # before the key balancer fires, so covering only the originally-hot suffix
    # cannot prove an arbitrary logged moved range. QUICK is explicitly sampled.
    step = MIGRATION_QUICK_STRIDE if quick else 1
    wanted = set(range(0, TOMO_BUCKETS, step))
    by_bucket: dict[int, tuple[bytes, bytes]] = {}
    candidate = 0
    while wanted and candidate < 2_000_000:
        key = f"bs:migration:canary:{candidate:08d}".encode("ascii")
        bucket = tomo_bucket(key)
        if bucket in wanted:
            value = deterministic_value(
                f"migration:b{bucket}:".encode("ascii") + key, 64
            )
            by_bucket[bucket] = (key, value)
            wanted.remove(bucket)
        candidate += 1
    if wanted:
        raise ConformanceError(
            f"could not generate canaries for {len(wanted)} ownership buckets"
        )
    ordered = [
        (key, value, bucket)
        for bucket, (key, value) in sorted(by_bucket.items())
    ]
    return ordered, by_bucket


def parse_debug_find_reply(reply: Any, key: bytes) -> tuple[int, int]:
    if not isinstance(reply, RespSimpleString):
        raise ConformanceError(
            f"DEBUG RESHARD FIND {key!r}: expected status, "
            f"got {_describe_bytes(reply)}"
        )
    fields: dict[bytes, bytes] = {}
    for token in reply.split():
        if b"=" in token:
            name, value = token.split(b"=", 1)
            fields[name] = value
    try:
        bucket = int(fields[b"bucket"])
        routed = int(fields[b"routed_ex"])
    except (KeyError, ValueError) as exc:
        raise ConformanceError(
            f"DEBUG RESHARD FIND {key!r}: unparseable reply {reply!r}"
        ) from exc
    local = tomo_bucket(key)
    if bucket != local:
        raise ConformanceError(
            f"XXH64 routing mismatch for {key!r}: local={local} server={bucket}"
        )
    return bucket, routed


def debug_find(conn: RespConnection, key: bytes) -> tuple[int, int]:
    return parse_debug_find_reply(
        conn.command(b"DEBUG", b"RESHARD", b"FIND", key), key
    )


def debug_find_many(
    conn: RespConnection, entries: Sequence[tuple[int, bytes]]
) -> list[tuple[int, int]]:
    """Pipeline strict FIND proofs without changing their per-key oracle."""

    found: list[tuple[int, int]] = []
    for offset in range(0, len(entries), 128):
        batch = entries[offset : offset + 128]
        replies = conn.pipeline(
            [(b"DEBUG", b"RESHARD", b"FIND", key) for _bucket, key in batch]
        )
        for (expected_bucket, key), reply in zip(batch, replies):
            bucket, route = parse_debug_find_reply(reply, key)
            if bucket != expected_bucket:
                raise ConformanceError(
                    f"DEBUG RESHARD FIND {key!r}: expected bucket "
                    f"{expected_bucket}, server reported {bucket}"
                )
            found.append((bucket, route))
    return found


def debug_worker_count(conn: RespConnection) -> int:
    reply = conn.command(b"DEBUG", b"RESHARD", b"PERWORKER")
    if (
        not isinstance(reply, list)
        or not reply
        or any(not isinstance(value, int) or value < 0 for value in reply)
    ):
        raise ConformanceError(
            "DEBUG RESHARD PERWORKER did not return a nonempty array "
            "of nonnegative counters"
        )
    return len(reply)


def debug_reshard_status(conn: RespConnection) -> dict[bytes, int]:
    reply = conn.command(b"DEBUG", b"RESHARD", b"STATUS")
    if not isinstance(reply, RespSimpleString):
        raise ConformanceError(
            "DEBUG RESHARD STATUS expected a status reply, "
            f"got {_describe_bytes(reply)}"
        )
    fields: dict[bytes, int] = {}
    for token in reply.split():
        if b"=" not in token:
            continue
        name, raw_value = token.split(b"=", 1)
        try:
            fields[name] = int(raw_value)
        except ValueError as exc:
            raise ConformanceError(
                f"DEBUG RESHARD STATUS has nonnumeric {name!r}: {reply!r}"
            ) from exc
    required = (b"active", b"phase", b"lo", b"hi", b"src", b"dst")
    missing = [name.decode("ascii") for name in required if name not in fields]
    if missing:
        raise ConformanceError(
            "DEBUG RESHARD STATUS lacks fields "
            f"{','.join(missing)}: {reply!r}"
        )
    return fields


def prove_moved_routes(
    conn: RespConnection,
    moved: Sequence[tuple[int, bytes, bytes]],
    moved_lo: int,
    moved_hi: int,
    moved_src: int,
    moved_dst: int,
    quick: bool,
) -> dict[str, Any]:
    """Prove the selected completed range routes from its logged src to dst."""

    status = debug_reshard_status(conn)
    worker_count = debug_worker_count(conn)
    if status[b"active"] != 0:
        raise ConformanceError(
            "moved-range route proof ran while migration remained active: "
            f"active={status[b'active']} phase={status[b'phase']}"
        )
    if status[b"lo"] != moved_lo or status[b"hi"] != moved_hi:
        raise ConformanceError(
            "reported moved range disagrees with DEBUG RESHARD STATUS: "
            f"argument=[{moved_lo},{moved_hi}) "
            f"status=[{status[b'lo']},{status[b'hi']})"
        )
    if status[b"src"] != moved_src or status[b"dst"] != moved_dst:
        raise ConformanceError(
            "reported moved workers disagree with DEBUG RESHARD STATUS: "
            f"argument={moved_src}->{moved_dst} "
            f"status={status[b'src']}->{status[b'dst']}"
        )
    if (
        moved_src < 0
        or moved_src >= worker_count
        or moved_dst < 0
        or moved_dst >= worker_count
        or moved_src == moved_dst
    ):
        raise ConformanceError(
            "DEBUG RESHARD STATUS has invalid source/destination for "
            f"{worker_count} worker slots: src={moved_src} dst={moved_dst}"
        )
    expected_canaries = moved_hi - moved_lo
    coverage_complete = not quick
    if coverage_complete and len(moved) != expected_canaries:
        raise ConformanceError(
            "full moved-range proof is not bucket-complete: "
            f"range=[{moved_lo},{moved_hi}) expected={expected_canaries} "
            f"canaries={len(moved)}"
        )

    routes: set[int] = set()
    changed_proofs = 0
    destination_proofs = 0
    entries = [(bucket, key) for bucket, key, _value in moved]
    for (bucket, key, _value), (_found_bucket, route) in zip(
        moved, debug_find_many(conn, entries)
    ):
        if route < 0 or route >= worker_count:
            raise ConformanceError(
                f"moved canary {key!r}: routed_ex={route} is outside "
                f"valid worker slots [0,{worker_count})"
            )
        if route == moved_src:
            raise ConformanceError(
                f"moved canary {key!r}: route did not change from "
                f"recorded source worker {moved_src}"
            )
        changed_proofs += 1
        if route != moved_dst:
            raise ConformanceError(
                f"moved canary {key!r}: expected completed destination "
                f"worker {moved_dst}, got {route}"
            )
        destination_proofs += 1
        routes.add(route)

    return {
        "moved_bucket_coverage_complete": coverage_complete,
        "moved_bucket_coverage_stride": (
            MIGRATION_QUICK_STRIDE if quick else 1
        ),
        "moved_bucket_span": expected_canaries,
        "moved_dst": moved_dst,
        "moved_route_change_proofs": changed_proofs,
        "moved_route_destination_proofs": destination_proofs,
        "moved_route_find_proofs": len(moved),
        "moved_routes": sorted(routes),
        "moved_src": moved_src,
        "route_worker_slots": worker_count,
    }


def _migration_worker(
    client_id: int,
    port: int,
    timeout: float,
    focus_keys: Sequence[bytes],
    buckets_by_key: dict[bytes, int],
    values: dict[bytes, bytes],
    pipeline_size: int,
    seed: int,
    go: threading.Event,
    connected: list[int],
    connected_lock: threading.Lock,
    running: list[int],
    running_lock: threading.Lock,
    active: list[int],
    active_lock: threading.Lock,
    run_deadline: list[float],
    ready_file: str | None,
    touched_buckets: set[int],
    touched_lock: threading.Lock,
    errors: ErrorBox,
    ops_by_client: list[int],
) -> None:
    cursor = seed % len(focus_keys)
    entered_sustained_loop = False
    try:
        with RespConnection(port, timeout, f"migration-client-{client_id}") as conn:
            with connected_lock:
                connected[0] += 1
            if not go.wait(timeout):
                raise ConformanceError("migration start barrier timed out")
            local_ops = 0
            while (
                time.monotonic() < run_deadline[0] and not errors.stop.is_set()
            ):
                chosen = [
                    focus_keys[(cursor + index) % len(focus_keys)]
                    for index in range(pipeline_size)
                ]
                cursor = (cursor + pipeline_size) % len(focus_keys)
                replies = conn.pipeline([(b"GET", key) for key in chosen])
                for index, (key, reply) in enumerate(zip(chosen, replies)):
                    expect_exact(
                        reply,
                        values[key],
                        f"migration c{client_id} pipeline[{index}] key={key!r}",
                    )
                with touched_lock:
                    touched_buckets.update(buckets_by_key[key] for key in chosen)
                local_ops += len(chosen)
                if (
                    not entered_sustained_loop
                    and local_ops >= len(focus_keys)
                ):
                    # Readiness means every worker has completed at least one
                    # deterministic, byte-exact sweep of the entire hot domain,
                    # then remained in the same cyclic sustained-traffic loop.
                    with active_lock:
                        active[0] += 1
                    entered_sustained_loop = True
                    with running_lock:
                        running[0] += 1
            ops_by_client[client_id] = local_ops
    except BaseException as exc:
        errors.fail(f"migration-client-{client_id}", exc)
        go.set()
    finally:
        if entered_sustained_loop:
            with active_lock:
                active[0] -= 1
                last_active_reader = active[0] == 0
            # The ready file is a lease, not a historical marker. Remove it
            # from the last exact-reader worker's exit path so the shell can
            # never mistake the join/finalization gap for live overlap.
            if last_active_reader and ready_file is not None:
                try:
                    os.unlink(ready_file)
                except FileNotFoundError:
                    pass


def run_migration(args: argparse.Namespace) -> None:
    validate_port(args.port)
    validate_seconds(args.seconds)
    timeout = command_timeout(args.quick)
    ready_file = validate_ready_file(args.ready_file)
    selection_file = validate_control_file(args.selection_file, "--selection-file")
    stop_file = validate_control_file(args.stop_file, "--stop-file")
    if args.verify_only and any(
        path is not None for path in (ready_file, selection_file, stop_file)
    ):
        raise ConformanceError(
            "--ready-file, --selection-file, and --stop-file are only valid "
            "for the traffic-bearing migration run"
        )
    moved_arguments = (
        args.moved_lo,
        args.moved_hi,
        args.moved_src,
        args.moved_dst,
    )
    if any(value is not None for value in moved_arguments) and not all(
        value is not None for value in moved_arguments
    ):
        raise ConformanceError(
            "--moved-lo, --moved-hi, --moved-src, and --moved-dst "
            "must be supplied together"
        )
    if args.moved_lo is not None and not (
        0 <= args.moved_lo < args.moved_hi <= TOMO_BUCKETS
    ):
        raise ConformanceError(
            f"invalid moved range [{args.moved_lo},{args.moved_hi})"
        )
    if args.moved_src is not None and (
        args.moved_src < 0
        or args.moved_dst < 0
        or args.moved_src == args.moved_dst
    ):
        raise ConformanceError(
            f"invalid moved workers {args.moved_src}->{args.moved_dst}"
        )
    if not args.verify_only and any(value is not None for value in moved_arguments):
        raise ConformanceError(
            "--moved-* arguments are only valid with --verify-only; use "
            "--selection-file for the traffic-bearing run"
        )

    canaries, by_bucket = generate_migration_canaries(args.quick)
    values = {key: value for key, value, _bucket in canaries}
    keys = [key for key, _value, _bucket in canaries]
    buckets_by_key = {key: bucket for key, _value, bucket in canaries}
    focus_keys = [
        key
        for key, _value, bucket in canaries
        if MIGRATION_LO <= bucket < MIGRATION_HI
    ]
    if not focus_keys:
        raise ConformanceError("migration traffic focus has no deterministic canary")

    if args.verify_only:
        if args.moved_lo is None:
            raise ConformanceError(
                "--verify-only requires all four --moved-* arguments"
            )
        verify_records: list[tuple[bytes, bytes, bytes]] = []
        moved = [
            (bucket, by_bucket[bucket][0], by_bucket[bucket][1])
            for bucket in sorted(by_bucket)
            if args.moved_lo <= bucket < args.moved_hi
        ]
        if not moved:
            raise ConformanceError(
                f"reported moved range [{args.moved_lo},{args.moved_hi}) "
                "contains no deterministic canary"
            )
        route_proof: dict[str, Any]
        with RespConnection(args.port, timeout, "migration-read-only-verify") as conn:
            # Bind the selected logged status/range first. The all-canary
            # value digest follows on the same bounded connection, but must
            # not delay this immediate post-DONE ownership observation.
            route_proof = prove_moved_routes(
                conn,
                moved,
                args.moved_lo,
                args.moved_hi,
                args.moved_src,
                args.moved_dst,
                args.quick,
            )
            pairs = sorted(values.items())
            for offset in range(0, len(pairs), 64):
                for key, value in verify_mget(
                    conn,
                    pairs[offset : offset + 64],
                    f"migration read-only final MGET {offset // 64}",
                ):
                    verify_records.append((b"canary", key, value))
        verify_result = {
            "bucket_coverage_complete": not args.quick,
            "bucket_coverage_stride": (
                MIGRATION_QUICK_STRIDE if args.quick else 1
            ),
            "canaries": len(canaries),
            "case": "migration-read-only-verify",
            "digest": canonical_digest(verify_records),
            "moved_canaries": len(moved),
            "moved_hi": args.moved_hi,
            "moved_lo": args.moved_lo,
            "profile": "quick" if args.quick else "full",
            "writes": 0,
        }
        verify_result.update(route_proof)
        emit_json(verify_result)
        return

    with RespConnection(args.port, timeout, "migration-setup") as setup:
        for offset in range(0, len(canaries), 64):
            pairs = [
                (key, value)
                for key, value, _bucket in canaries[offset : offset + 64]
            ]
            mset_pairs(setup, pairs, f"migration canary seed {offset // 64}")

        # Record every canary's pre-traffic route while the shell still has
        # key balancing disabled.  Sampling here would make a later route
        # comparison incapable of proving that each reported canary moved.
        initial_routes: set[int] = set()
        initial_route_by_key: dict[bytes, int] = {}
        initial_worker_count = debug_worker_count(setup)
        initial_found = debug_find_many(
            setup, [(bucket, key) for key, _value, bucket in canaries]
        )
        for (key, _value, _bucket), (_found_bucket, route) in zip(
            canaries, initial_found
        ):
            if route < 0 or route >= initial_worker_count:
                raise ConformanceError(
                    f"initial canary {key!r}: routed_ex={route} is outside "
                    f"valid worker slots [0,{initial_worker_count})"
                )
            initial_route_by_key[key] = route
            initial_routes.add(route)

    seeds = [0x5EED0000 + client_id * 0x9E37 for client_id in range(NCLIENTS)]
    pipeline_size = 24 if args.quick else 64
    errors = ErrorBox()
    go = threading.Event()
    connected = [0]
    connected_lock = threading.Lock()
    running = [0]
    running_lock = threading.Lock()
    active = [0]
    active_lock = threading.Lock()
    # Workers cannot enter the loop before `go`, and the finite qualification
    # window begins only after every worker completes one exact GET pipeline.
    run_deadline = [float("inf")]
    ops_by_client = [0] * NCLIENTS
    touched_buckets: set[int] = set()
    touched_lock = threading.Lock()
    workers = [
        threading.Thread(
            target=_migration_worker,
            name=f"migration-client-{client_id}",
            args=(
                client_id,
                args.port,
                timeout,
                focus_keys,
                buckets_by_key,
                values,
                pipeline_size,
                seeds[client_id],
                go,
                connected,
                connected_lock,
                running,
                running_lock,
                active,
                active_lock,
                run_deadline,
                ready_file,
                touched_buckets,
                touched_lock,
                errors,
                ops_by_client,
            ),
            daemon=True,
        )
        for client_id in range(NCLIENTS)
    ]
    for worker in workers:
        worker.start()
    stop_observed = threading.Event()
    stop_watcher: threading.Thread | None = None
    try:
        wait_for(
            lambda: connected[0] == NCLIENTS,
            time.monotonic() + timeout,
            errors,
            "all migration clients to connect",
        )
        go.set()
        wait_for(
            lambda: running[0] == NCLIENTS,
            time.monotonic() + timeout,
            errors,
            "all migration clients to complete an exact hot-domain GET sweep",
        )
        errors.check()
        if not all(worker.is_alive() for worker in workers):
            raise ConformanceError(
                "a migration GET worker exited before readiness publication"
            )
        run_deadline[0] = time.monotonic() + args.seconds
        # The helper never enables key balancing. The shell owns that control
        # change and treats this marker as an active-reader lease: it exists
        # only while all eight qualified GET workers are in their timed loop.
        if ready_file is not None:
            publish_ready_file(ready_file)
        if stop_file is not None:
            stop_watcher = threading.Thread(
                target=_watch_stop_file,
                name="migration-stop-file-watcher",
                args=(
                    stop_file,
                    run_deadline[0] + timeout + 5.0,
                    errors.stop,
                    stop_observed,
                ),
                daemon=True,
            )
            stop_watcher.start()
        join_threads(
            workers,
            run_deadline[0] + timeout + 5.0,
            errors,
            "migration clients",
        )
    finally:
        errors.stop.set()
        go.set()
        cleanup_deadline = time.monotonic() + timeout + 5.0
        for worker in workers:
            remaining = cleanup_deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(remaining)
        if stop_watcher is not None:
            stop_watcher.join(max(0.0, cleanup_deadline - time.monotonic()))
        if ready_file is not None:
            try:
                os.unlink(ready_file)
            except FileNotFoundError:
                pass
    errors.check()
    if any(count <= 0 for count in ops_by_client):
        raise ConformanceError(
            f"migration client completed no GETs: ops={ops_by_client}"
        )
    focus_buckets = {
        bucket
        for _key, _value, bucket in canaries
        if MIGRATION_LO <= bucket < MIGRATION_HI
    }
    if touched_buckets != focus_buckets:
        raise ConformanceError(
            "sustained exact traffic did not cover the complete hot domain: "
            f"proved={len(touched_buckets)} expected={len(focus_buckets)}"
        )

    selection = read_migration_selection(selection_file)
    selected_canaries = 0
    selected_initial_source_proofs = 0
    selected_traffic_read_proofs = 0
    selected_bucket_coverage_complete = False
    selected_lo: int | None = None
    selected_hi: int | None = None
    selected_src: int | None = None
    selected_dst: int | None = None
    if selection is not None:
        selected_lo, selected_hi, selected_src, selected_dst = selection
        if (
            selected_src >= initial_worker_count
            or selected_dst >= initial_worker_count
        ):
            raise ConformanceError(
                "migration selection workers are outside the initial worker "
                f"slots [0,{initial_worker_count}): {selected_src}->{selected_dst}"
            )
        selected = [
            (bucket, key)
            for key, _value, bucket in canaries
            if selected_lo <= bucket < selected_hi
        ]
        if not selected:
            raise ConformanceError(
                f"selected range [{selected_lo},{selected_hi}) contains no "
                "deterministic canary"
            )
        selected_canaries = len(selected)
        for bucket, key in selected:
            if bucket in touched_buckets:
                selected_traffic_read_proofs += 1
            route = initial_route_by_key[key]
            if route != selected_src:
                raise ConformanceError(
                    f"selected canary bucket={bucket} key={key!r} began on "
                    f"worker {route}, not logged source {selected_src}"
                )
            selected_initial_source_proofs += 1
        if selected_traffic_read_proofs != selected_canaries:
            raise ConformanceError(
                "selected moved range was not covered by exact helper traffic: "
                f"proved={selected_traffic_read_proofs} "
                f"selected={selected_canaries}"
            )
        selected_bucket_coverage_complete = not args.quick
        if (
            selected_bucket_coverage_complete
            and selected_canaries != selected_hi - selected_lo
        ):
            raise ConformanceError(
                "full selected-range initial-source proof is not "
                f"bucket-complete: range=[{selected_lo},{selected_hi}) "
                f"expected={selected_hi - selected_lo} "
                f"canaries={selected_canaries}"
            )

    records: list[tuple[bytes, bytes, bytes]] = []
    final_routes: set[int] = set()
    final_route_by_key: dict[bytes, int] = {}
    with RespConnection(args.port, timeout, "migration-final") as final_conn:
        pairs = sorted(values.items())
        for offset in range(0, len(pairs), 64):
            for key, value in verify_mget(
                final_conn,
                pairs[offset : offset + 64],
                f"migration final MGET {offset // 64}",
            ):
                records.append((b"canary", key, value))

        final_worker_count = debug_worker_count(final_conn)
        final_found = debug_find_many(
            final_conn, [(bucket, key) for key, _value, bucket in canaries]
        )
        for (key, _value, _bucket), (_found_bucket, route) in zip(
            canaries, final_found
        ):
            if route < 0 or route >= final_worker_count:
                raise ConformanceError(
                    f"final canary {key!r}: routed_ex={route} is outside "
                    f"valid worker slots [0,{final_worker_count})"
                )
            final_route_by_key[key] = route
            final_routes.add(route)

    changed_from_initial = sum(
        final_route_by_key[key] != initial_route_by_key[key] for key in keys
    )
    result: dict[str, Any] = {
        "bucket_coverage_complete": not args.quick,
        "bucket_coverage_stride": (
            MIGRATION_QUICK_STRIDE if args.quick else 1
        ),
        "canaries": len(canaries),
        "case": "migration",
        "clients": NCLIENTS,
        "digest": canonical_digest(records),
        "exact_get_workers_running": running[0],
        "final_routes": sorted(final_routes),
        "get_ops": sum(ops_by_client),
        "initial_routes": sorted(initial_routes),
        "min_client_get_ops": min(ops_by_client),
        "pipeline": pipeline_size,
        "profile": "quick" if args.quick else "full",
        "ready_file_published": ready_file is not None,
        "route_changed_from_initial": changed_from_initial,
        "route_post_find_proofs": len(final_route_by_key),
        "route_pre_find_proofs": len(initial_route_by_key),
        "route_unchanged_from_initial": len(canaries) - changed_from_initial,
        "route_worker_slots": final_worker_count,
        "selected_bucket_coverage_complete": (
            selected_bucket_coverage_complete
        ),
        "selected_canaries": selected_canaries,
        "selected_initial_source_proofs": selected_initial_source_proofs,
        "selected_traffic_read_proofs": selected_traffic_read_proofs,
        "selection_published": selection is not None,
        "seeds": seeds,
        "stop_file_observed": stop_observed.is_set(),
        "target_hi": MIGRATION_HI,
        "target_lo": MIGRATION_LO,
        "traffic_read_bucket_proofs": len(touched_buckets),
    }
    if selection is not None:
        result.update(
            {
                "selected_dst": selected_dst,
                "selected_hi": selected_hi,
                "selected_lo": selected_lo,
                "selected_src": selected_src,
            }
        )
    emit_json(result)


# ---------------------------------------------------------------------------
# connection lifecycle
# ---------------------------------------------------------------------------


def _lifecycle_survivor(
    survivor_id: int,
    conn: RespConnection,
    key: bytes,
    value: bytes,
    go: threading.Event,
    errors: ErrorBox,
    counts: list[int],
    final_values: list[bytes | None],
    client_ids: list[int | None],
    owner_paths: list[list[int]],
    handoff_seen: threading.Event,
    owner_max_slot: int,
) -> None:
    try:
        client_id, owner = client_identity(
            conn,
            f"lifecycle survivor {survivor_id} initial owner",
            owner_max_slot,
        )
        client_ids[survivor_id] = client_id
        owner_paths[survivor_id].append(owner)
        if not go.wait(conn.timeout):
            raise ConformanceError("lifecycle start barrier timed out")
        while not errors.stop.is_set():
            replies = conn.pipeline([(b"GET", key)] * 8)
            for index, reply in enumerate(replies):
                expect_exact(
                    reply,
                    value,
                    f"lifecycle survivor {survivor_id} GET[{index}]",
                )
            counts[survivor_id] += len(replies)
            # CLIENT INFO is executed on this same non-reconnecting socket and
            # reports c->tid.  Sampling in the owning worker avoids concurrent
            # commands on one RESP stream and observes even a later rebalance
            # which moves the socket back to its initial owner.
            if counts[survivor_id] % 128 == 0:
                observed_id, observed_owner = client_identity(
                    conn,
                    f"lifecycle survivor {survivor_id} owner sample",
                    owner_max_slot,
                )
                if observed_id != client_id:
                    raise ConformanceError(
                        f"lifecycle survivor {survivor_id}: CLIENT INFO id "
                        f"changed on one socket ({client_id}->{observed_id})"
                    )
                if observed_owner != owner_paths[survivor_id][-1]:
                    owner_paths[survivor_id].append(observed_owner)
                    handoff_seen.set()

        # Snapshot the owner first, then issue a distinct exact command.  Thus
        # any transition in the reported path is followed by a known-value
        # reply on that same, still-open socket rather than merely by replies
        # which might have been queued before the handoff.
        observed_id, observed_owner = client_identity(
            conn,
            f"lifecycle survivor {survivor_id} final owner",
            owner_max_slot,
        )
        if observed_id != client_id:
            raise ConformanceError(
                f"lifecycle survivor {survivor_id}: CLIENT INFO id changed "
                f"on one socket ({client_id}->{observed_id})"
            )
        if observed_owner != owner_paths[survivor_id][-1]:
            owner_paths[survivor_id].append(observed_owner)
            handoff_seen.set()
        final_reply = conn.command(b"GET", key)
        expect_exact(
            final_reply, value, f"lifecycle survivor {survivor_id} final GET"
        )
        counts[survivor_id] += 1
        final_values[survivor_id] = final_reply
    except BaseException as exc:
        errors.fail(f"lifecycle-survivor-{survivor_id}", exc)
    finally:
        conn.close()


def _lifecycle_churn(
    churn_id: int,
    port: int,
    timeout: float,
    go: threading.Event,
    errors: ErrorBox,
    connections: list[int],
    command_counts: list[int],
) -> None:
    iteration = 0
    key = f"bs:lifecycle:churn:{churn_id}".encode("ascii")
    try:
        if not go.wait(timeout):
            raise ConformanceError("lifecycle churn start barrier timed out")
        while not errors.stop.is_set():
            value = deterministic_value(
                f"lifecycle:churn:{churn_id}:{iteration}".encode("ascii"), 32
            )
            with RespConnection(
                port,
                timeout,
                f"lifecycle-churn-{churn_id}-{iteration}",
            ) as conn:
                replies = conn.pipeline(((b"SET", key, value), (b"GET", key)))
                expect_status(
                    replies[0],
                    b"OK",
                    f"lifecycle churn {churn_id}/{iteration} SET",
                )
                expect_exact(
                    replies[1],
                    value,
                    f"lifecycle churn {churn_id}/{iteration} GET",
                )
            connections[churn_id] += 1
            command_counts[churn_id] += 2
            iteration += 1
            # Keep a long full run below the host's ephemeral-port/TIME_WAIT
            # ceiling.  This is lifecycle coverage, not a SYN-rate benchmark.
            errors.stop.wait(0.05)
    except BaseException as exc:
        errors.fail(f"lifecycle-churn-{churn_id}", exc)


def run_lifecycle(args: argparse.Namespace) -> None:
    validate_port(args.port)
    validate_seconds(args.seconds)
    if args.owner_max_slot < 0:
        raise ConformanceError("--owner-max-slot must be nonnegative")
    timeout = command_timeout(args.quick)
    survivor_count = 24 if args.quick else 48
    churn_threads = 4 if args.quick else 8
    survivor_pairs = [
        (
            f"bs:lifecycle:survivor:{index:03d}".encode("ascii"),
            deterministic_value(
                f"lifecycle:survivor:{index:03d}".encode("ascii"), 64
            ),
        )
        for index in range(survivor_count)
    ]

    survivor_connections: list[RespConnection] = []
    try:
        with RespConnection(args.port, timeout, "lifecycle-setup") as setup:
            for offset in range(0, len(survivor_pairs), 32):
                mset_pairs(
                    setup,
                    survivor_pairs[offset : offset + 32],
                    f"lifecycle survivor seed {offset // 32}",
                )
        for index in range(survivor_count):
            survivor_connections.append(
                RespConnection(args.port, timeout, f"lifecycle-survivor-{index}")
            )
    except BaseException:
        for conn in survivor_connections:
            conn.close()
        raise

    errors = ErrorBox()
    go = threading.Event()
    survivor_gets = [0] * survivor_count
    survivor_final: list[bytes | None] = [None] * survivor_count
    survivor_client_ids: list[int | None] = [None] * survivor_count
    survivor_owner_paths: list[list[int]] = [
        [] for _index in range(survivor_count)
    ]
    handoff_seen = threading.Event()
    churn_connections = [0] * churn_threads
    churn_commands = [0] * churn_threads
    survivors = [
        threading.Thread(
            target=_lifecycle_survivor,
            name=f"lifecycle-survivor-{index}",
            args=(
                index,
                survivor_connections[index],
                survivor_pairs[index][0],
                survivor_pairs[index][1],
                go,
                errors,
                survivor_gets,
                survivor_final,
                survivor_client_ids,
                survivor_owner_paths,
                handoff_seen,
                args.owner_max_slot,
            ),
            daemon=True,
        )
        for index in range(survivor_count)
    ]
    churners = [
        threading.Thread(
            target=_lifecycle_churn,
            name=f"lifecycle-churn-{index}",
            args=(
                index,
                args.port,
                timeout,
                go,
                errors,
                churn_connections,
                churn_commands,
            ),
            daemon=True,
        )
        for index in range(churn_threads)
    ]
    threads = [*survivors, *churners]
    for thread in threads:
        thread.start()

    attempts = 0
    refusals = 0
    accepted = 0
    run_deadline = time.monotonic() + args.seconds
    try:
        go.set()
        warm_deadline = min(run_deadline, time.monotonic() + timeout)
        wait_for(
            lambda: min(survivor_gets) > 0 and sum(churn_connections) > 0,
            warm_deadline,
            errors,
            "survivor reads and connection churn to begin",
        )

        with RespConnection(args.port, timeout, "lifecycle-controller") as control:
            # An accepted request can legitimately select only short-lived
            # churn sockets.  Retry completed/idle rebalance rounds until a
            # tracked survivor reports a changed owner; owner_paths retain a
            # transition even if a later round moves that socket back.
            while time.monotonic() < run_deadline and not handoff_seen.is_set():
                errors.check()
                attempts += 1
                try:
                    reply = control.command(b"DEBUG", b"TOMO-MODESHIFT", 6)
                    expect_status(
                        reply, b"OK", "lifecycle DEBUG TOMO-MODESHIFT 6"
                    )
                    accepted += 1
                except RespServerError as exc:
                    if b"modeshift 6 refused:" not in exc.payload:
                        raise
                    refusals += 1
                errors.stop.wait(0.25)
        if accepted == 0 and not args.allow_no_handoff:
            raise ConformanceError(
                "DEBUG TOMO-MODESHIFT 6 was never accepted "
                f"(attempts={attempts}, refusals={refusals})"
            )

        # Keep both populations active for the rest of the requested window.
        while time.monotonic() < run_deadline:
            errors.check()
            errors.stop.wait(min(0.05, run_deadline - time.monotonic()))
    finally:
        errors.stop.set()
        go.set()
        try:
            join_threads(
                threads,
                time.monotonic() + timeout + 5.0,
                errors,
                "lifecycle clients",
            )
        finally:
            for conn in survivor_connections:
                conn.close()
    errors.check()

    if accepted <= 0 and not args.allow_no_handoff:
        raise ConformanceError("client rebalance did not engage")
    if sum(churn_connections) <= 0 or sum(churn_commands) <= 0:
        raise ConformanceError("connection lifecycle churn completed zero work")
    if any(value is None for value in survivor_final) or any(
        count <= 0 for count in survivor_gets
    ):
        bad = [
            index
            for index, (count, final) in enumerate(
                zip(survivor_gets, survivor_final)
            )
            if count <= 0 or final is None
        ]
        raise ConformanceError(
            f"surviving connections did not all pass final fidelity: {bad}"
        )
    if any(client_id is None for client_id in survivor_client_ids) or any(
        not path for path in survivor_owner_paths
    ):
        raise ConformanceError(
            "one or more surviving sockets lack a CLIENT INFO identity/owner"
        )
    concrete_client_ids = [
        client_id
        for client_id in survivor_client_ids
        if client_id is not None
    ]
    if len(set(concrete_client_ids)) != survivor_count:
        raise ConformanceError(
            "CLIENT INFO did not return one unique id per surviving socket"
        )
    moved_survivors = [
        index
        for index, path in enumerate(survivor_owner_paths)
        if len(path) > 1
    ]
    if not moved_survivors and not args.allow_no_handoff:
        raise ConformanceError(
            "DEBUG TOMO-MODESHIFT 6 was accepted but no surviving socket "
            "reported a changed CLIENT INFO io-thread owner"
        )

    records = [
        (b"survivor", key, actual)
        for (key, _expected), actual in sorted(
            zip(survivor_pairs, survivor_final), key=lambda item: item[0][0]
        )
        if actual is not None
    ]
    emit_json(
        {
            "accepted": accepted,
            "allow_no_handoff": args.allow_no_handoff,
            "attempts": attempts,
            "case": "lifecycle",
            "churn_commands": sum(churn_commands),
            "churn_connections": sum(churn_connections),
            "churn_threads": churn_threads,
            "digest": canonical_digest(records),
            "disconnects": 0,
            "min_survivor_gets": min(survivor_gets),
            "moved_client_ids": [
                survivor_client_ids[index] for index in moved_survivors
            ],
            "moved_survivors": len(moved_survivors),
            "owner_paths": {
                str(survivor_client_ids[index]): ">".join(
                    str(owner) for owner in survivor_owner_paths[index]
                )
                for index in range(survivor_count)
            },
            "owner_slot_range": f"0..{args.owner_max_slot}",
            "profile": "quick" if args.quick else "full",
            "refusals": refusals,
            "stable_ids": True,
            "survivor_gets": sum(survivor_gets),
            "survivors": survivor_count,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Exact RESP2 helpers for the bigstress acceptance suite"
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    fidelity = subparsers.add_parser(
        "fidelity", help="concurrent exact SET/GET/MSET/MGET plus SCAN"
    )
    fidelity.add_argument("--port", type=int, required=True)
    fidelity.add_argument("--quick", action="store_true")
    fidelity.set_defaults(func=run_fidelity)

    migration = subparsers.add_parser(
        "migration", help="exact hot-range canaries under automatic key balancing"
    )
    migration.add_argument("--port", type=int, required=True)
    migration.add_argument("--seconds", type=float, required=True)
    migration.add_argument("--quick", action="store_true")
    migration.add_argument("--verify-only", action="store_true")
    migration.add_argument(
        "--ready-file",
        help=(
            "atomically create this marker after all exact GET workers have "
            "completed a full hot-domain sweep; it remains present during their "
            "sustained exact-GET interval"
        ),
    )
    migration.add_argument(
        "--selection-file",
        help=(
            "read an atomically published 'lo hi src dst' selection after "
            "traffic stops, and prove its canaries began on the logged source"
        ),
    )
    migration.add_argument(
        "--stop-file",
        help=(
            "stop sustained exact readers normally when this path is "
            "atomically created"
        ),
    )
    migration.add_argument("--moved-lo", type=int)
    migration.add_argument("--moved-hi", type=int)
    migration.add_argument("--moved-src", type=int)
    migration.add_argument("--moved-dst", type=int)
    migration.set_defaults(func=run_migration)

    lifecycle = subparsers.add_parser(
        "lifecycle", help="long-lived exact sockets under connect/disconnect churn"
    )
    lifecycle.add_argument("--port", type=int, required=True)
    lifecycle.add_argument("--seconds", type=float, required=True)
    lifecycle.add_argument("--owner-max-slot", type=int, required=True)
    lifecycle.add_argument("--quick", action="store_true")
    lifecycle.add_argument(
        "--allow-no-handoff",
        action="store_true",
        help="record exact lifecycle fidelity even when the topology has one IO owner",
    )
    lifecycle.set_defaults(func=run_lifecycle)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        xxh64_selftest()
        args.func(args)
    except KeyboardInterrupt:
        print("bigstress_client: interrupted", file=sys.stderr, flush=True)
        return 130
    except BaseException as exc:
        print(
            f"bigstress_client {args.subcommand}: FAIL: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
