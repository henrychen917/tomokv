#!/usr/bin/env python3
"""NET1 directed live witness; connects to a maintainer-started disposable server.

Requires --enable-debug-command yes --client-lb 0 and an empty requirepass.
No server is launched here. The 64 KiB incomplete window must open before the
1 MiB attack; a timeout, missing error, skipped owner match, or missing close fails.
"""
import argparse
from contextlib import closing
import statistics
import threading
import time

import _lib

INLINE_ERROR = b"ERR Protocol error: too big inline request"


def require(ok, label):
    if not ok:
        raise AssertionError(label)


def client_rows(admin):
    return {int(row[b"id"]): row for row in
            (dict(item.split(b"=", 1) for item in line.split())
             for line in admin.must("CLIENT", "LIST").splitlines())}


def wait_for(predicate, label):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(label)


def closed(conn, label):
    try:
        data = conn.file.read(1)
    except (ConnectionResetError, BrokenPipeError):
        data = b""
    require(data == b"", label + ": connection did not close silently: %r" % data)


def send_until_close(conn, payload):
    try:
        conn.raw(payload)
    except (BrokenPipeError, ConnectionResetError):
        pass  # The read-side oracle still requires the exact reply and/or close.


def ping_samples(admin, count):
    times = []
    for _ in range(count):
        begin = time.monotonic()
        require(admin.must("PING") == b"PONG", "same-owner second connection remains responsive")
        times.append(time.monotonic() - begin)
    return times


def inline_attack(admin, host, port):
    require(admin.must("CONFIG", "GET", "client-lb") == [b"client-lb", b"0"],
            "NET1 witness requires fixed client ownership (--client-lb 0)")
    require(admin.must("CONFIG", "GET", "requirepass") == [b"requirepass", b""],
            "NET1 witness requires a disposable server without a password")
    owner = admin.must("DEBUG", "IO-THREAD")
    victim = None
    for _ in range(128):
        candidate = _lib.Conn(host, port, timeout=3)
        if candidate.must("DEBUG", "IO-THREAD") == owner:
            victim = candidate
            break
        candidate.close()
    require(victim is not None, "NET1: bounded discovery found no same-owner connection")
    ident = victim.must("CLIENT", "ID")
    baseline = statistics.median(ping_samples(admin, 32))
    password = "netcap-directed-preauth"
    try:
        # Preserve the proven owner while RESET drops the victim's initial nopass auth.
        # Only the observer sends AUTH; the victim must witness NOAUTH before the attack.
        admin.must("CONFIG", "SET", "requirepass", password)
        admin.must("AUTH", password)
        require(victim.must("RESET") == b"RESET", "victim session reset")
        require(victim.cmd("PING") == _lib.RespError(b"NOAUTH Authentication required."),
                "NET1: victim must be unauthenticated")
        victim.raw(b"x" * 65536)
        wait_for(lambda: int(client_rows(admin).get(ident, {}).get(b"qbuf", b"-1")) == 65536,
                 "NET1: exact 64 KiB incomplete window never opened")
        during = ping_samples(admin, 32)
        failures = []
        started = threading.Event()

        def attack():
            started.set()
            try:
                send_until_close(victim, b"x" * ((1 << 20) - 65536))
                try:
                    error = victim.read()
                except (EOFError, OSError) as exc:
                    raise AssertionError("NET1: 1 MiB unterminated inline missing Redis error") from exc
                require(error == _lib.RespError(INLINE_ERROR),
                        "NET1: 1 MiB unterminated inline missing Redis error: %r" % error)
                closed(victim, "NET1: inline error must be followed by close")
            except BaseException as exc:
                failures.append(exc)

        worker = threading.Thread(target=attack)
        worker.start()
        require(started.wait(1), "inline sender did not start")
        during += ping_samples(admin, 64)
        worker.join(5)
        require(not worker.is_alive(), "NET1: inline sender did not finish")
        if failures:
            raise failures[0]
        wait_for(lambda: ident not in client_rows(admin), "NET1: closed client remained registered")
        require(admin.must("DEBUG", "IO-THREAD") == owner, "observer ownership changed")
        median = statistics.median(during)
        # Fixed correctness liveness band, not an optimisation verdict or an adaptive tolerance.
        require(median <= max(4 * baseline, 0.002),
                "NET1: second connection p50 exceeded fixed liveness band")
        print("PASS netcap inline preauth owner=%d p50_before=%.6f p50_during=%.6f closed_id=%d" %
              (owner, baseline, median, ident))
    finally:
        admin.must("CONFIG", "SET", "requirepass", "")
        victim.close()


def query_limit(admin, host, port):
    original = admin.must("CONFIG", "GET", "client-query-buffer-limit")
    require(original == [b"client-query-buffer-limit", b"1073741824"], "Redis 1 GiB default")
    pending = _lib.Conn(host, port, timeout=3)  # Exists before CONFIG SET publication.
    try:
        admin.must("CONFIG", "SET", "client-query-buffer-limit", "1mb")
        require(admin.must("CONFIG", "GET", "client-query-buffer-limit") ==
                [b"client-query-buffer-limit", b"1048576"], "live query limit GET")
        header = b"*2\r\n$4\r\nECHO\r\n$2097152\r\n"
        send_until_close(pending, header + b"x" * ((1 << 20) + 1))
        closed(pending, "NET1: query limit exceeded on existing connection")
        admin.must("CONFIG", "SET", "client-query-buffer-limit", "2mb")
        with closing(_lib.Conn(host, port, timeout=3)) as legal:
            value = b"y" * ((1 << 20) + 1)
            require(legal.must("ECHO", value) == value, "raised live query cap permits larger request")
        admin.must("CONFIG", "SET", "client-query-buffer-limit", "1mb")
        with closing(_lib.Conn(host, port, timeout=3)) as multi:
            require(multi.must("MULTI") == b"OK", "MULTI opened")
            require(multi.must("ECHO", b"q" * (768 << 10)) == b"QUEUED", "MULTI argv retained")
            send_until_close(multi, _lib.encode("ECHO", b"q" * (512 << 10)))
            closed(multi, "NET1: queued MULTI argv counted in query limit")
        require(admin.must("PING") == b"PONG", "observer survives query-limit closes")
        print("PASS netcap live query cap, raised cap, queued MULTI argv")
    finally:
        pending.close()
        admin.must("CONFIG", "SET", "client-query-buffer-limit", original[1])


def framing(host, port):
    for payload, message in (
        (b"*x\r\n", b"ERR Protocol error: invalid multibulk length"),
        (b"*1\r\n!\r\n", b"ERR Protocol error: expected '$', got '!'"),
        (b"*1\r\n$x\r\n", b"ERR Protocol error: invalid bulk length"),
    ):
        with closing(_lib.Conn(host, port, timeout=3)) as conn:
            conn.raw(payload)
            require(conn.read() == _lib.RespError(message), "Redis framing error text")
            closed(conn, "framing error must close")
    print("PASS netcap Redis framing errors")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    with closing(_lib.Conn(args.host, args.port, timeout=3)) as admin:
        inline_attack(admin, args.host, args.port)
        query_limit(admin, args.host, args.port)
        framing(args.host, args.port)
    print("PASS netcap live")


if __name__ == "__main__":
    main()
