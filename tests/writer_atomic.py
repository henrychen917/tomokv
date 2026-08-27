#!/usr/bin/env python3
"""Quiescent writer-atomicity stress detector for Redis-compatible servers.

Usage example:
    tests/writer_atomic.py 127.0.0.1 7040 --command mset --pattern full \
        --writers 16 --keys 128 --seconds 60 --tomokv-mode 0

The workload is portable RESP2.  TomoKV-only CONFIG/INFO checks are enabled only
when --tomokv-mode is supplied.  A test sample is taken only after every writer
has completed its in-flight command and acknowledged the pause.  The final
sample is taken after the writer threads have terminated and joined.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable


class ErrorReply:
    def __init__(self, message: bytes):
        self.message = message

    def __repr__(self) -> str:
        return f"ErrorReply({self.message!r})"


def encode(args: Iterable[Any]) -> bytes:
    args = list(args)
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        if not isinstance(arg, bytes):
            arg = str(arg).encode()
        out.extend((f"${len(arg)}\r\n".encode(), arg, b"\r\n"))
    return b"".join(out)


class Resp:
    def __init__(self, host: str, port: int, timeout: float = 30.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(timeout)
        self.file = self.sock.makefile("rb")

    def close(self) -> None:
        try:
            self.file.close()
        finally:
            self.sock.close()

    def command(self, *args: Any) -> Any:
        self.sock.sendall(encode(args))
        return self.read()

    def read(self) -> Any:
        prefix = self.file.read(1)
        if not prefix:
            raise EOFError("server closed the connection")
        line = self.file.readline()
        if not line.endswith(b"\r\n"):
            raise ValueError(f"invalid RESP line {prefix + line!r}")
        body = line[:-2]
        if prefix == b"+":
            return body
        if prefix == b"-":
            return ErrorReply(body)
        if prefix == b":":
            return int(body)
        if prefix == b"$":
            size = int(body)
            if size == -1:
                return None
            data = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise ValueError("invalid bulk-string trailer")
            return data
        if prefix == b"*":
            count = int(body)
            if count == -1:
                return None
            return [self.read() for _ in range(count)]
        if prefix == b"_":
            return None
        raise ValueError(f"unsupported RESP prefix {prefix!r}")


def printable(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "backslashreplace")
    if isinstance(value, ErrorReply):
        return {"error": printable(value.message)}
    if isinstance(value, list):
        return [printable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): printable(item) for key, item in value.items()}
    return value


def expect(reply: Any, wanted: Any, label: str) -> None:
    if reply != wanted:
        raise AssertionError(f"{label}: got {reply!r}, wanted {wanted!r}")


def info_stats(client: Resp) -> dict[str, int] | None:
    reply = client.command("INFO", "STATS")
    if not isinstance(reply, bytes):
        return None
    values: dict[str, int] = {}
    for line in reply.decode("utf-8", "replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        try:
            values[key] = int(value)
        except ValueError:
            pass
    return values


@dataclass(frozen=True)
class WriterSet:
    writer: int
    keys: tuple[str, ...]


def make_writer_sets(prefix: str, pattern: str, writers: int, key_count: int) -> list[WriterSet]:
    if pattern == "full":
        keys = tuple(f"{prefix}:k{i:05d}" for i in range(key_count))
        return [WriterSet(writer, keys) for writer in range(writers)]
    if pattern == "partial":
        shift = max(1, key_count // 2)
        left = tuple(f"{prefix}:k{i:05d}" for i in range(key_count))
        right = tuple(f"{prefix}:k{i:05d}" for i in range(shift, shift + key_count))
        return [WriterSet(writer, left if writer % 2 == 0 else right)
                for writer in range(writers)]
    if pattern == "disjoint":
        return [WriterSet(writer, tuple(
            f"{prefix}:w{writer:02d}:k{i:05d}" for i in range(key_count)))
                for writer in range(writers)]
    if pattern == "rotating":
        # Fixed cyclic windows, rotated by writer id.  Keeping each writer's window fixed across
        # generations lets the quiescent checker decide exact final-state serializability.  The
        # last window wraps and overlaps the first, so inconsistent owner order creates a cycle.
        shift = max(1, key_count // 2)
        universe = max(key_count + 1, shift * writers)
        names = [f"{prefix}:ring:{i:05d}" for i in range(universe)]
        sets = []
        for writer in range(writers):
            start = (writer * shift) % universe
            keys = tuple(names[(start + offset) % universe] for offset in range(key_count))
            sets.append(WriterSet(writer, keys))
        return sets
    raise AssertionError(f"unknown pattern {pattern}")


class EventLog:
    def __init__(self, writers: int):
        self.lock = threading.Lock()
        self.sequence = 0
        self.recent: collections.deque[dict[str, Any]] = collections.deque(maxlen=512)
        self.last_completed: list[dict[str, Any] | None] = [None] * writers
        self.writes = [0] * writers
        self.expected_sum = 0

    def event(self, kind: str, writer: int | None = None, **fields: Any) -> int:
        with self.lock:
            self.sequence += 1
            item = {"seq": self.sequence, "ns": time.monotonic_ns(), "kind": kind}
            if writer is not None:
                item["writer"] = writer
            item.update(fields)
            self.recent.append(item)
            return self.sequence

    def complete(self, writer: int, generation: int, issued_seq: int, effect: Any,
                 sum_delta: int = 0, **fields: Any) -> None:
        with self.lock:
            self.sequence += 1
            item = {
                "seq": self.sequence,
                "ns": time.monotonic_ns(),
                "kind": "complete",
                "writer": writer,
                "generation": generation,
                "issued_seq": issued_seq,
                "effect": printable(effect),
            }
            item.update(fields)
            self.recent.append(item)
            self.last_completed[writer] = dict(item)
            self.writes[writer] += 1
            self.expected_sum += sum_delta

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "sequence": self.sequence,
                "last_completed": [dict(item) if item is not None else None
                                   for item in self.last_completed],
                "writes": list(self.writes),
                "expected_sum": self.expected_sum,
                "recent": [dict(item) for item in self.recent],
            }


class PauseGate:
    def __init__(self, writers: int, events: EventLog):
        self.writers = writers
        self.events = events
        self.condition = threading.Condition()
        self.pause_requested = False
        self.stopping = False
        self.paused: set[int] = set()

    def before_command(self, writer: int) -> bool:
        with self.condition:
            while self.pause_requested and not self.stopping:
                if writer not in self.paused:
                    self.paused.add(writer)
                    self.events.event("pause_ack", writer)
                    self.condition.notify_all()
                self.condition.wait()
            self.paused.discard(writer)
            return not self.stopping

    def pause(self, timeout: float) -> tuple[bool, list[int]]:
        deadline = time.monotonic() + timeout
        with self.condition:
            self.pause_requested = True
            self.events.event("pause_request")
            self.condition.notify_all()
            while len(self.paused) != self.writers and not self.stopping:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False, sorted(self.paused)
                self.condition.wait(remaining)
            return len(self.paused) == self.writers, sorted(self.paused)

    def resume(self) -> None:
        with self.condition:
            self.events.event("resume")
            self.pause_requested = False
            self.paused.clear()
            self.condition.notify_all()

    def stop(self) -> None:
        with self.condition:
            self.events.event("stop_request")
            self.stopping = True
            self.pause_requested = False
            self.condition.notify_all()


def token(writer: int, generation: int) -> bytes:
    return f"w{writer:02d}:g{generation:012d}".encode()


def unique_keys(writer_sets: list[WriterSet]) -> list[str]:
    return sorted({key for writer_set in writer_sets for key in writer_set.keys})


def cover_map(writer_sets: list[WriterSet]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = collections.defaultdict(list)
    for writer_set in writer_sets:
        for key in writer_set.keys:
            out[key].append(writer_set.writer)
    return dict(out)


def find_cycle(edges: dict[int, dict[int, str]], writers: int) -> list[tuple[int, int, str]]:
    color = [0] * writers
    parent: list[tuple[int, str] | None] = [None] * writers

    def visit(node: int) -> list[tuple[int, int, str]]:
        color[node] = 1
        for target, key in edges.get(node, {}).items():
            if color[target] == 0:
                parent[target] = (node, key)
                found = visit(target)
                if found:
                    return found
            elif color[target] == 1:
                chain: list[tuple[int, int, str]] = [(node, target, key)]
                cursor = node
                while cursor != target:
                    previous, witness = parent[cursor]  # type: ignore[misc]
                    chain.append((previous, cursor, witness))
                    cursor = previous
                chain.reverse()
                return chain
        color[node] = 2
        return []

    for writer in range(writers):
        if color[writer] == 0:
            found = visit(writer)
            if found:
                return found
    return []


class Workload:
    def __init__(self, args: argparse.Namespace, admin: Resp, events: EventLog):
        self.args = args
        self.admin = admin
        self.events = events
        self.writer_sets = make_writer_sets(
            args.prefix, args.pattern, args.writers, args.keys)
        self.keys = unique_keys(self.writer_sets)
        self.covers = cover_map(self.writer_sets)
        self.rename_pairs: list[tuple[str, str]] = []
        self.setop_sources: list[list[str]] = []
        self.setop_destinations: list[str] = []
        self.setop_expected: list[Any] = []
        self.incr_keys: list[str] = []

    def setup(self) -> None:
        expect(self.admin.command("FLUSHDB"), b"OK", "FLUSHDB setup")
        command = self.args.command
        if command == "rename":
            if self.args.pattern not in ("full", "disjoint"):
                raise ValueError("RENAME supports full or disjoint patterns")
            for writer in range(self.args.writers):
                pair = ((f"{self.args.prefix}:rename:a", f"{self.args.prefix}:rename:b")
                        if self.args.pattern == "full" else
                        (f"{self.args.prefix}:rename:w{writer}:a",
                         f"{self.args.prefix}:rename:w{writer}:b"))
                self.rename_pairs.append(pair)
            for pair in sorted(set(self.rename_pairs)):
                expect(self.admin.command("SET", pair[0], "rename-origin"), b"OK", "RENAME seed")
                self.admin.command("DEL", pair[1])
        elif command in ("sunionstore", "zunionstore"):
            if self.args.pattern not in ("full", "disjoint"):
                raise ValueError("SETOP stores support full or disjoint patterns")
            for writer in range(self.args.writers):
                sources = [f"{self.args.prefix}:{command}:w{writer}:src{i:04d}"
                           for i in range(self.args.keys)]
                destination = (f"{self.args.prefix}:{command}:destination" if
                               self.args.pattern == "full" else
                               f"{self.args.prefix}:{command}:w{writer}:destination")
                self.setop_sources.append(sources)
                self.setop_destinations.append(destination)
                if command == "sunionstore":
                    expected_members = []
                    for index, source in enumerate(sources):
                        member = f"w{writer:02d}:m{index:04d}".encode()
                        reply = self.admin.command("SADD", source, member)
                        if isinstance(reply, ErrorReply):
                            raise RuntimeError(f"SUNIONSTORE unsupported during setup: {reply!r}")
                        expect(reply, 1, "SADD setup")
                        expected_members.append(member)
                    self.setop_expected.append(frozenset(expected_members))
                else:
                    expected_zset = {}
                    for index, source in enumerate(sources):
                        member = f"w{writer:02d}:m{index:04d}".encode()
                        score = index + 1
                        reply = self.admin.command("ZADD", source, score, member)
                        if isinstance(reply, ErrorReply):
                            raise RuntimeError(f"ZUNIONSTORE unsupported during setup: {reply!r}")
                        expect(reply, 1, "ZADD setup")
                        expected_zset[member] = float(score)
                    self.setop_expected.append(expected_zset)
        elif command == "incrby":
            self.incr_keys = ([f"{self.args.prefix}:counter"] * self.args.writers if
                              self.args.pattern != "disjoint" else
                              [f"{self.args.prefix}:counter:{writer}"
                               for writer in range(self.args.writers)])
            for key in sorted(set(self.incr_keys)):
                expect(self.admin.command("SET", key, 0), b"OK", "INCRBY seed")

    def one_write(self, client: Resp, writer: int, generation: int) -> tuple[Any, int, dict[str, Any]]:
        command = self.args.command
        keys = self.writer_sets[writer].keys
        value = token(writer, generation)
        if command == "mset":
            argv: list[Any] = ["MSET"]
            for key in keys:
                argv.extend((key, value))
            expect(client.command(*argv), b"OK", "MSET")
            return value, 0, {}
        if command == "multi-mset":
            expect(client.command("MULTI"), b"OK", "MULTI")
            argv = ["MSET"]
            for key in keys:
                argv.extend((key, value))
            expect(client.command(*argv), b"QUEUED", "queued MSET")
            expect(client.command("EXEC"), [b"OK"], "EXEC")
            return value, 0, {}
        if command == "del-mset":
            if writer % 2 == 0:
                reply = client.command("DEL", *keys)
                if not isinstance(reply, int):
                    raise AssertionError(f"DEL: got {reply!r}")
                return None, 0, {"role": "delete", "deleted": reply}
            argv = ["MSET"]
            for key in keys:
                argv.extend((key, value))
            expect(client.command(*argv), b"OK", "MSET interleave")
            return value, 0, {"role": "mset"}
        if command == "rename":
            left, right = self.rename_pairs[writer]
            first = (left, right) if generation % 2 else (right, left)
            reply = client.command("RENAME", *first)
            if isinstance(reply, ErrorReply):
                second = (first[1], first[0])
                reply = client.command("RENAME", *second)
                if isinstance(reply, ErrorReply):
                    return "no-source", 0, {"successful": False, "errors": 2}
                expect(reply, b"OK", "RENAME reverse")
                return "rename-origin", 0, {"successful": True, "source": second[0],
                                             "destination": second[1], "errors": 1}
            expect(reply, b"OK", "RENAME")
            return "rename-origin", 0, {"successful": True, "source": first[0],
                                         "destination": first[1], "errors": 0}
        if command == "sunionstore":
            destination = self.setop_destinations[writer]
            reply = client.command("SUNIONSTORE", destination, *self.setop_sources[writer])
            expect(reply, self.args.keys, "SUNIONSTORE")
            return f"set:w{writer}", 0, {"destination": destination}
        if command == "zunionstore":
            destination = self.setop_destinations[writer]
            reply = client.command("ZUNIONSTORE", destination, self.args.keys,
                                   *self.setop_sources[writer])
            expect(reply, self.args.keys, "ZUNIONSTORE")
            return f"zset:w{writer}", 0, {"destination": destination}
        if command == "incrby":
            delta = writer + 1
            reply = client.command("INCRBY", self.incr_keys[writer], delta)
            if not isinstance(reply, int):
                raise AssertionError(f"INCRBY: got {reply!r}")
            return reply, delta, {"key": self.incr_keys[writer], "delta": delta}
        raise AssertionError(f"unknown command {command}")

    def snapshot(self, client: Resp) -> Any:
        command = self.args.command
        if command in ("mset", "multi-mset", "del-mset"):
            values = client.command("MGET", *self.keys)
            if not isinstance(values, list) or len(values) != len(self.keys):
                raise AssertionError(f"MGET snapshot: got {values!r}")
            return dict(zip(self.keys, values))
        if command == "rename":
            pairs = sorted(set(self.rename_pairs))
            keys = sorted({key for pair in pairs for key in pair})
            values = client.command("MGET", *keys)
            if not isinstance(values, list) or len(values) != len(keys):
                raise AssertionError(f"RENAME MGET snapshot: got {values!r}")
            return dict(zip(keys, values))
        if command == "sunionstore":
            destinations = sorted(set(self.setop_destinations))
            return {destination: frozenset(client.command("SMEMBERS", destination) or [])
                    for destination in destinations}
        if command == "zunionstore":
            destinations = sorted(set(self.setop_destinations))
            result = {}
            for destination in destinations:
                reply = client.command("ZRANGE", destination, 0, -1, "WITHSCORES") or []
                if not isinstance(reply, list) or len(reply) % 2:
                    raise AssertionError(f"ZRANGE snapshot: got {reply!r}")
                result[destination] = {
                    reply[index]: float(reply[index + 1]) for index in range(0, len(reply), 2)
                }
            return result
        if command == "incrby":
            values = {}
            for key in sorted(set(self.incr_keys)):
                value = client.command("GET", key)
                values[key] = int(value) if value is not None else None
            return values
        raise AssertionError(f"unknown command {command}")

    def check_snapshot(self, observed: Any, state: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        command = self.args.command
        if command in ("mset", "multi-mset"):
            return self._check_tagged_values(observed, state)
        if command == "del-mset":
            return self._check_del_mset(observed, state)
        if command == "rename":
            bad = {}
            for pair in sorted(set(self.rename_pairs)):
                pair_values = {key: observed[key] for key in pair}
                present = [value for value in pair_values.values() if value is not None]
                if present != [b"rename-origin"]:
                    bad.update(pair_values)
            return not bad, {"reason": "RENAME pair does not contain exactly one origin",
                             "offending": printable(bad)} if bad else {}
        if command in ("sunionstore", "zunionstore"):
            bad = {}
            for destination, value in observed.items():
                candidates = [self.setop_expected[writer]
                              for writer, writer_destination in enumerate(self.setop_destinations)
                              if writer_destination == destination]
                if value not in candidates:
                    bad[destination] = printable(value)
            return not bad, {"reason": f"{command.upper()} destination is not one writer image",
                             "offending": bad} if bad else {}
        if command == "incrby":
            if self.args.pattern == "disjoint":
                expected = collections.defaultdict(int)
                for item in state["last_completed"]:
                    if item is not None:
                        expected[item["key"]] += item["delta"] * state["writes"][item["writer"]]
                # last_completed only carries the delta; every successful write by a writer uses
                # that same delta, so writes[] reconstructs the exact per-key sum.
                bad = {key: {"observed": value, "expected": expected[key]}
                       for key, value in observed.items() if value != expected[key]}
                return not bad, {"reason": "INCRBY disjoint sum mismatch", "offending": bad} if bad else {}
            wanted = state["expected_sum"]
            key = self.incr_keys[0]
            if observed[key] != wanted:
                return False, {"reason": "INCRBY exact sum mismatch",
                               "offending": {key: {"observed": observed[key],
                                                    "expected": wanted}}}
            return True, {}
        raise AssertionError(f"unknown command {command}")

    def detector_selftest(self) -> dict[str, bool]:
        """Exercise both detector polarities without relying on a server defect."""
        command = self.args.command
        fake = {
            "writes": [1] * self.args.writers,
            "expected_sum": 0,
            "last_completed": [
                {"writer": writer, "generation": 1, "key":
                 (self.incr_keys[writer] if self.incr_keys else ""), "delta": writer + 1}
                for writer in range(self.args.writers)
            ],
        }
        if command in ("mset", "multi-mset"):
            clean = {}
            for key, covering in self.covers.items():
                winner = max(covering)
                clean[key] = token(winner, 1)
            torn = dict(clean)
            common = set(self.writer_sets[0].keys)
            for writer_set in self.writer_sets[1:]:
                common.intersection_update(writer_set.keys)
            if len(common) >= 2:
                first, second = sorted(common)[:2]
                torn[first] = token(0, 1)
                torn[second] = token(1, 1)
            else:
                # Rotating windows may have no all-writer witness.  An old generation is still an
                # impossible final image because that writer's completed final write covers it.
                first = sorted(torn)[0]
                torn[first] = token(self.covers[first][0], 0)
        elif command == "del-mset":
            clean = {}
            for key, covering in self.covers.items():
                winner = max(covering)
                clean[key] = None if winner % 2 == 0 else token(winner, 1)
            torn = dict(clean)
            common = set(self.writer_sets[0].keys)
            for writer_set in self.writer_sets[1:]:
                common.intersection_update(writer_set.keys)
            if len(common) >= 2:
                first, second = sorted(common)[:2]
                torn[first] = None
                torn[second] = token(1, 1)
            else:
                first = sorted(torn)[0]
                torn[first] = b"impossible"
        elif command == "rename":
            clean = {key: None for pair in set(self.rename_pairs) for key in pair}
            for pair in set(self.rename_pairs):
                clean[pair[0]] = b"rename-origin"
            torn = dict(clean)
            first_pair = sorted(set(self.rename_pairs))[0]
            torn[first_pair[1]] = b"rename-origin"
        elif command in ("sunionstore", "zunionstore"):
            clean = {}
            for destination in set(self.setop_destinations):
                writer = self.setop_destinations.index(destination)
                clean[destination] = self.setop_expected[writer]
            torn = dict(clean)
            destination = sorted(torn)[0]
            torn[destination] = (frozenset((b"impossible",)) if command == "sunionstore"
                                 else {b"impossible": 1.0})
        elif command == "incrby":
            if self.args.pattern == "disjoint":
                clean = {self.incr_keys[writer]: writer + 1
                         for writer in range(self.args.writers)}
            else:
                clean = {key: 0 for key in set(self.incr_keys)}
            torn = dict(clean)
            torn[sorted(torn)[0]] = 1
        else:
            raise AssertionError(command)
        clean_ok, _ = self.check_snapshot(clean, fake)
        torn_ok, _ = self.check_snapshot(torn, fake)
        cycle_fired = bool(find_cycle({0: {1: "a"}, 1: {0: "b"}}, 2))
        cycle_control = not find_cycle({0: {1: "a"}}, 2)
        return {
            "clean_control_zero": clean_ok,
            "torn_positive_fired": not torn_ok,
            "cycle_positive_fired": cycle_fired,
            "cycle_control_zero": cycle_control,
        }

    def _check_tagged_values(self, observed: dict[str, bytes | None],
                             state: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        final_tokens: dict[int, bytes] = {}
        for writer, item in enumerate(state["last_completed"]):
            if item is None:
                return False, {"reason": f"writer {writer} completed no writes"}
            final_tokens[writer] = token(writer, item["generation"])

        edges: dict[int, dict[int, str]] = collections.defaultdict(dict)
        invalid = {}
        for key, value in observed.items():
            covering = self.covers[key]
            winners = [writer for writer in covering if final_tokens[writer] == value]
            if len(winners) != 1:
                invalid[key] = {
                    "observed": printable(value),
                    "candidates": [printable(final_tokens[writer]) for writer in covering],
                }
                continue
            winner = winners[0]
            for loser in covering:
                if loser != winner:
                    edges[loser][winner] = key
        if invalid:
            return False, {"reason": "key is not from the final write of any covering writer",
                           "offending": invalid}
        cycle = find_cycle(edges, self.args.writers)
        if cycle:
            offending = {}
            for before, after, key in cycle:
                offending[key] = {
                    "observed": printable(observed[key]),
                    "requires": f"writer {before} before writer {after}",
                }
            return False, {
                "reason": "no serial order can produce the stored key/value image",
                "cycle": [{"before": before, "after": after, "witness_key": key}
                          for before, after, key in cycle],
                "offending": offending,
            }
        return True, {}

    def _check_del_mset(self, observed: dict[str, bytes | None],
                        state: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        final_tokens = {}
        for writer, item in enumerate(state["last_completed"]):
            if item is None:
                return False, {"reason": f"writer {writer} completed no writes"}
            if writer % 2:
                final_tokens[writer] = token(writer, item["generation"])
        invalid = {}
        for key, value in observed.items():
            covering = self.covers[key]
            valid = value is None and any(writer % 2 == 0 for writer in covering)
            valid = valid or any(writer % 2 and final_tokens[writer] == value
                                 for writer in covering)
            if not valid:
                invalid[key] = printable(value)
        common = set(self.writer_sets[0].keys)
        for writer_set in self.writer_sets[1:]:
            common.intersection_update(writer_set.keys)
        common_values = {observed[key] for key in common}
        if len(common_values) > 1:
            invalid.update({key: printable(observed[key]) for key in sorted(common)})
        if invalid:
            return False, {
                "reason": "DEL/MSET common intersection is neither one complete value nor all nil",
                "offending": invalid,
            }
        if self.args.pattern == "disjoint":
            for writer_set in self.writer_sets:
                wanted = None if writer_set.writer % 2 == 0 else final_tokens[writer_set.writer]
                for key in writer_set.keys:
                    if observed[key] != wanted:
                        return False, {"reason": "disjoint DEL/MSET final write is incomplete",
                                       "offending": {key: printable(observed[key])}}
        return True, {}


def wait_atomic_drain(admin: Resp, timeout: float = 5.0) -> dict[str, int] | None:
    deadline = time.monotonic() + timeout
    latest = info_stats(admin)
    while latest is not None and time.monotonic() < deadline:
        if latest.get("atomic_inflight", 0) == 0 and latest.get("atomic_pending_entries", 0) == 0:
            return latest
        time.sleep(0.01)
        latest = info_stats(admin)
    return latest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--command", choices=("mset", "multi-mset", "del-mset", "rename",
                                               "sunionstore", "zunionstore", "incrby"),
                        default="mset")
    parser.add_argument("--pattern", choices=("full", "partial", "rotating", "disjoint"),
                        default="full")
    parser.add_argument("--writers", type=int, default=2)
    parser.add_argument("--keys", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--active-ms", type=float, default=100.0,
                        help="writer run time between quiescent probes")
    parser.add_argument("--settle-ms", type=float, default=10.0,
                        help="extra quiet time after every writer acknowledges the pause")
    parser.add_argument("--pause-timeout", type=float, default=30.0)
    parser.add_argument("--tomokv-mode", type=int, choices=(0, 1))
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--allow-short", action="store_true",
                        help="permit <60s cells for harness smoke/ASAN validation only")
    args = parser.parse_args()
    if not 2 <= args.writers <= 32:
        parser.error("--writers must be between 2 and 32")
    if not 1 <= args.keys <= 128:
        parser.error("--keys must be between 1 and 128")
    if args.command != "incrby" and args.keys < 2:
        parser.error("multi-key commands require --keys >= 2")
    if args.seconds < 60 and not args.allow_short:
        parser.error("campaign cells must run >=60s; use --allow-short only for validation")
    if args.active_ms <= 0 or args.settle_ms < 0:
        parser.error("probe timing must be positive")
    if args.command == "del-mset" and args.pattern == "rotating":
        parser.error("del-mset needs a common witness; rotating is unsupported")
    if args.command in ("rename", "sunionstore", "zunionstore") and args.pattern not in (
            "full", "disjoint"):
        parser.error(f"{args.command} supports full or disjoint patterns")
    if args.prefix is None:
        args.prefix = f"wstress:{os.getpid()}:{time.time_ns()}"
    return args


def main() -> int:
    args = parse_args()
    admin = Resp(args.host, args.port, timeout=max(30.0, args.pause_timeout))
    events = EventLog(args.writers)
    gate = PauseGate(args.writers, events)
    workload = Workload(args, admin, events)
    errors: list[str] = []
    errors_lock = threading.Lock()
    barrier = threading.Barrier(args.writers + 1)
    violations: list[dict[str, Any]] = []
    probe_count = 0
    drain_probe_count = 0
    pause_failures = 0
    started = time.monotonic()
    stats_before = None
    stats_after = None
    mode_value = None
    detector_selftest: dict[str, bool] = {}

    try:
        workload.setup()
        detector_selftest = workload.detector_selftest()
        if not all(detector_selftest.values()):
            raise AssertionError(f"detector self-test failed: {detector_selftest}")
        if args.tomokv_mode is not None:
            config = admin.command("CONFIG", "GET", "atomic")
            if not isinstance(config, list) or len(config) != 2:
                raise AssertionError(f"CONFIG GET atomic returned {config!r}")
            mode_value = int(config[1])
            if mode_value != args.tomokv_mode:
                raise AssertionError(
                    f"server atomic mode is {mode_value}, expected {args.tomokv_mode}")
            stats_before = info_stats(admin)
            if stats_before is None or "atomic_groups" not in stats_before:
                raise AssertionError("TomoKV INFO STATS lacks atomic_groups")

        def writer_main(writer: int) -> None:
            client = None
            generation = 0
            try:
                client = Resp(args.host, args.port, timeout=max(30.0, args.pause_timeout))
                barrier.wait(timeout=30)
                while gate.before_command(writer):
                    generation += 1
                    issued_seq = events.event("issue", writer, generation=generation)
                    effect, delta, fields = workload.one_write(client, writer, generation)
                    if args.command == "rename" and not fields.get("successful", False):
                        events.event("rename_no_source", writer, generation=generation)
                        continue
                    events.complete(writer, generation, issued_seq, effect, delta, **fields)
            except Exception as exc:  # report to the controller; never silently lose a writer
                with errors_lock:
                    errors.append(f"writer {writer}: {type(exc).__name__}: {exc}")
                gate.stop()
                try:
                    barrier.abort()
                except threading.BrokenBarrierError:
                    pass
            finally:
                if client is not None:
                    client.close()

        threads = [threading.Thread(target=writer_main, args=(writer,),
                                    name=f"writer-{writer}") for writer in range(args.writers)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=30)
        events.event("writers_started")
        deadline = time.monotonic() + args.seconds
        next_probe = time.monotonic() + args.active_ms / 1000.0
        while time.monotonic() < deadline and not errors:
            delay = min(next_probe - time.monotonic(), deadline - time.monotonic())
            if delay > 0:
                time.sleep(delay)
            if time.monotonic() >= deadline:
                break
            if errors:
                break
            paused, acknowledged = gate.pause(args.pause_timeout)
            if not paused:
                pause_failures += 1
                errors.append(f"pause timed out; acknowledgements={acknowledged}")
                gate.stop()
                break
            if args.settle_ms:
                time.sleep(args.settle_ms / 1000.0)
            state = events.snapshot()
            observed = workload.snapshot(admin)
            ok, detail = workload.check_snapshot(observed, state)
            probe_count += 1
            if not ok:
                violations.append({
                    "probe": probe_count,
                    "kind": "quiescent",
                    "elapsed_seconds": time.monotonic() - started,
                    "detail": detail,
                    "last_completed": state["last_completed"],
                    "writes": state["writes"],
                })
            gate.resume()
            next_probe = time.monotonic() + args.active_ms / 1000.0

        gate.stop()
        for thread in threads:
            thread.join(timeout=args.pause_timeout)
        alive = [thread.name for thread in threads if thread.is_alive()]
        if alive:
            errors.append(f"writer threads did not drain: {alive}")

        # A distinct final drain sample: all writers have terminated and their sockets are closed.
        state = events.snapshot()
        observed = workload.snapshot(admin)
        ok, detail = workload.check_snapshot(observed, state)
        drain_probe_count = 1
        if not ok:
            violations.append({
                "probe": probe_count + 1,
                "kind": "final-drain",
                "elapsed_seconds": time.monotonic() - started,
                "detail": detail,
                "last_completed": state["last_completed"],
                "writes": state["writes"],
            })

        if any(count == 0 for count in state["writes"]):
            errors.append(f"vacuous writer count: writes={state['writes']}")

        counter_checks: dict[str, Any] = {}
        if args.tomokv_mode is not None:
            stats_after = wait_atomic_drain(admin)
            if stats_after is None:
                errors.append("TomoKV INFO STATS disappeared")
            else:
                delta = stats_after["atomic_groups"] - stats_before["atomic_groups"]
                counter_checks = {
                    "configured_atomic": mode_value,
                    "atomic_groups_before": stats_before["atomic_groups"],
                    "atomic_groups_after": stats_after["atomic_groups"],
                    "atomic_groups_delta": delta,
                    "atomic_inflight_final": stats_after.get("atomic_inflight"),
                    "atomic_pending_entries_final": stats_after.get("atomic_pending_entries"),
                }
                grouped = args.command not in ("incrby",)
                force_grouped = args.command == "multi-mset"
                if args.tomokv_mode == 0 and grouped and not force_grouped and delta != 0:
                    errors.append(f"atomic_groups advanced by {delta} with atomic mode off")
                if (args.tomokv_mode == 1 and grouped or force_grouped) and delta <= 0:
                    errors.append("atomic group machinery did not fire")
                if stats_after.get("atomic_inflight") != 0:
                    errors.append(f"atomic_inflight did not drain: {stats_after.get('atomic_inflight')}")
                if stats_after.get("atomic_pending_entries") != 0:
                    errors.append("atomic_pending_entries did not drain: "
                                  f"{stats_after.get('atomic_pending_entries')}")

        elapsed = time.monotonic() - started
        result = {
            "status": "error" if errors else ("violation" if violations else "clean"),
            "host": args.host,
            "port": args.port,
            "command": args.command,
            "pattern": args.pattern,
            "writers": args.writers,
            "keys_per_write": args.keys,
            "requested_seconds": args.seconds,
            "elapsed_seconds": elapsed,
            "active_ms": args.active_ms,
            "settle_ms": args.settle_ms,
            "prefix": args.prefix,
            "quiescent_probes": probe_count,
            "final_drain_probes": drain_probe_count,
            "violations": len(violations),
            "violation_samples": violations,
            "writes_total": sum(state["writes"]),
            "writes_by_writer": state["writes"],
            "pause_failures": pause_failures,
            "errors": errors,
            "detector_selftest": detector_selftest,
            "tomokv": counter_checks,
        }
        rendered = json.dumps(result, sort_keys=True, separators=(",", ":"))
        print(
            "writer_atomic: "
            f"status={result['status']} command={args.command} pattern={args.pattern} "
            f"writers={args.writers} keys={args.keys} writes={result['writes_total']} "
            f"probes={probe_count}+{drain_probe_count} violations={len(violations)} "
            f"errors={len(errors)} elapsed={elapsed:.3f}s",
            flush=True,
        )
        for sample in violations[:8]:
            print("  violation:", json.dumps(sample, sort_keys=True), flush=True)
        if len(violations) > 8:
            print(f"  ... {len(violations) - 8} additional samples are in RESULT_JSON", flush=True)
        for error in errors:
            print(f"  error: {error}", flush=True)
        if counter_checks:
            print("  tomokv:", json.dumps(counter_checks, sort_keys=True), flush=True)
        print("RESULT_JSON " + rendered, flush=True)
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as output:
                output.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 2 if errors else (1 if violations else 0)
    finally:
        admin.close()


if __name__ == "__main__":
    sys.exit(main())
