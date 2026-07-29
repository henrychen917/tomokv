#!/usr/bin/env python3
"""ee451 (#B2) exact-count check for the PER-COMMAND statistics surface.

Companion to numcmd_check.py, which checks the ONE global command counter. This checks the three
per-command surfaces that had the same root cause (workers never enter call()):

  1. INFO commandstats   cmdstat_<cmd>:calls / usec / failed_calls / rejected_calls
  2. INFO latencystats   latency_percentiles_usec_<cmd>
  3. CLIENT INFO         tot-cmds  (c->commands_processed)

Method: CONFIG RESETSTAT, then drive an EXACTLY known number of commands of known types over one
connection, then assert INFO reports exactly that number. Nothing is approximate and nothing is a
ratio-with-slop: a correct server matches to the unit.

Routes covered, because they are three different code paths in this fork:
  SET/GET/LPUSH  worker-routed single-key  (exExecFake)
  PING           inline on the io thread   (call())
  MGET k1..k8    cross-shard scatter       (csSubExec -> csReassemble, ONE call per group)

Exit code 0 = every assertion held, 1 = at least one did not.
"""
import socket, sys, threading, time

port = int(sys.argv[1])
label = sys.argv[2] if len(sys.argv) > 2 else "run"

N = 20000          # per worker-routed command type
NP = 20000         # inline PINGs
NM = 4000          # cross-shard MGETs (8 keys each)
NF = 5000          # deliberately failing worker commands (WRONGTYPE)

fails = []


def cmd(*a):
    o = f"*{len(a)}\r\n".encode()
    for x in a:
        b = x if isinstance(x, bytes) else str(x).encode()
        o += b"$%d\r\n%s\r\n" % (len(b), b)
    return o


SENT = b"ZZ_CMDSTAT_SENTINEL_ZZ"


def read_bulk(s):
    """Read one RESP reply that is expected to be a bulk string, return its body."""
    buf = b""
    while True:
        c = s.recv(1 << 20)
        if not c:
            raise RuntimeError("connection closed mid-reply")
        buf += c
        if buf[0:1] != b"$":
            raise RuntimeError("unexpected reply %r" % buf[:64])
        hdr = buf.find(b"\r\n")
        if hdr < 0:
            continue
        n = int(buf[1:hdr])
        if n < 0:
            return b""
        if len(buf) >= hdr + 2 + n + 2:
            return buf[hdr + 2:hdr + 2 + n]


def info(s, section):
    s.sendall(cmd("INFO", section))
    return read_bulk(s).decode(errors="replace")


def client_info(s):
    s.sendall(cmd("CLIENT", "INFO"))
    return read_bulk(s).decode(errors="replace")


def tot_cmds(s):
    for tok in client_info(s).split():
        if tok.startswith("tot-cmds="):
            return int(tok.split("=")[1])
    raise RuntimeError("tot-cmds not present in CLIENT INFO — the field was renamed or removed")


def cmdstats(text):
    """cmdstat_get:calls=1,usec=2,... -> {'get': {'calls':1,'usec':2,...}}"""
    out = {}
    for line in text.splitlines():
        if not line.startswith("cmdstat_"):
            continue
        name, _, rest = line[len("cmdstat_"):].partition(":")
        d = {}
        for kv in rest.split(","):
            k, _, v = kv.partition("=")
            try:
                d[k] = float(v) if "." in v else int(v)
            except ValueError:
                pass
        out[name] = d
    return out


def latnames(text):
    return {line.split(":")[0][len("latency_percentiles_usec_"):]
            for line in text.splitlines()
            if line.startswith("latency_percentiles_usec_")}


def check(name, got, want):
    ok = got == want
    print("  %-42s got=%-10s want=%-10s %s" % (name, got, want, "OK" if ok else "*** WRONG ***"))
    if not ok:
        fails.append("%s: got %s want %s" % (name, got, want))
    return ok


def check_ge(name, got, want):
    ok = got >= want
    print("  %-42s got=%-10s want>=%-8s %s" % (name, got, want, "OK" if ok else "*** WRONG ***"))
    if not ok:
        fails.append("%s: got %s want >= %s" % (name, got, want))
    return ok


s = socket.create_connection(("127.0.0.1", port))
s.settimeout(180)
s.sendall(cmd("PING"))
while b"+PONG" not in s.recv(1 << 16):
    pass

# latencystats is only populated when latency tracking is on; make that explicit rather than
# depending on the config file, so an "absent section" result can only mean the defect.
s.sendall(cmd("CONFIG", "SET", "latency-tracking", "yes"))
s.recv(1 << 16)

# Seed the string keys that the WRONGTYPE probes will collide with, BEFORE the reset, so the
# seeding SETs are not part of the counted traffic.
seed = b"".join(cmd("SET", "str:%d" % i, "v") for i in range(64)) + cmd("ECHO", SENT)
s.sendall(seed)
buf = b""
while SENT not in buf:
    buf = buf[-64:] + s.recv(1 << 20)

s.sendall(cmd("CONFIG", "RESETSTAT"))
s.recv(1 << 16)

base_tot = tot_cmds(s)     # CLIENT INFO reports BEFORE call() bumps, so it leaves base_tot+1

batch = []
batch += [cmd("SET", "k:%d" % i, "v") for i in range(N)]
batch += [cmd("GET", "k:%d" % i) for i in range(N)]
batch += [cmd("PING") for _ in range(NP)]
batch += [cmd("MGET", *["k:%d" % ((i * 8 + j) % N) for j in range(8)]) for i in range(NM)]
batch += [cmd("LPUSH", "str:%d" % (i % 64), "x") for i in range(NF)]   # WRONGTYPE on a worker
n_sent = len(batch)

payload = b"".join(batch) + cmd("ECHO", SENT)
err = []


def reader():
    b = b""
    try:
        while SENT not in b:
            c = s.recv(1 << 20)
            if not c:
                err.append("closed before sentinel")
                return
            b = b[-64:] + c
    except Exception as e:                     # noqa: BLE001 - surfaced via err
        err.append(repr(e))


t = threading.Thread(target=reader, daemon=True)
t.start()
s.sendall(payload)
t.join(300)
if t.is_alive():
    raise RuntimeError("timed out waiting for sentinel")
if err:
    raise RuntimeError("reader failed: %s" % err[0])
n_sent += 1                                    # the ECHO sentinel
time.sleep(0.5)                                # let any in-flight bumps land

after_tot = tot_cmds(s)
cs = cmdstats(info(s, "commandstats"))
ls = latnames(info(s, "latencystats"))

print("%s: INFO commandstats — exact per-command call counts" % label)
check("cmdstat_set:calls   (worker route)", cs.get("set", {}).get("calls", 0), N)
check("cmdstat_get:calls   (worker route)", cs.get("get", {}).get("calls", 0), N)
check("cmdstat_ping:calls  (inline route)", cs.get("ping", {}).get("calls", 0), NP)
check("cmdstat_mget:calls  (cross-shard) ", cs.get("mget", {}).get("calls", 0), NM)
check("cmdstat_lpush:calls (worker route)", cs.get("lpush", {}).get("calls", 0), NF)

print("%s: INFO commandstats — failed_calls (WRONGTYPE on a worker)" % label)
check("cmdstat_lpush:failed_calls", cs.get("lpush", {}).get("failed_calls", 0), NF)
check("cmdstat_get:failed_calls", cs.get("get", {}).get("failed_calls", 0), 0)

print("%s: INFO commandstats — usec must accumulate, not stay 0" % label)
check_ge("cmdstat_set:usec", cs.get("set", {}).get("usec", 0), 1)
check_ge("cmdstat_get:usec", cs.get("get", {}).get("usec", 0), 1)
check_ge("cmdstat_mget:usec", cs.get("mget", {}).get("usec", 0), 1)

print("%s: INFO latencystats — a distribution per executed command" % label)
for c in ("set", "get", "ping", "mget", "lpush"):
    ok = c in ls
    print("  %-42s %s" % ("latency_percentiles_usec_" + c, "OK" if ok else "*** MISSING ***"))
    if not ok:
        fails.append("latencystats missing %s" % c)

print("%s: CLIENT INFO tot-cmds — per-client counter" % label)
# base_tot was read by a CLIENT INFO that reports before counting itself, hence the -1.
check("tot-cmds delta over the run", after_tot - base_tot - 1, n_sent)

print()
if fails:
    print("%s: FAILED (%d)" % (label, len(fails)))
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("%s: PASSED" % label)
sys.exit(0)
