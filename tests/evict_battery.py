#!/usr/bin/env python3
# Eviction scenario battery. One SECTION per fresh server boot (the lane has no FLUSHALL, and
# cross-section residue poisons verdicts). tests/gate.sh boots lfu and lruclock on the split and
# the fused+read-local boots; the other sections are the original driver's scenario set.
#   python3 evict_battery.py <port> <section>
# Sections: off noev lru vlru vttl lfu lruclock growth config
#   lfu       hot-set survival under pressure PLUS the mechanism: OBJECT FREQ rises for ordinary
#             reads and stays put for CLIENT NO-TOUCH reads, whoever serves the read.
#   lruclock  the LRU twin on the fixed 256 s clock: seed every old cohort before one bucket
#             boundary, then prove ordinary reads reset age, NO-TOUCH retains age, and
#             all 50 re-read keys enter a newer bucket before eviction. The bounded clock wait
#             can take 260 s per boot. Sampled eviction cannot promise universal hot-key survival.
# On a fused boot with the read-local lane armed (INFO server read_local:1) both sections also
# assert the reads they measure were LANE-served: before the lane learned to touch, a key kept hot
# only by such reads was never counted as accessed and was evicted FIRST -- the policy inverted.
import socket, sys, time

HOST, PORT, SECTION = "127.0.0.1", int(sys.argv[1]), sys.argv[2]
s = socket.create_connection((HOST, PORT), timeout=20)
f = s.makefile("rb")

def enc(a):
    o = b"*%d\r\n" % len(a)
    for x in a:
        x = x.encode() if isinstance(x, str) else x
        o += b"$%d\r\n" % len(x) + x + b"\r\n"
    return o

def rr_on(fh):
    line = fh.readline()
    if not line: raise EOFError
    t = line[:1]
    if t in b"+-:": return line.strip()
    if t == b"$":
        n = int(line[1:-2]); return None if n == -1 else fh.read(n + 2)[:-2]
    n = int(line[1:-2]); return [rr_on(fh) for _ in range(n)]

def rr(): return rr_on(f)

def cmd(*a):
    s.sendall(enc(list(a))); return rr()

def open_conn():
    c = socket.create_connection((HOST, PORT), timeout=20)
    return c, c.makefile("rb")

def cmd_on(c, fh, *a):
    c.sendall(enc(list(a))); return rr_on(fh)

def as_int(reply):
    return int(reply[1:]) if isinstance(reply, bytes) and reply[:1] == b":" else None

def must(*a):
    r = cmd(*a)
    assert not (isinstance(r, bytes) and r.startswith(b"-")), (a, r)
    return r

def fill(prefix, n, sz=100, ttl=None, start=0, tolerate_oom=False):
    B = 500; ooms = 0
    for i in range(start, start + n, B):
        chunk = b""
        cnt = 0
        for j in range(i, min(i + B, start + n)):
            if ttl: chunk += enc(["SET", "%s:%d" % (prefix, j), "v" * sz, "EX", str(ttl)])
            else:   chunk += enc(["SET", "%s:%d" % (prefix, j), "v" * sz])
            cnt += 1
        s.sendall(chunk)
        for _ in range(cnt):
            r = rr()
            if isinstance(r, bytes) and r.startswith(b"-"):
                assert tolerate_oom, r
                ooms += 1
    return ooms

def info_num(field):
    txt = cmd("INFO")
    for ln in txt.split(b"\r\n"):
        if ln.startswith(field.encode() + b":"): return int(ln.split(b":")[1])
    return None

def dbsize(): return int(cmd("DBSIZE")[1:])
def alive(prefix, rng): return sum(1 for i in rng if cmd("EXISTS", "%s:%d" % (prefix, i)) == b":1")

P = 0; F = 0
def check(name, ok, detail=""):
    global P, F
    print("  %-52s %s %s" % (name, "ok" if ok else "FAIL", detail))
    P, F = P + (1 if ok else 0), F + (0 if ok else 1)

MM = "1048576"   # 1MB / 16 shards = 64KB/shard; ~124B per 100B-value key => ~8.4k-key ceiling

if SECTION == "off":
    fill("off", 3000)
    check("disabled: 3000 writes all land", dbsize() == 3000, dbsize())
    check("disabled: evicted_keys==0", info_num("evicted_keys") == 0)

elif SECTION == "noev":
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "noeviction")
    oom = None
    for i in range(40000):
        s.sendall(enc(["SET", "noev:%d" % i, "x" * 100]))
        r = rr()
        if r.startswith(b"-"): oom = r; break
    check("noeviction: hits OOM", oom is not None, (oom or b"")[:40])
    check("noeviction: exact redis OOM text",
          oom == b"-OOM command not allowed when used memory > 'maxmemory'.")
    check("noeviction: evicted_keys stays 0", info_num("evicted_keys") == 0)

elif SECTION == "lru":
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "allkeys-lru")
    fill("lru", 8000)
    for r in range(3):     # keep hot set warm while pressure continues
        for i in range(50):
            s.sendall(enc(["GET", "lru:%d" % i])); rr()
        fill("lrufill", 2000, start=r * 2000)
    ev = info_num("evicted_keys")
    live = dbsize()
    OFFERED = 8000 + 3 * 2000
    # Was `check("...writes keep landing past limit", True)` -- literally the constant True, a row
    # that could not fail. The claim it meant to make is an IDENTITY, and an exact one: fill() does
    # not tolerate OOM, so every one of the 14000 writes was accepted, nothing here carries a TTL,
    # no key is written twice, and under allkeys-lru an accepted key is either still live or was
    # evicted to make room for a later one. Nothing sampled about it.
    check("allkeys-lru: every offered write landed (live + evicted == offered)",
          live + (ev or 0) == OFFERED,
          "live=%d evicted=%s offered=%d" % (live, ev, OFFERED))
    check("allkeys-lru: eviction FIRED", ev and ev > 0, "evicted=%s" % ev)
    # The plateau, stated as the property rather than as an observed constant. The budget buys a
    # ceiling, not a number somebody measured once: MM / 16 shards / ~124 B per 100 B-value key is
    # ~8.4k keys (see MM above), so a policy that is working holds the live set at that ceiling and
    # therefore materially SHORT of the 14000 offered. The 25% is headroom for per-shard imbalance,
    # not a threshold anyone tunes: the discriminating gap here is 8.4k against 14k.
    CEILING = 8400
    check("allkeys-lru: live set plateaus at the budget ceiling, not at what was offered",
          live < CEILING * 5 // 4,
          "live=%d ceiling~%d offered=%d" % (live, CEILING, OFFERED))

elif SECTION == "vlru":
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "volatile-lru")
    fill("persist", 5000)                       # < ceiling: all land
    ooms = fill("pfill", 20000, tolerate_oom=True)   # no volatiles -> must OOM, never evict
    check("volatile-lru, no volatiles: OOMs observed", ooms > 0, ooms)
    check("volatile-lru: zero evictions without volatiles", info_num("evicted_keys") == 0)
    check("volatile-lru: persistents untouched", alive("persist", range(0, 5000, 100)) == 50)

elif SECTION == "vttl":
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "volatile-ttl")
    fill("soon", 3000, ttl=50)
    fill("late", 3000, ttl=10000)
    fill("perm", 300)
    fill("ttlfill", 8000, ttl=5000, tolerate_oom=True)
    ev = info_num("evicted_keys")
    soon, late = alive("soon", range(0, 3000, 60)), alive("late", range(0, 3000, 60))
    check("volatile-ttl: eviction FIRED", ev and ev > 0, "evicted=%s" % ev)
    # A count out of a sampled victim choice, so it is stated the way the survival rows in the lfu
    # and lruclock sections are: RELATIVE, needing no observed constant, and inverting outright if
    # the policy stops preferring the nearest expiry. The absolute companion below is what makes
    # the comparison non-vacuous -- if the pressure never reached the `soon` bucket at all both
    # counts would sit at 50 and "soon < late" would be deciding on noise rather than on policy.
    check("volatile-ttl: pressure reached the nearest-expiry bucket", soon < 50,
          "soon=%d/50 alive" % soon)
    check("volatile-ttl: soon evicted more than late", soon < late, "soon=%d late=%d" % (soon, late))
    check("volatile-ttl: permanents survive", alive("perm", range(300)) == 300)

elif SECTION == "lfu":
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "allkeys-lfu")
    lane_armed = info_num("read_local") == 1
    fill("lfuhot", 20)
    lane0 = info_num("read_local_keyspace_hits") or 0
    # The hot set is read THROUGH the pressure, not in a burst before each fill, and that is what
    # makes this row deterministic instead of a coin flip. Our LFU counter has five header bits and
    # no wall-clock decay: it is decremented once per SAMPLING event instead (flatstore.h
    # choose_victim, "sampling is also the bounded aging event"). 18k cold writes against an ~8.4k
    # ceiling force ~10.5k evictions x 5 samples = ~53k decrements spread over the live set, so
    # every key -- hot ones included -- is decayed several times per round. Read the hot set in a
    # burst BEFORE a 3000-key fill and its counters are ground down with nothing to restore them,
    # landing on 2-7 while the cold keys sit on 2-6: two overlapping distributions, and the row
    # then draws a number. Read it DURING the fill and each decrement is repaid immediately (the
    # logarithmic increment has probability 1 below 6), so the hot set holds 6-18 against the same
    # cold 2-6 and all 20 survive.
    #
    # DO NOT "fix" a flake here with CONFIG SET maxmemory-samples 64. Because the decay is per
    # sample rather than per unit time -- unlike Redis, whose lfu-decay-time is independent of
    # maxmemory-samples -- raising the sample count raises the decay rate with it: measured 4/20
    # survivors at samples=64 with burst reads, against 17-20 at the default 5. More samples buys a
    # more exact victim among counters that have all been crushed to the floor.
    HOT = ["lfuhot:%d" % i for i in range(20)]
    hot_reads = 0
    for r in range(6):
        for c in range(6):
            for _ in range(17):
                for k in HOT:
                    s.sendall(enc(["GET", k])); rr()
                hot_reads += len(HOT)
            fill("lfucold", 500, start=r * 3000 + c * 500)
    lane_hot = (info_num("read_local_keyspace_hits") or 0) - lane0
    ev = info_num("evicted_keys")
    survivors = [k for k in HOT if cmd("EXISTS", k) == b":1"]
    freqs = sorted(x for x in (as_int(cmd("OBJECT", "FREQ", k)) for k in survivors) if x is not None)
    median = freqs[len(freqs) // 2] if freqs else None
    check("allkeys-lfu: eviction FIRED", ev and ev > 0, "evicted=%s" % ev)
    check("allkeys-lfu: the hot 20 ALL survive", len(survivors) == 20, "%d/20 alive" % len(survivors))
    # The bound that makes the survival row deterministic, asserted directly. A cold key is written
    # at 5 and its write counts as an access, so the cold population's ceiling is 6 and decay only
    # moves it down; a median hot counter of 8 is more than one probabilistic increment clear of
    # that ceiling. Measured medians on this tree: 9.5-13 over six boots, both atomic modes, split
    # and fused+armed. On a server whose lane does not touch, the hot keys never leave the cold
    # band at all (measured 2-5, and 2-4 of 20 alive), so this row and the one above fail together.
    check("allkeys-lfu: hot counters stay clear of the cold band (median OBJECT FREQ >= 8)",
          median is not None and median >= 8, "median=%s freqs=%s" % (median, freqs))
    if lane_armed:
        check("allkeys-lfu: the hot reads were lane-served (read_local_keyspace_hits)",
              lane_hot >= hot_reads * 8 // 10,
              "lane hits %d of %d reads" % (lane_hot, hot_reads))
    # MECHANISM, on a key nothing else samples: a fresh key starts at 5; the first ordinary read
    # raises it for certain (the logarithmic increment has probability 1 below 6), while reads
    # from a CLIENT NO-TOUCH connection must leave it exactly where the write put it.
    must("SET", "lfunt", "v")
    check("allkeys-lfu: fresh key starts at OBJECT FREQ 5", as_int(cmd("OBJECT", "FREQ", "lfunt")) == 5,
          cmd("OBJECT", "FREQ", "lfunt"))
    nt, ntf = open_conn()
    check("allkeys-lfu: CLIENT NO-TOUCH ON", cmd_on(nt, ntf, "CLIENT", "NO-TOUCH", "ON") == b"+OK")
    lane1 = info_num("read_local_keyspace_hits") or 0
    for _ in range(20):
        cmd_on(nt, ntf, "GET", "lfunt")
    lane_nt = (info_num("read_local_keyspace_hits") or 0) - lane1
    check("allkeys-lfu: 20 NO-TOUCH reads leave OBJECT FREQ at 5",
          as_int(cmd("OBJECT", "FREQ", "lfunt")) == 5, cmd("OBJECT", "FREQ", "lfunt"))
    lane2 = info_num("read_local_keyspace_hits") or 0
    for _ in range(20):
        cmd("GET", "lfunt")
    lane_plain = (info_num("read_local_keyspace_hits") or 0) - lane2
    freq = as_int(cmd("OBJECT", "FREQ", "lfunt"))
    check("allkeys-lfu: 20 ordinary reads raise OBJECT FREQ above 5", freq is not None and freq > 5, freq)
    if lane_armed:
        check("allkeys-lfu: both probes were lane-served", lane_nt >= 15 and lane_plain >= 15,
              "no-touch %d/20 plain %d/20" % (lane_nt, lane_plain))
    nt.close()

elif SECTION == "lruclock":
    # The production clock is fixed at 256 seconds per bucket.
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "allkeys-lru")
    # LRU reads metadata without aging it. However, these are 64 draws WITH REPLACEMENT,
    # deduplicated after drawing, not an exhaustive scan (flatstore.h choose_victim*).
    # Even with old keys remaining, a sample can contain only newer keys. No finite old-cohort
    # size makes (1-p)^64 zero. GT18's 49/50 survivors therefore cannot adjudicate a touch defect.
    # Assert exact clock metadata before pressure; store_regression's aof-eviction case proves
    # the real chooser prefers an older key when BOTH ages are present in its candidate sample.
    must("CONFIG", "SET", "maxmemory-samples", "64")
    lane_armed = info_num("read_local") == 1
    must("SET", "lruc:probe", "v")
    must("SET", "lruc:no-touch", "v")
    fill("lruold", 3000)
    # Age all three cohorts together. Poll the last-created key without touching it, so the
    # whole cohort must cross a real production bucket; an unchanged clock must fail this arm.
    deadline = time.monotonic() + 260
    aged = None
    while time.monotonic() < deadline:
        aged = as_int(cmd("OBJECT", "IDLETIME", "lruold:2999"))
        if aged is not None and aged >= 256:
            break
        time.sleep(0.1)
    check("lruclock: production clock advanced for the full old cohort",
          aged is not None and aged >= 256, aged)
    # Retry the read/probe pair only if a clock boundary fell between its two commands.
    def read_then_idle(key):
        for _ in range(3):
            cmd("GET", key)
        return as_int(cmd("OBJECT", "IDLETIME", key))
    lane0 = info_num("read_local_keyspace_hits") or 0
    idle = read_then_idle("lruc:probe")
    if idle != 0:
        idle = read_then_idle("lruc:probe")
    lane_probe = (info_num("read_local_keyspace_hits") or 0) - lane0
    check("lruclock: one ordinary read resets OBJECT IDLETIME to 0", idle == 0, idle)
    nt, ntf = open_conn()
    check("lruclock: CLIENT NO-TOUCH ON", cmd_on(nt, ntf, "CLIENT", "NO-TOUCH", "ON") == b"+OK")
    lane1 = info_num("read_local_keyspace_hits") or 0
    for _ in range(20):
        cmd_on(nt, ntf, "GET", "lruc:no-touch")
    lane_nt = (info_num("read_local_keyspace_hits") or 0) - lane1
    idle = as_int(cmd("OBJECT", "IDLETIME", "lruc:no-touch"))
    check("lruclock: 20 NO-TOUCH reads preserve an old bucket", idle is not None and idle >= 256, idle)
    nt.close()
    if lane_armed:
        check("lruclock: the probe reads were lane-served", lane_probe >= 3 and lane_nt >= 15,
              "plain %d/3+ no-touch %d/20" % (lane_probe, lane_nt))
    # Prove the touch on every key, while eviction is still impossible. Warm the lane with
    # NO-TOUCH first, then require ALL measured reads to be lane-served on the armed boot.
    # If dispatch falls back, re-arm on 50 fresh, still-old keys: an executor touch in an
    # invalid attempt must not conceal a missing lane touch in the next attempt.
    reads = 3 * 50
    for attempt in range(3):
        hot_indices = range(attempt * 50, (attempt + 1) * 50)
        HOT = ["lruold:%d" % i for i in hot_indices]
        must("CLIENT", "NO-TOUCH", "ON")
        for _ in range(3):
            for key in HOT:
                assert cmd("GET", key) == b"v" * 100, key
        must("CLIENT", "NO-TOUCH", "OFF")
        old_ages = [as_int(cmd("OBJECT", "IDLETIME", key)) for key in HOT]
        assert all(age is not None and age >= 256 for age in old_ages), (
            "lruclock: fresh re-read cohort never armed in an old bucket", old_ages)
        lane2 = info_num("read_local_keyspace_hits") or 0
        for _ in range(3):
            for key in HOT:
                assert cmd("GET", key) == b"v" * 100, key
        lane_hot = (info_num("read_local_keyspace_hits") or 0) - lane2
        hot_ages = [as_int(cmd("OBJECT", "IDLETIME", key)) for key in HOT]
        if not lane_armed or lane_hot == reads:
            break
        print("  lruclock: INVALID touch arm %d/3: lane hits %d/%d; fresh cohort next" %
              (attempt + 1, lane_hot, reads))
    else:
        raise AssertionError("lruclock: no fully lane-served touch window in 3 fresh cohorts")
    check("lruclock: all 50 re-read keys reset IDLETIME before eviction",
          hot_ages == [0] * 50, hot_ages)
    cold_ages = [as_int(cmd("OBJECT", "IDLETIME", "lruold:%d" % i))
                for i in range(150, 3000, 57)]
    check("lruclock: untouched keys are in an older bucket than all 50 re-reads",
          hot_ages == [0] * 50 and all(age is not None and age >= 256 for age in cold_ages),
          cold_ages)
    if lane_armed:
        check("lruclock: all measured re-reads were lane-served", lane_hot == reads,
              "lane hits %d of %d" % (lane_hot, reads))
    # Exercise real pressure as well, but judge its exact accounting identity. Survivor counts
    # are diagnostics: the sampler's contract is oldest IN THE SAMPLE, not oldest in the shard.
    ooms = 0
    for c in range(15):
        for k in HOT:
            cmd("GET", k)
        ooms += fill("lrunew", 400, start=c * 400, tolerate_oom=True)
    ev = info_num("evicted_keys")
    hot = alive("lruold", hot_indices)
    cold = alive("lruold", range(150, 3000, 57))
    live = int(cmd("DBSIZE", "NOW")[1:])
    # INFO's eviction counter is batch-published. With all writes acknowledged, NOW is an
    # exact census; wait for the counter to catch up to that identity without any count slack.
    deadline = time.monotonic() + 1
    while live + (ev or 0) + ooms != 9002 and time.monotonic() < deadline:
        time.sleep(.001)
        ev = info_num("evicted_keys")
    check("lruclock: eviction FIRED", ev and ev > 0, "evicted=%s" % ev)
    check("lruclock: every pressure write is accounted for", live + (ev or 0) + ooms == 9002,
          "live=%d evicted=%s rejected=%d offered=9002" % (live, ev, ooms))
    print("  lruclock: sampled survival (diagnostic): untouched %d/50, re-read %d/50" % (cold, hot))

elif SECTION == "growth":
    # wrinkle fix: collection growth must respect maxmemory (pre-exec DENYOOM gate).
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "noeviction")
    oom = None; i = 0
    while i < 60000 and oom is None:          # one hash, grown far past the whole-server budget
        s.sendall(enc(["HSET", "bigh", "f%d" % i, "v" * 100]))
        r = rr()
        if isinstance(r, bytes) and r.startswith(b"-"): oom = r
        i += 1
    check("growth: HSET on one hash hits OOM", oom is not None, (oom or b"")[:40])
    check("growth: exact redis OOM text",
          oom == b"-OOM command not allowed when used memory > 'maxmemory'.")
    check("growth: reads still served", cmd("HLEN", "bigh")[:1] == b":")
    check("growth: DEL allowed while over budget", cmd("DEL", "bigh") == b":1")
    ok_after = cmd("HSET", "bigh2", "f", "v")
    check("growth: writes recover after DEL", ok_after == b":1", ok_after)
    must("CONFIG", "SET", "maxmemory-policy", "allkeys-lru")
    fill("filler", 3000)
    grown = 0; stopped = False
    for j in range(40000):
        s.sendall(enc(["RPUSH", "bigl", "x" * 100]))
        r = rr()
        if isinstance(r, bytes) and r.startswith(b"-"): stopped = True; break
        grown += 1
    ev = info_num("evicted_keys")
    check("growth: allkeys-lru evicts others for list growth", ev and ev > 0, "evicted=%s" % ev)
    check("growth: gate closes once nothing evictable remains", stopped, "grew %d then %s" % (grown, "OOM" if stopped else "never stopped"))

elif SECTION == "config":
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "allkeys-lru")
    fill("cfg", 3000)
    must("CONFIG", "SET", "maxmemory", "0")     # live-disable
    n0 = dbsize()
    fill("cfg2", 6000)
    check("maxmemory=0 re-disables (all 6000 land)", dbsize() == n0 + 6000, dbsize() - n0)
    check("samples: rejects 0", cmd("CONFIG", "SET", "maxmemory-samples", "0").startswith(b"-"))
    check("samples: rejects 65", cmd("CONFIG", "SET", "maxmemory-samples", "65").startswith(b"-"))
    check("samples: accepts 64", cmd("CONFIG", "SET", "maxmemory-samples", "64") == b"+OK")
    check("policy: rejects junk", cmd("CONFIG", "SET", "maxmemory-policy", "zzz").startswith(b"-"))
    g = cmd("CONFIG", "GET", "maxmemory-policy")
    check("CONFIG GET policy roundtrip", g[1] == b"allkeys-lru", g)
    multi = cmd("CONFIG", "SET", "maxmemory", "4194304", "maxmemory-policy", "volatile-ttl")
    g2 = cmd("CONFIG", "GET", "*")
    check("multi-pair CONFIG SET coherent", multi == b"+OK" and b"4194304" in g2 and b"volatile-ttl" in g2)

print("SECTION %s: %d ok, %d FAIL" % (SECTION, P, F))
# A section name this file does not implement falls through every branch above and would otherwise
# report "0 ok, 0 FAIL" and exit 0 -- a gate row that turns green having tested nothing. A driver
# typo is a gate defect, so say so and go red.
if P + F == 0:
    print("SECTION %s ran no checks -- unknown section name?" % SECTION)
    sys.exit(1)
sys.exit(1 if F else 0)
