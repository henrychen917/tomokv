#!/usr/bin/env python3
"""EX4.19: 1030 simultaneous clients on one witnessed IO owner, exact remote replies."""
import argparse
from contextlib import closing
import time
import _lib


def run(host, port):
    clients = []
    try:
        with closing(_lib.Conn(host, port)) as admin:
            assert admin.must("CONFIG", "GET", "client-lb") == [b"client-lb", b"0"]
            target = admin.must("DEBUG", "IO-THREAD")
            topo = _lib.topology(admin)
            # Fused must cross owners too: its self-completion route bypasses the channel.
            key = next(key for key, _, owner in _lib.probe_keys(admin, "slotless:remote", topo)
                       if owner != target)
            assert admin.must("SET", key, "remote-value") == b"OK"
            deadline = time.monotonic() + 45
            for attempt in range(30000):
                conn = _lib.Conn(host, port, timeout=5)
                if conn.must("DEBUG", "IO-THREAD") == target:
                    clients.append(conn)
                else:
                    conn.close()
                if len(clients) == 1030:
                    break
                assert time.monotonic() < deadline, "1030-client owner geometry never opened"
            assert len(clients) == 1030, "1030-client owner geometry never opened"
            for round_ in range(3):
                for index, conn in enumerate(clients):
                    marker = f"{round_}:{index}".encode()
                    conn.raw(_lib.encode("GET", key) + _lib.encode("ECHO", marker))
                for index, conn in enumerate(clients):
                    assert conn.read() == b"remote-value", (round_, index, "remote reply")
                    assert conn.read() == f"{round_}:{index}".encode(), (round_, index, "order")
            assert all(conn.must("DEBUG", "IO-THREAD") == target for conn in clients), "owner moved"
            print(f"PASS EX4.19 owner={target} simultaneous=1030 remote-owner GET/ECHO rounds=3")
    finally:
        for conn in clients:
            conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    run(args.host, args.port)
