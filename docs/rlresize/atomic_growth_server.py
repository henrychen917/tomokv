#!/usr/bin/env python3
"""Deterministic live-server reproduction of the rlresize abort (no timing window).

Boot the server armed fused (--thread-mode 1s --read-local 1 --atomic 1, debug commands on).
Owner maintenance is paused (DEBUG SET-ACTIVE-EXPIRE 0), so only this client's writes advance
shard 0's resize, and DEBUG REHASH-STATE reports shard 0's table after every step:

  1. plain SETs grow shard 0 and complete that ordinary resize: the boot reservation is consumed;
  2. plain SETs fill shard 0 to one key below its 70% trigger, without growing it;
  3. one cross-owner atomic MSET puts one new key on shard 0: its atomic preflight grows the table;
  4. plain SETs on shard 0 drive that resize to completion.

PRE loses the server at the completing step-4 SET (SIGABRT, missing resize retirement record).
POST completes the resize and every written key reads back. Exit 0 only for the POST outcome.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
import _lib  # noqa: E402

LOAD_PCT = 70


def state(conn):
    reply = conn.must("DEBUG", "REHASH-STATE")
    keys = ("shard", "rehashes", "capacity", "old_capacity", "cursor", "old_live", "size")
    return dict(zip(keys, reply))


def main():
    host, port = sys.argv[1], int(sys.argv[2])
    conn = _lib.Conn(host, port)
    topo = _lib.topology(conn)
    shard0_owner = topo.shard_owner[0]
    assert conn.must("DEBUG", "SET-ACTIVE-EXPIRE", "0") == b"OK"
    start = state(conn)
    assert start["shard"] == 0 and start["old_capacity"] == 0 and start["size"] == 0, start

    # Enough shard-0 keys for every phase (ordinary growth + fill + drive), plus one key whose
    # shard has a different owner, so the MSET takes the cross-owner atomic scatter path.
    shard0, other, index = [], None, 0
    want = 4 * start["capacity"] + 64
    while len(shard0) < want or other is None:
        batch = ["rlresize:%d" % (index + i) for i in range(256)]
        index += 256
        for key, (sid, owner) in zip(batch, _lib.shards_of(conn, batch)):
            if sid == 0:
                shard0.append(key)
            elif other is None and owner != shard0_owner:
                other = key
    keys = iter(shard0)
    written = []
    log = []

    def put():
        key = next(keys)
        assert conn.must("SET", key, key) == b"OK"
        written.append(key)
        return state(conn)

    # 1. Ordinary growth, then completion: the boot reservation is handed to the owner FIFO.
    current = start
    while current["old_capacity"] == 0:
        current = put()
    log.append(dict(phase="ordinary growth started", **current))
    while current["old_capacity"] != 0:
        current = put()
    log.append(dict(phase="ordinary growth completed (boot reservation consumed)", **current))

    # 2. Fill to one key below the 70% trigger. A plain insert grows at (size+1) >= 70%.
    cap = current["capacity"]
    while (current["size"] + 1) * 100 < cap * LOAD_PCT:
        current = put()
    assert current["old_capacity"] == 0 and current["capacity"] == cap, current
    log.append(dict(phase="filled to the trigger without growth", **current))

    # 3. One cross-owner atomic MSET: shard 0's group is one new key at the trigger.
    atomic_key = next(keys)
    assert conn.must("MSET", atomic_key, atomic_key, other, other) == b"OK"
    written.append(atomic_key)
    current = state(conn)
    assert current["old_capacity"] == cap and current["capacity"] == 2 * cap, current
    log.append(dict(phase="atomic MSET grew the table", **current))
    print(json.dumps(log, indent=1), flush=True)

    # 4. Drive the atomic resize to completion with plain SETs on shard 0.
    steps = 0
    try:
        while current["old_capacity"] != 0:
            current = put()
            steps += 1
    except (EOFError, ConnectionError) as exc:
        print("SERVER LOST at drive SET %d of %d (resize %d -> %d slots): %r"
              % (steps + 1, cap // 8, cap, 2 * cap, exc), flush=True)
        return 1
    log.append(dict(phase="atomic resize completed", drive_sets=steps, **current))
    for key in written:
        assert conn.must("GET", key) == key.encode(), key
    assert conn.must("GET", other) == other.encode()
    assert conn.must("DEBUG", "SET-ACTIVE-EXPIRE", "1") == b"OK"
    assert conn.must("PING") == b"PONG"
    print(json.dumps(log[-1]), flush=True)
    print("PASS atomic growth resize completed after %d drive SETs; %d keys read back"
          % (steps, len(written) + 1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
