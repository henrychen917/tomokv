import os, shutil, socket, sys, threading, time, random
PORT = int(sys.argv[1]); MODE = sys.argv[2]   # save | verify_cut | verify_save | atomic_groups
def conn(p=None):
    s = socket.create_connection(("127.0.0.1", p or PORT), timeout=20); return s, s.makefile("rb")
def enc(a):
    o=b"*%d\r\n"%len(a)
    for x in a:
        x=x.encode() if isinstance(x,str) else x
        o+=b"$%d\r\n"%len(x)+x+b"\r\n"
    return o
def rr(f):
    line=f.readline()
    if not line: raise EOFError
    t=line[:1]
    if t in b"+-:": return line.strip()
    if t==b"$":
        n=int(line[1:-2]); return None if n==-1 else f.read(n+2)[:-2]
    n=int(line[1:-2]); return [rr(f) for _ in range(n)]
s, f = conn()
def cmd(*a): s.sendall(enc(list(a))); return rr(f)
def info_field(name):
    t = cmd("INFO")
    for ln in t.split(b"\r\n"):
        if ln.startswith(name.encode()+b":"): return ln.split(b":",1)[1]
    return None
rng = random.Random(11)
KEYS = [("pk:%d"%i, "val-%d-%s"%(i, "x"*rng.randrange(0,200))) for i in range(6000)]
TTLK = [("tk:%d"%i, "tval%d"%i) for i in range(500)]

# ---------------------------------------------------------------------------------------------
# atomic_groups: does a cut taken under load write HALF-APPLIED cross-shard atomic groups?
#
# The rest of this battery only ever writes single keys, so it passes on a tree whose snapshot
# tears every multi-key group. This arm is the one that can tell the difference. Each group is a
# generation-tagged cross-shard MSET (or MULTI/EXEC): all of a group's keys carry the same
# generation, forever. A snapshot in which one group's keys disagree therefore contains a state
# that never existed, and it is read straight out of the .tomo bytes with no server involved.
#
# Non-vacuous by construction:
#   * DEBUG SHARD proves every group really spans >1 shard (the hash seed is drawn at boot, so a
#     key-name-only "cross-shard" test can silently be same-owner and prove nothing);
#   * a live MGET reader runs against the same server throughout and must see zero torn groups --
#     that is what makes a torn FILE a contract violation rather than a permitted interleaving;
#   * INFO snapshot_cuts_waited must advance: a group drain that never actually blocks is
#     indistinguishable from a missing one.
# ---------------------------------------------------------------------------------------------
AG_GROUPS = 100
AG_SLOTS = 8
AG_CONNS = 24
AG_ROUNDS = 32            # MSETs of the writer's groups kept in flight at once -> deep ex queues
AG_GENS = 16
AG_PAD = "p" * 400
FRAME_TAG, FOOTER_TAG, RECORD_TAG = 0x4D415246, 0x454E4F44, 0x44434552

def ag_key(g, sl): return "ag:%d:%d" % (g, sl)
def ag_val(g, sl, gen): return "G%d#%d:%d:%s" % (gen, g, sl, AG_PAD)
def ag_gen(v): return int(v[1:v.index(b"#")])

def ag_scan(path):
    """Server-free .tomo reader: {key: (value, shard)}. Mirrors snapshot_read_plan()."""
    with open(path, "rb") as fh: data = fh.read()
    u32 = lambda p: int.from_bytes(data[p:p+4], "little")
    if data[:8] != b"TOMOSNP\0": raise AssertionError("not a tomo snapshot: %r" % data[:8])
    pos, sections = 80, {}
    while pos + 32 <= len(data) and u32(pos) == FRAME_TAG:
        sid, seq, ln = u32(pos+4), u32(pos+8), u32(pos+16)
        pos += 32
        sections.setdefault(sid, []).append((seq, data[pos:pos+ln]))
        pos += ln
    if u32(pos) != FOOTER_TAG: raise AssertionError("no footer at %d/%d" % (pos, len(data)))
    out = {}
    for sid, frames in sections.items():
        frames.sort()
        blob = b"".join(p for _, p in frames)
        off = 0
        while off < len(blob):
            if int.from_bytes(blob[off:off+4], "little") != RECORD_TAG:
                raise AssertionError("bad record tag in shard %d" % sid)
            klen = int.from_bytes(blob[off+8:off+12], "little")
            plen = int.from_bytes(blob[off+16:off+24], "little")
            off += 32
            k = blob[off:off+klen]; off += klen
            v = blob[off:off+plen]; off += plen
            out[k] = (v, sid)
    return out

def ag_file_torn(path):
    kv = ag_scan(path)
    torn, present, examples = 0, 0, []
    for g in range(AG_GROUPS):
        gens = {ag_gen(kv[ag_key(g, sl).encode()][0])
                for sl in range(AG_SLOTS) if ag_key(g, sl).encode() in kv}
        if not gens: continue
        present += 1
        if len(gens) > 1:
            torn += 1
            if len(examples) < 3: examples.append((g, sorted(gens)))
    return torn, present, len(kv), examples

if MODE == "atomic_groups":
    DUMP = sys.argv[3]
    WRITE = sys.argv[4] if len(sys.argv) > 4 else "mset"      # mset | exec
    SAVES = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    fail = []
    def need(ok, what):
        print(("  ok   " if ok else "  FAIL ") + what, flush=True)
        if not ok: fail.append(what)

    atomic = cmd("CONFIG", "GET", "atomic")
    print("atomic_groups arm: writes=%s saves=%d %r" % (WRITE, SAVES, atomic), flush=True)
    need(atomic in ([b"atomic", b"0"], [b"atomic", b"1"]), "purpose boot exposes atomic knob")
    if WRITE == "exec":
        need(atomic == [b"atomic", b"0"],
             "EXEC arm runs at the DEFAULT atomic 0 (EXEC force-admits a group anyway)")
    else:
        need(atomic == [b"atomic", b"1"], "MSET arm runs at atomic 1")
    cmd("FLUSHALL")

    # geometry oracle: a same-owner "cross-shard" group cannot tear and would gate nothing
    spans = [len({cmd("DEBUG", "SHARD", ag_key(g, sl)) for sl in range(AG_SLOTS)})
             for g in range(AG_GROUPS)]
    need(min(spans) >= 2, "every group spans >1 shard (min=%d avg=%.2f)"
                          % (min(spans), sum(spans)/len(spans)))

    pending = 0
    for g in range(AG_GROUPS):
        for sl in range(AG_SLOTS):
            s.sendall(enc(["SET", ag_key(g, sl), ag_val(g, sl, 0)]))
            pending += 1
            if pending == 200:
                for _ in range(200): rr(f)
                pending = 0
    for _ in range(pending): rr(f)

    stop = threading.Event()
    tally = {"writes": 0, "reads": 0, "torn_reads": 0, "errors": 0, "last": ""}
    lock = threading.Lock()

    def ag_blobs(idx):
        """Pre-render every byte a writer sends, so the loop is pure socket work and the server,
        not python, is the thing under load. Generations cycle; a tear is two cycle values in one
        group, and consecutive generations always differ."""
        mine = [g for g in range(AG_GROUPS) if g % AG_CONNS == idx]
        out = []
        for base in range(AG_GENS):
            blob, count = b"", 0
            for r in range(AG_ROUNDS):
                gen = 1 + (base + r) % AG_GENS
                for g in mine:
                    if WRITE == "exec":
                        blob += enc(["MULTI"])
                        for sl in range(AG_SLOTS):
                            blob += enc(["SET", ag_key(g, sl), ag_val(g, sl, gen)])
                        blob += enc(["EXEC"])
                    else:
                        args = ["MSET"]
                        for sl in range(AG_SLOTS):
                            args += [ag_key(g, sl), ag_val(g, sl, gen)]
                        blob += enc(args)
                    count += 1
            out.append((blob, count))
        return out

    UNIT = (b"+OK\r\n" + b"+QUEUED\r\n" * AG_SLOTS + b"*%d\r\n" % AG_SLOTS + b"+OK\r\n" * AG_SLOTS
            if WRITE == "exec" else b"+OK\r\n")

    def ag_writer(blobs):
        if not blobs or blobs[0][1] == 0: return
        w, wf = conn()
        w.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        n, i = 0, 0
        try:
            while not stop.is_set():
                blob, count = blobs[i % len(blobs)]; i += 1
                w.sendall(blob)
                want, got = len(UNIT) * count, b""
                while len(got) < want:
                    chunk = wf.read(want - len(got))
                    if not chunk: raise EOFError("server closed")
                    got += chunk
                if got != UNIT * count: raise AssertionError("reply %r" % got[:60])
                n += count
        except Exception as exc:
            with lock: tally["errors"] += 1; tally["last"] = repr(exc)
        finally:
            with lock: tally["writes"] += n
            w.close()

    def ag_reader():
        r, rf = conn()
        prng = random.Random(7)
        n, bad = 0, 0
        try:
            while not stop.is_set():
                g = prng.randrange(AG_GROUPS)
                r.sendall(enc(["MGET"] + [ag_key(g, sl) for sl in range(AG_SLOTS)]))
                vals = rr(rf)
                n += 1
                if len({ag_gen(v) for v in vals if v is not None}) > 1: bad += 1
        except Exception as exc:
            with lock: tally["errors"] += 1; tally["last"] = repr(exc)
        finally:
            with lock: tally["reads"] += n; tally["torn_reads"] += bad
            r.close()

    # A tree with no cut instrumentation reports -1 here, which fails the counter rows below
    # instead of dying with a traceback -- the FAIL transcript is the point of this arm.
    def info_int(name):
        v = info_field(name)
        return int(v) if v is not None else -1
    groups_before = info_int("atomic_groups")
    armed_before = info_int("snapshot_cuts_armed")
    waited_before = info_int("snapshot_cuts_waited")
    rendered = [ag_blobs(i) for i in range(AG_CONNS)]
    workers = [threading.Thread(target=ag_writer, args=(rendered[i],)) for i in range(AG_CONNS)]
    workers.append(threading.Thread(target=ag_reader))
    for t in workers: t.start()
    time.sleep(0.6)
    torn_total = 0
    for i in range(SAVES):
        t0 = time.time()
        reply = cmd("SAVE")
        if reply != b"+OK": fail.append("SAVE #%d replied %r" % (i, reply))
        copy = "%s.cut%d" % (DUMP, i)
        shutil.copyfile(DUMP, copy)
        torn, present, keys, examples = ag_file_torn(copy)
        torn_total += torn
        print("    cut#%d %.3fs keys=%d groups=%d torn=%d %s"
              % (i, time.time()-t0, keys, present, torn,
                 ("e.g. %s" % examples) if examples else ""), flush=True)
        if present != AG_GROUPS: fail.append("cut #%d captured %d/%d groups" % (i, present, AG_GROUPS))
        os.unlink(copy)
        time.sleep(0.2)
    stop.set()
    for t in workers: t.join()
    groups = info_int("atomic_groups") - groups_before
    armed = info_int("snapshot_cuts_armed") - armed_before
    waited = info_int("snapshot_cuts_waited") - waited_before
    drained = info_int("snapshot_groups_drained")

    print("  storm: writes=%d live_mget_reads=%d live_torn_reads=%d errors=%d %s"
          % (tally["writes"], tally["reads"], tally["torn_reads"], tally["errors"], tally["last"]),
          flush=True)
    print("  counters: atomic_groups+=%d cuts_armed+=%d cuts_waited+=%d groups_drained=%d"
          % (groups, armed, waited, drained), flush=True)

    need(tally["errors"] == 0, "storm ran clean")
    need(tally["writes"] > 10000, "storm actually loaded the server (%d group writes)" % tally["writes"])
    need(groups > 0, "the atomic group lane fired (%d groups admitted)" % groups)
    need(tally["reads"] > 200, "live reader actually read (%d MGETs)" % tally["reads"])
    need(tally["torn_reads"] == 0,
         "CONTROL: live MGET never saw a torn group (%d torn)" % tally["torn_reads"])
    need(armed == SAVES, "every cut armed the atomic barrier (%d of %d)" % (armed, SAVES))
    if WRITE == "mset":
        # FIRED-proof. Kept on the arm whose depth reliably parks the drain; the EXEC arm reports
        # the same counter but does not gate on it, because its lower group rate can legitimately
        # leave nothing in flight by the time the cut samples.
        need(waited > 0, "the group drain actually blocked on something (%d of %d cuts)"
                         % (waited, SAVES))
    need(torn_total == 0, "NO half-applied group in any snapshot file (%d torn)" % torn_total)

    print("ATOMIC_GROUP_CUT", "PASS" if not fail else "FAIL: %s" % fail[:3], flush=True)
    sys.exit(1 if fail else 0)
if MODE == "save":
    B=400
    for i in range(0, len(KEYS), B):
        s.sendall(b"".join(enc(["SET",k,v]) for k,v in KEYS[i:i+B]))
        for _ in range(min(B,len(KEYS)-i)): rr(f)
    for k,v in TTLK:
        s.sendall(enc(["SET",k,v,"EX","5000"]))
    for _ in TTLK: rr(f)
    # short-TTL keys that expire BEFORE the cut: must be absent from dump
    for i in range(50):
        s.sendall(enc(["SET","gone:%d"%i,"g","PX","150"]))
    for _ in range(50): rr(f)
    time.sleep(0.5)
    print("BGSAVE:", cmd("BGSAVE"))
    # mutations begin only after the BGSAVE reply => ALL are post-cut. The dump must show none.
    m, fm = conn()
    def mc(*a): m.sendall(enc(list(a))); return rr(fm)
    for i in range(0, 6000, 2): mc("SET", "pk:%d"%i, "MUTATED-%d"%i)
    for i in range(100): mc("DEL", "pk:%d"%(i*3+1))
    for i in range(800): mc("SET", "post:%d"%i, "newkey%d"%i)
    t0=time.time()
    while info_field("rdb_bgsave_in_progress") != b"0" and time.time()-t0 < 90: time.sleep(0.2)
    print("bgsave done in %.1fs (mutation storm raced the capture)" % (time.time()-t0))
    print("last_save_time:", info_field("last_save_time"))
elif MODE == "verify_cut":
    # the dump is the state at the cut: every original pk value, no MUTATED, no post:*, no gone:*
    bad=0; first=None
    for k, v in KEYS:
        got = cmd("GET", k)
        if got != v.encode():
            bad+=1
            if first is None: first=(k, v[:24], got[:24] if got else got)
    ttl_ok = sum(1 for k,_ in TTLK[:50] if (lambda t: t!=b":-2" and int(t[1:])>4000)(cmd("TTL",k)))
    post = sum(1 for i in range(800) if cmd("GET","post:%d"%i) is not None)
    gone = sum(1 for i in range(50) if cmd("GET","gone:%d"%i) is not None)
    print("cut verify: mismatch=%d (first=%s) ttl=%d/50 post-cut-leaked=%d pre-cut-expired=%d"
          % (bad, first, ttl_ok, post, gone))
    ok = bad==0 and ttl_ok==50 and post==0 and gone==0
    print("VERIFY_CUT", "PASS" if ok else "FAIL")
    if ok: print("SAVE-on-loaded:", cmd("SAVE"))
    sys.exit(0 if ok else 1)
elif MODE == "verify_save":
    bad = sum(1 for k,v in KEYS[::137] if cmd("GET",k) != v.encode())
    print("VERIFY_SAVE", "PASS" if bad==0 else "FAIL (%d)"%bad)
    sys.exit(1 if bad else 0)   # was inverted: exited 0 exactly when keys MISmatched
