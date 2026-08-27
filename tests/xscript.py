#!/usr/bin/env python3
"""Directed cross-owner scripting battery. Usage: xscript.py HOST PORT [stage0]."""

import socket
import sys
import threading
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])
MODE = sys.argv[3] if len(sys.argv) > 3 else "all"
FAIL = 0


class RespError:
    def __init__(self, message):
        self.message = message

    def __repr__(self):
        return "RespError(%r)" % self.message


def frame(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return bytes(out)


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=30)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def close(self):
        self.file.close()
        self.sock.close()

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        marker = line[:1]
        if marker == b"+":
            return line[1:-2]
        if marker == b"-":
            return RespError(line[1:-2].decode(errors="replace"))
        if marker == b":":
            return int(line[1:-2])
        if marker == b"$":
            size = int(line[1:-2])
            if size == -1:
                return None
            value = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise ValueError("bad bulk trailer")
            return value
        if marker == b"*":
            count = int(line[1:-2])
            if count == -1:
                return None
            return [self.read() for _ in range(count)]
        raise ValueError("unsupported RESP marker %r" % marker)

    def cmd(self, *args):
        self.sock.sendall(frame(*args))
        return self.read()


def note(label, passed, detail=""):
    global FAIL
    print(("  ok   " if passed else "  FAIL ") + label +
          ((" " + detail) if detail else ""), flush=True)
    if not passed:
        FAIL += 1


def same_owner_pair(client):
    buckets = {}
    for index in range(4096):
        key = "xscript:watch:%d" % index
        owner = client.cmd("DEBUG", "SHARD", key)
        if not isinstance(owner, int):
            raise AssertionError("DEBUG SHARD is required, got %r" % (owner,))
        bucket = buckets.setdefault(owner, [])
        bucket.append(key)
        if len(bucket) == 2:
            return owner, bucket
    raise AssertionError("no same-owner key pair in 4096 candidates")


def geometry(client):
    by_owner = {}
    for index in range(20000):
        key = "xscript:key:%d" % index
        owner = client.cmd("DEBUG", "SHARD", key)
        if not isinstance(owner, int):
            raise AssertionError("DEBUG SHARD is required, got %r" % (owner,))
        by_owner.setdefault(owner, []).append(key)
        if len(by_owner) >= 8 and max(map(len, by_owner.values())) >= 8:
            break
    if len(by_owner) < 8:
        raise AssertionError("need eight distinct owners, found %r" % sorted(by_owner))
    distinct = [by_owner[owner][0] for owner in sorted(by_owner)[:8]]
    same = next(keys[:8] for keys in by_owner.values() if len(keys) >= 8)
    return distinct, same


def stats(client):
    raw = client.cmd("INFO", "STATS")
    if not isinstance(raw, bytes):
        raise AssertionError("INFO STATS returned %r" % (raw,))
    out = {}
    for line in raw.split(b"\r\n"):
        if b":" not in line:
            continue
        name, value = line.split(b":", 1)
        try:
            out[name.decode()] = int(value)
        except ValueError:
            pass
    return out


def cross_script(client, keys, values):
    source = ("local r={} for i=1,#KEYS do "
              "redis.call('SET',KEYS[i],ARGV[i]); r[i]=redis.call('GET',KEYS[i]) "
              "end return r")
    return client.cmd("EVAL", source, str(len(keys)), *keys, *values)


def watch_declared_keys_only():
    watcher, writer = Resp(), Resp()
    try:
        owner, (declared, argument) = same_owner_pair(writer)
        writer.cmd("DEL", declared, argument)

        quiet_ok = watcher.cmd("WATCH", argument) == b"OK"
        quiet_ok &= writer.cmd(
            "EVAL", "return redis.call('SET',KEYS[1],ARGV[1])",
            "1", declared, "value", argument) == b"OK"
        quiet_ok &= watcher.cmd("MULTI") == b"OK"
        quiet_ok &= watcher.cmd("GET", argument) == b"QUEUED"
        quiet = watcher.cmd("EXEC")
        quiet_ok &= quiet == [None]

        fired_ok = watcher.cmd("WATCH", declared) == b"OK"
        fired_ok &= writer.cmd(
            "EVAL", "return redis.call('SET',KEYS[1],ARGV[1])",
            "1", declared, "changed", argument) == b"OK"
        fired_ok &= watcher.cmd("MULTI") == b"OK"
        fired_ok &= watcher.cmd("GET", declared) == b"QUEUED"
        fired = watcher.cmd("EXEC")
        fired_ok &= fired is None

        note("WATCH ignores script ARGV on the same owner", quiet_ok,
             "owner=%d reply=%r" % (owner, quiet))
        note("WATCH detector fires for the script's declared key", fired_ok,
             "owner=%d reply=%r" % (owner, fired))
    finally:
        watcher.close()
        writer.close()


def core_semantics():
    admin = Resp()
    try:
        distinct, same = geometry(admin)
        admin.cmd("DEL", *(distinct + same))

        before = stats(admin)
        same_values = ["same:%d" % i for i in range(8)]
        same_reply = cross_script(admin, same, same_values)
        after_same = stats(admin)
        note("eight-key same-owner control stays local",
             same_reply == [value.encode() for value in same_values] and
             after_same.get("script_crossshard_activations", 0) ==
             before.get("script_crossshard_activations", 0),
             "cross_delta=%d" % (after_same.get("script_crossshard_activations", 0) -
                                  before.get("script_crossshard_activations", 0)))

        phase_before = stats(admin)
        for count in (2, 4, 8):
            keys = distinct[:count]
            values = ["value:%d:%d" % (count, i) for i in range(count)]
            reply = cross_script(admin, keys, values)
            observed = admin.cmd("MGET", *keys)
            note("%d-key cross-owner write/read" % count,
                 reply == [value.encode() for value in values] and observed == reply,
                 "owners=%r" % [admin.cmd("DEBUG", "SHARD", key) for key in keys])
        phase_after = stats(admin)
        required = ("script_stage_owner_tasks", "script_run_attempts",
                    "script_validate_owner_tasks", "script_apply_owner_tasks",
                    "script_crossshard_activations", "script_group_commits",
                    "script_staged_bytes_total")
        deltas = {name: phase_after.get(name, 0) - phase_before.get(name, 0)
                  for name in required}
        note("STAGE/RUN/VALIDATE/APPLY counters all fired",
             all(value > 0 for value in deltas.values()), repr(deltas))

        ryow = admin.cmd(
            "EVAL",
            "redis.call('SET',KEYS[1],'new-a'); redis.call('SET',KEYS[2],'new-b'); "
            "return {redis.call('GET',KEYS[2]),redis.call('GET',KEYS[1])}",
            "2", distinct[0], distinct[1])
        note("cross script reads its own writes", ryow == [b"new-b", b"new-a"], repr(ryow))

        admin.cmd("MSET", distinct[0], "old-a", distinct[1], "old-b")
        failed = admin.cmd(
            "EVAL", "redis.call('SET',KEYS[1],'kept'); error('after write')",
            "2", distinct[0], distinct[1])
        retained = admin.cmd("MGET", distinct[0], distinct[1])
        note("failed cross script keeps its prefix effects",
             isinstance(failed, RespError) and "after write" in failed.message and
             retained == [b"kept", b"old-b"],
             "error=%r values=%r" % (failed, retained))

        undeclared = "xscript:undeclared"
        admin.cmd("SET", undeclared, "secret")
        refused = admin.cmd(
            "EVAL", "return redis.call('GET',ARGV[1])", "2",
            distinct[0], distinct[1], undeclared)
        note("undeclared key remains an explicit refusal",
             isinstance(refused, RespError) and
             refused.message.startswith("ERR Script attempted to access an undeclared key"),
             repr(refused))

        # Exercise all six public script forms across the same proven-distinct geometry. The
        # read-only controls also prove they consume no commit ticket or APPLY work.
        pair = distinct[:2]
        sha_source = ("redis.call('SET',KEYS[1],ARGV[1]); "
                      "redis.call('SET',KEYS[2],ARGV[2]); "
                      "return {redis.call('GET',KEYS[1]),redis.call('GET',KEYS[2])}")
        sha = admin.cmd("SCRIPT", "LOAD", sha_source)
        evalsha = admin.cmd("EVALSHA", sha, "2", *pair, "sha-left", "sha-right")

        library = ("#!lua name=xscript_surface\n"
                   "redis.register_function{function_name='xscript_put2', "
                   "callback=function(keys,args) "
                   "redis.call('SET',keys[1],args[1]); "
                   "redis.call('SET',keys[2],args[2]); "
                   "return {redis.call('GET',keys[1]),redis.call('GET',keys[2])} end}\n"
                   "redis.register_function{function_name='xscript_get2', "
                   "callback=function(keys,args) "
                   "return {redis.call('GET',keys[1]),redis.call('GET',keys[2])} end, "
                   "flags={'no-writes'}}\n")
        loaded = admin.cmd("FUNCTION", "LOAD", "REPLACE", library)
        fcall = admin.cmd("FCALL", "xscript_put2", "2", *pair, "fn-left", "fn-right")
        note("EVALSHA and FCALL cross-owner write forms",
             isinstance(sha, bytes) and len(sha) == 40 and
             evalsha == [b"sha-left", b"sha-right"] and
             loaded == b"xscript_surface" and fcall == [b"fn-left", b"fn-right"],
             "evalsha=%r fcall=%r" % (evalsha, fcall))

        ro_source = "return {redis.call('GET',KEYS[1]),redis.call('GET',KEYS[2])}"
        ro_sha = admin.cmd("SCRIPT", "LOAD", ro_source)
        ro_before = stats(admin)
        eval_ro = admin.cmd("EVAL_RO", ro_source, "2", *pair)
        evalsha_ro = admin.cmd("EVALSHA_RO", ro_sha, "2", *pair)
        fcall_ro = admin.cmd("FCALL_RO", "xscript_get2", "2", *pair)
        ro_after = stats(admin)
        expected_ro = [b"fn-left", b"fn-right"]
        note("EVAL_RO, EVALSHA_RO, and FCALL_RO cross-owner forms",
             eval_ro == expected_ro and evalsha_ro == expected_ro and fcall_ro == expected_ro,
             "eval=%r evalsha=%r fcall=%r" % (eval_ro, evalsha_ro, fcall_ro))
        note("read-only cross scripts allocate no group ticket or APPLY wave",
             ro_after.get("script_crossshard_activations", 0) -
             ro_before.get("script_crossshard_activations", 0) == 3 and
             ro_after.get("script_group_commits", 0) ==
             ro_before.get("script_group_commits", 0) and
             ro_after.get("script_apply_owner_tasks", 0) ==
             ro_before.get("script_apply_owner_tasks", 0) and
             ro_after.get("script_validate_owner_tasks", 0) ==
             ro_before.get("script_validate_owner_tasks", 0),
             "activation=+%d commits=+%d apply=+%d validate=+%d" % (
                 ro_after.get("script_crossshard_activations", 0) -
                 ro_before.get("script_crossshard_activations", 0),
                 ro_after.get("script_group_commits", 0) -
                 ro_before.get("script_group_commits", 0),
                 ro_after.get("script_apply_owner_tasks", 0) -
                 ro_before.get("script_apply_owner_tasks", 0),
                 ro_after.get("script_validate_owner_tasks", 0) -
                 ro_before.get("script_validate_owner_tasks", 0)))

        # Stage 1 deliberately leaves nested composition to the next reviewable commit.
        admin.cmd("DEL", *pair)
        queued = admin.cmd("MULTI") == b"OK"
        queued &= admin.cmd("EVAL", "return redis.call('MSET',KEYS[1],'x',KEYS[2],'y')",
                            "2", *pair) == b"QUEUED"
        nested = admin.cmd("EXEC")
        note("Stage-1 cross script inside MULTI is explicitly refused",
             queued and len(nested) == 1 and isinstance(nested[0], RespError) and
             nested[0].message == "CROSSSLOT Keys in request don't hash to the same slot" and
             admin.cmd("MGET", *pair) == [None, None], repr(nested))
    finally:
        admin.close()


def contention_and_deadlock():
    admin = Resp()
    distinct, _ = geometry(admin)
    keys = distinct[:4]
    admin.cmd("DEL", *keys)
    admin.cmd("MSET", *sum(([key, "0"] for key in keys), []))
    before = stats(admin)
    errors = []
    successes = [0, 0]
    source = "for i=1,#KEYS do redis.call('INCR',KEYS[i]) end return 1"

    def worker(slot, ordered):
        client = Resp()
        try:
            while successes[slot] < 40:
                reply = client.cmd("EVAL", source, str(len(ordered)), *ordered)
                if reply == 1:
                    successes[slot] += 1
                elif isinstance(reply, RespError) and reply.message.startswith("TRYAGAIN "):
                    continue
                else:
                    errors.append((slot, reply))
                    return
        finally:
            client.close()

    threads = [threading.Thread(target=worker, args=(0, keys)),
               threading.Thread(target=worker, args=(1, list(reversed(keys))))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    alive = [thread.name for thread in threads if thread.is_alive()]
    values = admin.cmd("MGET", *keys)
    after = stats(admin)
    retry_delta = after.get("script_group_occ_retries", 0) - \
        before.get("script_group_occ_retries", 0)
    note("opposite-order overlapping scripts terminate without deadlock",
         not alive and not errors and successes == [40, 40] and
         values == [b"80"] * len(keys),
         "success=%r alive=%r errors=%r values=%r" %
         (successes, alive, errors[:2], values))
    note("contention detector forced at least one OCC restart", retry_delta > 0,
         "retries=+%d" % retry_delta)

    # The plain multi-key writer is deliberately a second connection. While script intents are
    # live its fragments must be promoted into one atomic group even on an --atomic=0 boot; the
    # final generation can be either writer's, but never a mix.
    script_writer = Resp()
    mset_writer = Resp()
    race_errors = []
    script_source = "for i=1,#KEYS do redis.call('SET',KEYS[i],ARGV[1]) end return 1"

    def script_racer():
        for _ in range(80):
            while True:
                reply = script_writer.cmd("EVAL", script_source, str(len(keys)), *keys, "S")
                if reply == 1:
                    break
                if isinstance(reply, RespError) and reply.message.startswith("TRYAGAIN "):
                    continue
                race_errors.append(("script", reply))
                return

    def mset_racer():
        command = [item for key in keys for item in (key, "M")]
        for _ in range(80):
            reply = mset_writer.cmd("MSET", *command)
            if reply != b"OK":
                race_errors.append(("mset", reply))
                return

    racers = [threading.Thread(target=script_racer), threading.Thread(target=mset_racer)]
    for thread in racers:
        thread.start()
    for thread in racers:
        thread.join(20)
    race_alive = [thread.name for thread in racers if thread.is_alive()]
    raced_values = admin.cmd("MGET", *keys)
    note("cross script and plain MSET serialize without a torn generation",
         not race_alive and not race_errors and
         raced_values in ([b"S"] * len(keys), [b"M"] * len(keys)),
         "alive=%r errors=%r values=%r" % (race_alive, race_errors[:2], raced_values))
    script_writer.close()
    mset_writer.close()
    admin.close()


def maxmemory_pressure():
    client = Resp()
    try:
        distinct, _ = geometry(client)
        keys = distinct[:2]
        client.cmd("CONFIG", "SET", "maxmemory", "0")
        client.cmd("CONFIG", "SET", "maxmemory-policy", "noeviction")
        client.cmd("FLUSHALL")

        before_control = stats(client)
        control = client.cmd(
            "EVAL", "redis.call('SET',KEYS[1],'control-a'); "
                    "redis.call('SET',KEYS[2],'control-b'); return 1",
            "2", *keys)
        after_control = stats(client)
        note("maxmemory negative control commits below pressure",
             control == 1 and client.cmd("MGET", *keys) == [b"control-a", b"control-b"] and
             after_control.get("script_group_commits", 0) ==
             before_control.get("script_group_commits", 0) + 1,
             "reply=%r commits=+%d" % (
                 control, after_control.get("script_group_commits", 0) -
                 before_control.get("script_group_commits", 0)))

        client.cmd("MSET", keys[0], "old-a", keys[1], "old-b")
        client.cmd("CONFIG", "SET", "maxmemory", "1048576")
        filler = b"F" * 4096
        oom = None
        filled = 0
        target_owner = client.cmd("DEBUG", "SHARD", keys[0])
        for index in range(20000):
            filler_key = "xscript:oom:%d" % index
            if client.cmd("DEBUG", "SHARD", filler_key) != target_owner:
                continue
            reply = client.cmd("SET", filler_key, filler)
            if isinstance(reply, RespError):
                oom = reply
                break
            filled += 1
        before = stats(client)
        refused = client.cmd(
            "EVAL", "redis.call('SET',KEYS[1],ARGV[1]); "
                    "redis.call('SET',KEYS[2],ARGV[1]); return 1",
            "2", *keys, b"Y" * 8192)
        values = client.cmd("MGET", *keys)
        after = stats(client)
        note("noeviction pressure detector reaches exact OOM",
             isinstance(oom, RespError) and
             oom.message == "OOM command not allowed when used memory > 'maxmemory'." and
             filled > 0, "owner=%r filled=%d reply=%r" % (target_owner, filled, oom))
        note("cross-script APPLY OOM aborts atomically and preserves predecessors",
             isinstance(refused, RespError) and
             refused.message == "OOM command not allowed when used memory > 'maxmemory'." and
             values == [b"old-a", b"old-b"] and
             after.get("script_group_aborts_oom", 0) ==
             before.get("script_group_aborts_oom", 0) + 1,
             "reply=%r value_lengths=%r aborts=+%d" % (
                 refused, [len(value) if isinstance(value, bytes) else None for value in values],
                 after.get("script_group_aborts_oom", 0) -
                 before.get("script_group_aborts_oom", 0)))
    finally:
        client.cmd("CONFIG", "SET", "maxmemory", "0")
        client.cmd("FLUSHALL")
        client.close()


def feature_off_control():
    client = Resp()
    try:
        distinct, same = geometry(client)
        before = stats(client)
        refused = client.cmd("EVAL", "return {KEYS[1],KEYS[2]}", "2",
                             distinct[0], distinct[1])
        local = client.cmd("EVAL", "return {KEYS[1],KEYS[2]}", "2", same[0], same[1])
        after = stats(client)
        counters = ("script_stage_owner_tasks", "script_run_attempts",
                    "script_validate_owner_tasks", "script_apply_owner_tasks",
                    "script_crossshard_activations")
        deltas = {name: after.get(name, 0) - before.get(name, 0) for name in counters}
        note("feature-off cross-owner refusal is byte-exact",
             isinstance(refused, RespError) and
             refused.message == "CROSSSLOT Keys in request don't hash to the same slot",
             repr(refused))
        note("feature-off same-owner scripts remain available",
             local == [same[0].encode(), same[1].encode()], repr(local))
        note("feature-off control allocates/executes no cross engine", all(v == 0 for v in deltas.values()),
             repr(deltas))
    finally:
        client.close()


def staging_limit_control():
    client = Resp()
    try:
        distinct, _ = geometry(client)
        keys = distinct[:2]
        client.cmd("DEL", *keys)
        before = stats(client)
        small = client.cmd("EVAL", "return #KEYS", "2", *keys)
        client.cmd("MSET", keys[0], "A" * 200, keys[1], "B" * 200)
        refused = client.cmd(
            "EVAL", "redis.call('SET',KEYS[1],'changed'); return 1", "2", *keys)
        values = client.cmd("MGET", *keys)
        after = stats(client)
        note("staging budget negative control succeeds below the cap", small == 2, repr(small))
        note("staging budget fires before RUN and preserves values",
             isinstance(refused, RespError) and
             refused.message == "ERR cross-shard script staging limit exceeded" and
             values == [b"A" * 200, b"B" * 200] and
             after.get("script_group_aborts_oom", 0) ==
             before.get("script_group_aborts_oom", 0) + 1,
             "reply=%r aborts=+%d" %
             (refused, after.get("script_group_aborts_oom", 0) -
              before.get("script_group_aborts_oom", 0)))
    finally:
        client.close()


watch_declared_keys_only()

if MODE not in ("stage0", "all", "off", "limit"):
    raise SystemExit("unknown xscript battery mode %r" % MODE)
if MODE == "all":
    core_semantics()
    contention_and_deadlock()
    maxmemory_pressure()
elif MODE == "off":
    feature_off_control()
elif MODE == "limit":
    staging_limit_control()
if FAIL:
    raise SystemExit("%d xscript checks failed" % FAIL)
print("XSCRIPT %s directed battery passed" % MODE, flush=True)
