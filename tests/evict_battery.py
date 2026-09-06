#!/usr/bin/env python3
# Eviction scenario battery. One SECTION per fresh server boot (the lane has no FLUSHALL, and
# cross-section residue poisons verdicts). tests/gate.sh boots lfu and lruclock on the split and
# the fused+read-local boots; the other sections are the original driver's scenario set.
#   python3 evict_battery.py <port> <section>
# Sections: off noev lru vlru vttl lfu lruclock growth config
#   lfu       hot-set survival under pressure PLUS the mechanism: OBJECT FREQ rises for ordinary
#             reads and stays put for CLIENT NO-TOUCH reads, whoever serves the read.
#   lruclock  the LRU twin on a 1 s bucket (boot with --lru-clock-shift 0): OBJECT IDLETIME
#             resets on a read, keeps aging under NO-TOUCH, and re-touched old keys outlive
#             untouched ones under pressure. The default 256 s bucket makes every key in a short
#             test the same age, which is why the lru section above cannot see a touch at all.
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
    check("allkeys-lru: writes keep landing past limit", True)
    check("allkeys-lru: eviction FIRED", ev and ev > 0, "evicted=%s" % ev)
    check("allkeys-lru: plateau near ceiling (<10k of 14k offered)", dbsize() < 10000, dbsize())

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
    check("volatile-ttl: soon evicted more than late", soon < late, "soon=%d late=%d" % (soon, late))
    check("volatile-ttl: permanents survive", alive("perm", range(300)) == 300)

elif SECTION == "lfu":
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "allkeys-lfu")
    lane_armed = info_num("read_local") == 1
    fill("lfuhot", 20)
    lane0 = info_num("read_local_keyspace_hits") or 0
    for r in range(6):
        for _ in range(5):
            for i in range(20):
                s.sendall(enc(["GET", "lfuhot:%d" % i])); rr()
        fill("lfucold", 3000, start=r * 3000)
    lane_hot = (info_num("read_local_keyspace_hits") or 0) - lane0
    ev = info_num("evicted_keys")
    hot = alive("lfuhot", range(20))
    check("allkeys-lfu: eviction FIRED", ev and ev > 0, "evicted=%s" % ev)
    check("allkeys-lfu: hot 20 mostly survive", hot >= 15, hot)
    if lane_armed:
        # Not 600: a read of an already-evicted hot key probes Missing and demotes to the owner,
        # so the floor has to survive the eviction this section is deliberately causing. 400 of
        # 600 still leaves no doubt about which path answered.
        check("allkeys-lfu: the hot reads were lane-served (read_local_keyspace_hits)",
              lane_hot >= 400, "lane hits %d of 600 reads" % lane_hot)
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
    # Boot with --lru-clock-shift 0: one-second buckets, so a 1.6 s dwell is a visible age.
    must("CONFIG", "SET", "maxmemory", MM); must("CONFIG", "SET", "maxmemory-policy", "allkeys-lru")
    lane_armed = info_num("read_local") == 1
    must("SET", "lruc:probe", "v")
    time.sleep(1.6)
    idle = as_int(cmd("OBJECT", "IDLETIME", "lruc:probe"))
    check("lruclock: bucket advanced over a 1.6 s dwell (needs --lru-clock-shift 0)",
          idle is not None and idle >= 1, idle)
    # Read then probe, twice if need be: on a 1 s bucket a second boundary falling between the
    # GET and the OBJECT IDLETIME reports 1 for a read that did reset the clock, and a gate row
    # must not be decided by which side of a tick it landed on. Three reads per attempt also give
    # the lane more than one chance to admit the command on a freshly opened connection.
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
    time.sleep(1.6)
    nt, ntf = open_conn()
    check("lruclock: CLIENT NO-TOUCH ON", cmd_on(nt, ntf, "CLIENT", "NO-TOUCH", "ON") == b"+OK")
    lane1 = info_num("read_local_keyspace_hits") or 0
    for _ in range(20):
        cmd_on(nt, ntf, "GET", "lruc:probe")
    lane_nt = (info_num("read_local_keyspace_hits") or 0) - lane1
    idle = as_int(cmd("OBJECT", "IDLETIME", "lruc:probe"))
    check("lruclock: 20 NO-TOUCH reads leave IDLETIME aging", idle is not None and idle >= 1, idle)
    nt.close()
    if lane_armed:
        check("lruclock: the probe reads were lane-served", lane_probe >= 3 and lane_nt >= 15,
              "plain %d/3+ no-touch %d/20" % (lane_probe, lane_nt))
    # Discrimination under pressure: 3000 old keys age one bucket, 50 of them are re-read, then
    # 6800 new keys push past the ceiling. The pressure is deliberately sized so that the eviction
    # it forces (~1.4k) is roughly HALF the untouched old bucket (2950) rather than nearly all of
    # it: the ceiling is per SHARD, and a run that has to consume ~90% of the average shard's old
    # keys will exhaust the unlucky shards and start spending re-read ones for reasons that have
    # nothing to do with the policy. At half, the re-read 50 survive on their bucket alone and the
    # untouched sample halves -- and on a server whose lane does not touch, the re-read 50 are just
    # 50 more untouched keys and "mostly survive" fails, which is the whole point of the row.
    fill("lruold", 3000)
    time.sleep(1.6)
    lane2 = info_num("read_local_keyspace_hits") or 0
    for i in range(50):
        cmd("GET", "lruold:%d" % i)
    lane_hot = (info_num("read_local_keyspace_hits") or 0) - lane2
    fill("lrunew", 6800, tolerate_oom=True)
    ev = info_num("evicted_keys")
    hot = alive("lruold", range(50))
    cold = alive("lruold", range(50, 3000, 59))
    check("lruclock: eviction FIRED", ev and ev > 0, "evicted=%s" % ev)
    check("lruclock: the 50 re-read old keys mostly survive (>=40)", hot >= 40, hot)
    check("lruclock: untouched old keys went first", cold < hot, "untouched %d/50 alive, re-read %d/50" % (cold, hot))
    if lane_armed:
        check("lruclock: the re-reads were lane-served", lane_hot >= 40, "lane hits %d of 50" % lane_hot)

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
