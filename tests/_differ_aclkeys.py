"""ACL key extraction and witnessed blocking, on differential-harness-owned listeners."""
import select
import time

DENIED = b"-NOPERM No permissions to access a key\r\n"


def cases(timeout, key):
    """Timeouts are seconds for lists/zsets, milliseconds for streams."""
    return (
        (["BLPOP", key, timeout], [key], ["LPUSH", key, "value"]),
        (["BRPOP", key, timeout], [key], ["LPUSH", key, "value"]),
        (["BLMPOP", timeout, "1", key, "LEFT"], [key], ["LPUSH", key, "value"]),
        (["BZPOPMIN", key, timeout], [key], ["ZADD", key, "1", "value"]),
        (["XREAD", "BLOCK", timeout, "STREAMS", key, "0"], [key],
         ["XADD", key, "1-0", "field", "value"]),
    )


def wait_blocked(admin, blocked, client_id, issue, parse, read_reply, timeout=5.0):
    """An early NOPERM, missing client, or an unobserved window is a failure."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        if select.select([blocked[0]], [], [], 0)[0]:
            raise AssertionError("command replied before parking: %r" % read_reply(blocked[1]))
        last = parse(issue(admin, ["CLIENT", "LIST", "ID", str(client_id)]))
        assert isinstance(last, bytes), last
        rows = last.splitlines()
        assert len(rows) == 1, (client_id, last)
        fields = dict(item.split(b"=", 1) for item in rows[0].split())
        assert fields.get(b"id") == str(client_id).encode(), last
        assert b"flags" in fields, last
        if b"b" in fields[b"flags"] and time.monotonic() < deadline:
            return
        time.sleep(.001)
    raise AssertionError("client %s never parked: %r" % (client_id, last))


def run(api):
    enc, parse, read_reply = api["enc"], api["parse_reply"], api["read_reply"]
    endpoints = ((api["TH"], api["TP"]), (api["OH"], api["OP"]))
    opened = []
    counters = dict(admitted=0, denied=0, getkeys=0, parked=0)
    username = "aclkeys-differ"

    def connect(endpoint):
        pair = api["conn_mode"](*endpoint, False, buffering=0)
        pair[0].settimeout(5)
        opened.append(pair)
        return pair

    def issue(pair, args):
        api["coverage"].note(args)
        pair[0].sendall(enc(args))
        return read_reply(pair[1])

    def equal(pairs, args, expected=None):
        replies = [issue(pair, args) for pair in pairs]
        assert replies[0] == replies[1], (args, replies)
        if expected is not None:
            assert replies[0] == expected, (args, replies, expected)
        return replies[0]

    admins = [connect(endpoint) for endpoint in endpoints]
    workers = []
    try:
        info = parse(issue(admins[1], ["INFO", "SERVER"]))
        assert b"redis_version:7.4.10\r\n" in info, info
        equal(admins, ["ACL", "SETUSER", username, "reset", "on", "nopass",
                       "~block:*", "+@all"], b"+OK\r\n")
        workers = [connect(endpoint) for endpoint in endpoints]
        equal(workers, ["AUTH", username, "unused"], b"+OK\r\n")

        for timeout in ("0", "1"):
            for number, (args, keys, wake) in enumerate(cases(timeout, "block:aclkeys")):
                equal(admins, ["DEL", *keys])
                # Preseed: even XREAD BLOCK 1 (one millisecond) has an exact successful reply.
                # Admission therefore cannot pass by mistaking a timeout or early error for success.
                equal(admins, wake)
                expected_keys = b"*%d\r\n" % len(keys) + b"".join(
                    b"$%d\r\n%s\r\n" % (len(k.encode()), k.encode()) for k in keys)
                equal(admins, ["COMMAND", "GETKEYS", *args], expected_keys)
                counters["getkeys"] += 1
                reply = equal(workers, args)
                assert reply.startswith(b"*") and reply != b"*-1\r\n", (args, reply)
                assert b"value" in reply and keys[0].encode() in reply, (args, reply)
                counters["admitted"] += 1
                forbidden, badkeys, _ = cases(timeout, "outside:aclkeys")[number]
                bad_expected = b"*1\r\n$%d\r\n%s\r\n" % (
                    len(badkeys[0].encode()), badkeys[0].encode())
                equal(admins, ["COMMAND", "GETKEYS", *forbidden], bad_expected)
                counters["getkeys"] += 1
                equal(workers, forbidden, DENIED)
                counters["denied"] += 1
                equal(workers, ["PING"], b"+PONG\r\n")

        # All five commands must actually park and wake, not merely accept ready data.
        # The revoke/wake denial is the separate strict witness in acl.py.
        for args, keys, wake in cases("0", "block:aclkeys"):
            equal(admins, ["DEL", *keys])
            ids = [int(parse(issue(worker, ["CLIENT", "ID"]))[1:]) for worker in workers]
            for worker in workers:
                worker[0].sendall(enc(args))
            for admin, worker, client_id in zip(admins, workers, ids):
                wait_blocked(admin, worker, client_id, issue, parse, read_reply)
                counters["parked"] += 1
            equal(admins, wake)
            replies = [read_reply(worker[1]) for worker in workers]
            assert replies[0] == replies[1], (args, replies)
            assert b"value" in replies[0], (args, replies)
            # Require exactly one reply and an intact connection after completion.
            equal(workers, ["PING"], b"+PONG\r\n")
        assert counters == dict(admitted=10, denied=10, getkeys=20, parked=10), counters
        print("DIFFER aclkeys: PASS %s" % counters)
        return 0
    finally:
        # Close our blocked sockets before deleting our user on failure.
        for sock, file in reversed(opened[2:]):
            file.close()
            sock.close()
        for admin in admins:
            try:
                issue(admin, ["ACL", "DELUSER", username])
                issue(admin, ["DEL", "block:aclkeys"])
            finally:
                admin[1].close()
                admin[0].close()
