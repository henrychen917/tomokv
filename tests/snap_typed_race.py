"""Exact typed-snapshot ticket oracle.

Usage:
  snap_typed_race.py PORT race  /path/to/race.tomo
  snap_typed_race.py PORT verify /path/to/race.tomo.oracle.json

The race arm leaves the target-cut image at ``race.tomo.cut`` and its oracle at
``race.tomo.oracle.json``.  The caller must restart from the former and pass the latter to verify.

Ordinary HSET/ZADD/RPUSH writes do not necessarily receive commit tickets, so they cannot be
classified against INFO snapshot_cut_ticket.  This test puts every classified typed mutation in a
cross-owner MULTI/EXEC instead.  A transaction publishes exactly one ticket.  The groups are sent
sequentially on one connection, with each EXEC reply consumed before the next MULTI is sent.

An empty SAVE first latches baseline B.  G successful pre-cut EXECs must therefore own tickets
B+1..B+G, which is checked by the target BGSAVE reporting cut C == B+G.  After G successful
post-cut EXECs, the completed target file is copied aside and a final SAVE must report D == C+G.
There are no other ticket-producing commands in between.  Thus each typed value's ticket is known,
not inferred from wall-clock timing.  The JSON sidecar persists B/C/D and the geometry needed to
audit that proof after restart.
"""

import json
import os
import shutil
import socket
import sys
import time


PORT = int(sys.argv[1])
MODE = sys.argv[2]
N = 4000
# 3 witness/metadata writes + 3 typed writes per row, plus MULTI and EXEC. Sixteen keeps the
# complete 53-frame transaction below Rob<64>'s window while still mutating the 2,000 keys in only
# 125 sequential ticket groups.
GROUP_WIDTH = 16
MUTATED = list(range(0, N, 2))
GROUPS = len(MUTATED) // GROUP_WIDTH


def enc(args):
    out = b"*%d\r\n" % len(args)
    for arg in args:
        arg = arg.encode() if isinstance(arg, str) else arg
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return out


class C:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.f = self.s.makefile("rb")

    def rr(self):
        line = self.f.readline()
        if not line:
            raise EOFError("server closed the connection")
        kind = line[:1]
        if kind in b"+-:":
            return line.strip()
        if kind == b"$":
            size = int(line[1:-2])
            return None if size == -1 else self.f.read(size + 2)[:-2]
        if kind == b"*":
            size = int(line[1:-2])
            return None if size == -1 else [self.rr() for _ in range(size)]
        raise AssertionError("malformed RESP line %r" % line[:80])

    def cmd(self, *args):
        self.s.sendall(enc(list(args)))
        return self.rr()

    def pipeline(self, commands):
        self.s.sendall(b"".join(enc(command) for command in commands))
        return [self.rr() for _ in commands]


def resp_int(value, context):
    if not isinstance(value, bytes) or not value.startswith(b":"):
        raise AssertionError("%s: expected integer reply, got %r" % (context, value))
    return int(value[1:])


def require_reply(actual, expected, context):
    if actual != expected:
        raise AssertionError("%s: expected %r, got %r" % (context, expected, actual))


def info_int(client, field):
    payload = client.cmd("INFO", "PERSISTENCE")
    if not isinstance(payload, bytes):
        raise AssertionError("INFO PERSISTENCE returned %r" % (payload,))
    prefix = field.encode() + b":"
    for line in payload.split(b"\r\n"):
        if line.startswith(prefix):
            return int(line[len(prefix):])
    raise AssertionError("INFO PERSISTENCE has no %s" % field)


def geometry(client):
    candidates = ["snapshot:ticket:witness:%d" % i for i in range(256)]
    reply = client.cmd("DEBUG", "SHARDS", *candidates)
    if not isinstance(reply, list) or len(reply) != len(candidates):
        raise AssertionError(
            "DEBUG SHARDS unavailable; boot with --enable-debug-command yes: %r" % (reply,))
    parsed = []
    for key, row in zip(candidates, reply):
        if not isinstance(row, list) or len(row) != 2:
            raise AssertionError("DEBUG SHARDS malformed row for %s: %r" % (key, row))
        parsed.append((key, resp_int(row[0], "shard id"), resp_int(row[1], "owner tid")))
    for left in parsed:
        for right in parsed:
            if left[2] != right[2]:
                return left, right
    raise AssertionError("ticket oracle needs at least two shard owners; rows=%r" % (parsed[:8],))


def ticket_tag(phase, ticket):
    return "%s-ticket-%d" % (phase, ticket)


def exec_typed_group(client, phase, group, ticket, witnesses):
    """Execute one typed mutation group and wait for its one ticket to be published."""
    tag = ticket_tag(phase, ticket)
    commands = [
        ["SET", witnesses[0], "%s-a" % tag],
        ["SET", witnesses[1], "%s-b" % tag],
        ["SET", "snapshot:ticket:%s:%d" % (phase, group), str(ticket)],
    ]
    first = group * GROUP_WIDTH
    for index in MUTATED[first:first + GROUP_WIDTH]:
        commands.extend((
            ["HSET", "H%d" % index, "f1", tag],
            ["ZADD", "Z%d" % index, "7.25" if phase == "pre" else "9.9", tag],
            ["RPUSH", "L%d" % index, tag],
        ))

    client.s.sendall(enc(["MULTI"]) + b"".join(enc(command) for command in commands) +
                     enc(["EXEC"]))
    require_reply(client.rr(), b"+OK", "%s group %d MULTI" % (phase, group))
    for command in commands:
        require_reply(client.rr(), b"+QUEUED",
                      "%s group %d queue %s" % (phase, group, command[0]))
    result = client.rr()
    if not isinstance(result, list) or len(result) != len(commands):
        raise AssertionError("%s group %d EXEC returned %r" % (phase, group, result))
    errors = [item for item in result if isinstance(item, bytes) and item.startswith(b"-")]
    if errors:
        raise AssertionError("%s group %d EXEC errors: %r" % (phase, group, errors[:3]))


def seed_typed_dataset(client):
    for start in range(0, N, 200):
        stop = min(start + 200, N)
        commands = [["HSET", "H%d" % index, "f1", "A" * 300, "f2", "B" * 300]
                    for index in range(start, stop)]
        commands += [["ZADD", "Z%d" % index, "1.5", "m" + "C" * 200,
                     "2.5", "n" + "D" * 200] for index in range(start, stop)]
        commands += [["RPUSH", "L%d" % index] + ["e" + "E" * 100] * 5
                     for index in range(start, stop)]
        replies = client.pipeline(commands)
        errors = [reply for reply in replies
                  if isinstance(reply, bytes) and reply.startswith(b"-")]
        if errors:
            raise AssertionError("typed seed errors: %r" % errors[:3])


def wait_for_snapshot(client, timeout=120):
    deadline = time.time() + timeout
    while info_int(client, "rdb_bgsave_in_progress") != 0:
        if time.time() >= deadline:
            raise AssertionError("BGSAVE did not finish within %ds" % timeout)
        time.sleep(0.05)


def write_oracle(path, state):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as output:
        json.dump(state, output, sort_keys=True, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def race(source_dump):
    client = C(PORT)
    cut_dump = source_dump + ".cut"
    oracle_path = source_dump + ".oracle.json"
    if client.cmd("CONFIG", "GET", "atomic") != [b"atomic", b"0"]:
        raise AssertionError("ticket oracle must exercise forced EXEC admission at atomic=0")
    if client.cmd("CONFIG", "GET", "save") != [b"save", b""]:
        raise AssertionError("ticket oracle needs --save '' so no cron snapshot can replace its cut")
    left, right = geometry(client)
    witnesses = [left[0], right[0]]
    if left[2] == right[2]:
        raise AssertionError("witnesses unexpectedly share owner %d" % left[2])

    # Establish B before any classified transaction. This snapshot is empty, so the additional
    # blocking save adds negligible work while avoiding an assumption that a fresh boot starts at
    # ticket zero.
    require_reply(client.cmd("SAVE"), b"+OK", "baseline SAVE")
    baseline = info_int(client, "snapshot_cut_ticket")
    baseline_file = os.stat(source_dump)
    seed_typed_dataset(client)  # ordinary writes; deliberately not part of the ticket oracle

    for group in range(GROUPS):
        exec_typed_group(client, "pre", group, baseline + group + 1, witnesses)

    preimages_before = info_int(client, "snapshot_preimages")
    reply = client.cmd("BGSAVE")
    if reply != b"+Background saving started":
        raise AssertionError("target BGSAVE returned %r" % (reply,))
    cut = info_int(client, "snapshot_cut_ticket")
    if cut != baseline + GROUPS:
        raise AssertionError(
            "pre-cut ticket bracket failed: baseline=%d groups=%d cut=%d" %
            (baseline, GROUPS, cut))

    # BGSAVE does not reply until Freeze has latched C. These groups are sequential and therefore
    # own C+1..C+G even though their physical snapshot preimages race the background traversal.
    for group in range(GROUPS):
        exec_typed_group(client, "post", group, cut + group + 1, witnesses)

    if info_int(client, "snapshot_cut_ticket") != cut:
        raise AssertionError("snapshot_cut_ticket changed while the target capture was active")
    wait_for_snapshot(client)
    if info_int(client, "snapshot_cut_ticket") != cut:
        raise AssertionError("snapshot_cut_ticket did not remain latched after target BGSAVE")
    target_file = os.stat(source_dump)
    if ((target_file.st_dev, target_file.st_ino) ==
            (baseline_file.st_dev, baseline_file.st_ino)):
        raise AssertionError("target BGSAVE did not replace the baseline snapshot file")
    preimages = info_int(client, "snapshot_preimages") - preimages_before
    if preimages <= 0:
        raise AssertionError("snapshot preimage path never fired")

    # Preserve the target image before the closing SAVE overwrites dbfilename. That SAVE is an
    # observation point: its cut proves that the G post groups consumed exactly C+1..C+G.
    shutil.copyfile(source_dump, cut_dump)
    if os.path.getsize(cut_dump) != target_file.st_size:
        raise AssertionError("target snapshot copy has the wrong size")
    require_reply(client.cmd("SAVE"), b"+OK", "closing SAVE")
    closing = info_int(client, "snapshot_cut_ticket")
    if closing != cut + GROUPS:
        raise AssertionError(
            "post-cut ticket bracket failed: cut=%d groups=%d closing=%d" %
            (cut, GROUPS, closing))

    state = {
        "version": 1,
        "baseline_cut_ticket": baseline,
        "snapshot_cut_ticket": cut,
        "closing_cut_ticket": closing,
        "pre_ticket_range": [baseline + 1, cut],
        "post_ticket_range": [cut + 1, closing],
        "groups": GROUPS,
        "group_width": GROUP_WIDTH,
        "nkeys": N,
        "mutated_indices": MUTATED,
        "witnesses": [
            {"key": left[0], "shard": left[1], "owner_tid": left[2]},
            {"key": right[0], "shard": right[1], "owner_tid": right[2]},
        ],
        "cut_dump": os.path.basename(cut_dump),
        "rule": "pre_ticket <= snapshot_cut_ticket < post_ticket",
        "snapshot_preimages_delta": preimages,
    }
    write_oracle(oracle_path, state)
    print("TICKET BRACKET baseline=%d cut=%d closing=%d groups=%d owners=%d,%d" %
          (baseline, cut, closing, GROUPS, left[2], right[2]))
    print("PREIMAGE-FIRED PASS (delta=%d)" % preimages)
    print("SNAPSHOT-TICKET-ORACLE PASS")


def verify(oracle_path):
    with open(oracle_path, "r", encoding="utf-8") as source:
        state = json.load(source)
    if state.get("version") != 1:
        raise AssertionError("unsupported oracle version %r" % state.get("version"))
    baseline = int(state["baseline_cut_ticket"])
    cut = int(state["snapshot_cut_ticket"])
    closing = int(state["closing_cut_ticket"])
    groups = int(state["groups"])
    width = int(state["group_width"])
    indices = list(state["mutated_indices"])
    if (groups != GROUPS or width != GROUP_WIDTH or int(state["nkeys"]) != N or
            indices != MUTATED):
        raise AssertionError("oracle geometry does not match this test revision")
    if cut != baseline + groups or closing != cut + groups:
        raise AssertionError("invalid persisted ticket bracket B=%d C=%d D=%d G=%d" %
                             (baseline, cut, closing, groups))
    if (state.get("pre_ticket_range") != [baseline + 1, cut] or
            state.get("post_ticket_range") != [cut + 1, closing] or
            int(state.get("snapshot_preimages_delta", 0)) <= 0):
        raise AssertionError("persisted ranges/preimage proof disagree with the ticket bracket")
    witnesses = state["witnesses"]
    if len(witnesses) != 2 or witnesses[0]["owner_tid"] == witnesses[1]["owner_tid"]:
        raise AssertionError("persisted witnesses are not cross-owner: %r" % witnesses)

    client = C(PORT)
    bad = []

    def mismatch(context, expected, actual):
        if len(bad) < 12:
            bad.append("%s expected=%r got=%r" % (context, expected, actual))

    # Pipeline every check, but retain a one-to-one expected list so all classified keys are
    # checked rather than sampled. The loaded target image must contain the <= C transaction and
    # exclude the > C transaction for every type.
    for start in range(0, len(indices), 100):
        commands = []
        expected = []
        for index in indices[start:start + 100]:
            group = (index // 2) // width
            pre_ticket = baseline + group + 1
            post_ticket = cut + group + 1
            pre = ticket_tag("pre", pre_ticket).encode()
            post = ticket_tag("post", post_ticket)
            commands.extend((
                ["HGET", "H%d" % index, "f1"],
                ["ZSCORE", "Z%d" % index, pre.decode()],
                ["ZSCORE", "Z%d" % index, post],
                ["LLEN", "L%d" % index],
                ["LINDEX", "L%d" % index, "-1"],
            ))
            expected.extend((
                ("H%d preimage" % index, pre),
                ("Z%d pre member" % index, b"7.25"),
                ("Z%d post member" % index, None),
                ("L%d cut length" % index, b":6"),
                ("L%d cut tail" % index, pre),
            ))
        for (context, wanted), actual in zip(expected, client.pipeline(commands)):
            if actual != wanted:
                mismatch(context, wanted, actual)

    metadata_commands = []
    metadata_expected = []
    for group in range(groups):
        pre_ticket = baseline + group + 1
        metadata_commands.extend((
            ["GET", "snapshot:ticket:pre:%d" % group],
            ["GET", "snapshot:ticket:post:%d" % group],
        ))
        metadata_expected.extend((
            ("pre metadata %d" % group, str(pre_ticket).encode()),
            ("post metadata %d" % group, None),
        ))
    for (context, wanted), actual in zip(metadata_expected, client.pipeline(metadata_commands)):
        if actual != wanted:
            mismatch(context, wanted, actual)

    last_pre = ticket_tag("pre", cut)
    for suffix, witness in zip(("-a", "-b"), witnesses):
        actual = client.cmd("GET", witness["key"])
        wanted = (last_pre + suffix).encode()
        if actual != wanted:
            mismatch("witness %s" % witness["key"], wanted, actual)

    # An untouched sample keeps the typed serializer baseline in this focused oracle too.
    # STRIDE PARITY MATTERS. MUTATED is every even index, so a stride of 401 -- an odd number --
    # alternates parity and walks straight into keys this test mutated itself (402, 1204, 2006 ...),
    # which then read back as their last pre-cut write and look like snapshot corruption. Step by an
    # even stride from an odd start so every sampled key really is one nothing ever wrote.
    for index in range(1, N, 402):
        h = client.cmd("HGET", "H%d" % index, "f1")
        z = client.cmd("ZSCORE", "Z%d" % index, "m" + "C" * 200)
        length = client.cmd("LLEN", "L%d" % index)
        if h != b"A" * 300:
            mismatch("H%d untouched" % index, b"A" * 300, h)
        if z != b"1.5":
            mismatch("Z%d untouched" % index, b"1.5", z)
        if length != b":5":
            mismatch("L%d untouched" % index, b":5", length)

    if bad:
        print("TYPED TICKET VERIFY FAIL (%d shown): %s" % (len(bad), "; ".join(bad)))
        raise SystemExit(1)
    print("TYPED TICKET VERIFY PASS (keys=%d cut=%d pre<=cut<post)" %
          (len(indices), cut))


if MODE == "race":
    if len(sys.argv) != 4:
        raise SystemExit("race mode needs the configured snapshot path")
    race(sys.argv[3])
elif MODE == "verify":
    if len(sys.argv) != 4:
        raise SystemExit("verify mode needs the .oracle.json path")
    verify(sys.argv[3])
else:
    raise SystemExit("mode must be race or verify")
