#!/usr/bin/env bash
# ============================================================================
# feature_sweep.sh — full-feature correctness + stress sweep for the THredis
# 2s-numa-shared-kv fork (tree: stable-w2 @ 52c760720).
#
# Usage:
#   SMOKE=1 ./feature_sweep.sh      # ~12-16 min, 1 rep, short cells
#   ./feature_sweep.sh              # full, ~50-80 min
#
# Output:
#   /tmp/tomo_pfjob/feature_sweep.tsv
#     columns: section <TAB> test <TAB> config <TAB> result <TAB> detail
#     result in {PASS, FAIL, KNOWN, SUSPECT}
#   per-section logs + per-boot server logs (PRESERVED, never truncated):
#     /tmp/tomo_pfjob/feature_sweep_logs/
#
# BOX DISCIPLINE (encoded, do not relax):
#   - never pkill/pgrep by pattern; all lifecycle is by OUR recorded PIDs only
#   - single instance via flock
#   - before every measurement: assert OUR pid serves OUR port (INFO process_id)
#   - a port already in use => the cell is aborted (we never touch foreign servers)
#   - every wait is `wait $PID`-or-timeout-loop; no bare `wait`
#   - memtier "Totals" LAST column is KB/sec, NOT errors; we read col2 = Ops/sec
#   - INFO fields compared within one test are parsed from ONE INFO call
#   - every checker gets a positive control where feasible (comparator self-test
#     injects a deliberate divergence and must catch it, or section A is SUSPECT)
# ============================================================================
set -u -o pipefail

JOB=/tmp/tomo_pfjob
TREE=${TREE:-$JOB/stable-w2}
FORKSRV=${TOMO_BIN:-$TREE/src/redis-server}
ORACLESRV=${ORACLESRV:-/home/user/Projects/redis/src/redis-server}
# CLI must follow the binary under test. Defaulting it to $TREE/src/redis-cli silently paired a
# freshly-built server with a redis-cli from whatever stale worktree TREE happened to point at
# (observed: rev 652deda9b while testing a much newer binary).
CLI=${CLI:-$(dirname "$FORKSRV")/redis-cli}
[ -x "$CLI" ] || CLI=$TREE/src/redis-cli
[ -x "$CLI" ] || CLI=/home/user/Projects/redis/src/redis-cli

TSV="${TOMO_RESULT_FILE:-$JOB/feature_sweep.tsv}"
LOGDIR=$JOB/feature_sweep_logs
# ee451 2026-07-29: PER-RUN log identity. Server logs were named srv_<BOOTSEQ>_<kind>_p<port>.log
# and BOOTSEQ restarts at 0 every run, so run N and run N+1 both wrote srv_14_fork_p7791.log -- and
# boot_srv opens it with `>>` while redis is also told `--logfile` the same path. Nothing ever
# truncated it. Measured: ONE such file held FOURTEEN boot banners and two assertion records.
# crash_scan then greps that accumulated history, so a crash that happened once at 03:57 on 28 Jul
# was re-reported as a fresh FAIL by the 04:22, 08:57 and 12:49 runs -- three false product failures
# from one real event, and it would have gone on failing forever. This is the same stale-artifact
# trap preflight.sh already guards with `rm -f "$2"` ("never grade a STALE result file") and
# stress_reclaim guards with `: > $J/stress.log`.
# A per-run id keeps BOTH properties the header asks for: logs are still never truncated (so a
# post-mortem is intact), and no run can ever scan another run's log.
RUNID=${RUNID:-$(date -u +%Y%m%d_%H%M%S)_$$}
WORK=$JOB/feature_sweep_work
PY=$WORK/oracle_helper.py

SMOKE=${SMOKE:-0}
FORK_PORT=${FORK_PORT:-7791}
ORACLE_PORT=${ORACLE_PORT:-7792}
SRV_CORES=${SRV_CORES:-}    # e.g. "0-7"  (taskset for servers; empty = no taskset)
LG_CORES=${LG_CORES:-}      # e.g. "8-15" (taskset for memtier / pipe loaders)
SEED=${SEED:-3225208}       # fixed stream seed
# report the ACTUAL revision under test, not a hardcoded one (it read 52c760720 for every run,
# which made every log line about "which build was this?" actively misleading)
TREE_REV=${TREE_REV:-$(git -C "$TREE" rev-parse --short HEAD 2>/dev/null || echo unknown)}

if [ "$SMOKE" = "1" ]; then
    A_OPS=12000; B_OPS=1500; STRESS_T=60; FLIP_T=25; E_REPS=5
else
    A_OPS=50000; B_OPS=4000; STRESS_T=300; FLIP_T=45; E_REPS=20
fi

# fork default topology (mandatory knobs) + politeness (float, no core pinning)
DEF_TOPO=(--tomokv-thread-io 2 --tomokv-thread-ex 2)
FORK_COMMON=(--bind 127.0.0.1 --save '' --appendonly no --protected-mode no
             --enable-debug-command yes --busy-reply-threshold 1000
             --tomokv-pin-mode float)
ORACLE_COMMON=(--bind 127.0.0.1 --save '' --appendonly no --protected-mode no
               --enable-debug-command yes)

GUARD_MSG="not yet supported with tomokv sharding"
MULTI_MSG="is not supported with tomokv sharding"
BUSY_MSG="another script is running"
CRASH_RE='REDIS BUG REPORT|ASSERTION FAILED|Segmentation fault|SIGSEGV|SIGABRT|SIGBUS|AddressSanitizer|Guru Meditation'

# ---------------------------------------------------------------------------
# infra
# ---------------------------------------------------------------------------
exec 9>/tmp/feature_sweep.lock
flock -n 9 || {
  # HARNESS FIX 2026-07-27: this used to abort BEFORE writing anything, so preflight was left
  # grading a STALE feature_sweep.tsv from a previous run -- in one case results 6 hours old,
  # including a crash row for a panic that had since been fixed. Make the abort self-evident in
  # the RESULT FILE, not just on stderr, so it can never be mistaken for a real verdict.
  echo "A	lock-held	-	FAIL	another feature_sweep holds the flock; THIS RUN PRODUCED NO RESULTS" > "${TOMO_RESULT_FILE:-$JOB/feature_sweep.tsv}"
  echo "another feature_sweep is running; abort" >&2
  exit 1; }

mkdir -p "$LOGDIR" "$WORK"
NFAIL=0; NSUSPECT=0; BOOTSEQ=0
declare -a OUR_PIDS=()
BOOT_PID=""; LAST_SRV_LOG=""
SECLOG=$LOGDIR/sc_main.log
A_ORACLE_PID=""; B_LAST_PID=""
D_RELOAD_RESULT=""; D_RELOAD_DETAIL=""

if [ ! -x "$FORKSRV" ]; then echo "fork binary missing: $FORKSRV" >&2; exit 1; fi
if [ ! -x "$ORACLESRV" ]; then echo "oracle binary missing: $ORACLESRV" >&2; exit 1; fi
command -v python3 >/dev/null || { echo "python3 missing (comparator needs it)" >&2; exit 1; }

{ printf '# feature_sweep tree=%s rev=%s smoke=%s date=%s\n' "$TREE" "$TREE_REV" "$SMOKE" "$(date -Is)"
  printf '# section\ttest\tconfig\tresult\tdetail\n'; } > "$TSV"

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$SECLOG" >&2; }

row() { # section test config result detail
    local d=${5//$'\t'/ }; d=${d//$'\n'/ }
    printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$d" >> "$TSV"
    case "$4" in FAIL) NFAIL=$((NFAIL+1));; SUSPECT) NSUSPECT=$((NSUSPECT+1));; esac
    log "[$1] $2 ($3) -> $4 :: $d"
}

tcli() { # port cmd...
    local p=$1; shift
    timeout 20 "$CLI" -p "$p" "$@" 2>&1
}

port_free() { ! timeout 2 "$CLI" -p "$1" -t 1 ping >/dev/null 2>&1; }

# assert exactly-our server on port: INFO process_id must equal our pid
assert_server() { # port pid -> 0 ok
    local info pid
    info=$(tcli "$1" INFO server) || return 1
    pid=$(printf '%s' "$info" | tr -d '\r' | awk -F: '/^process_id:/{print $2}')
    [ "$pid" = "$2" ]
}

# boot_srv: NOT called in a subshell — sets globals BOOT_PID and LAST_SRV_LOG.
boot_srv() { # kind(fork|oracle) port dir extra-args... ; rc!=0 on failure
    local kind=$1 port=$2 dir=$3; shift 3
    BOOT_PID=""; BOOTSEQ=$((BOOTSEQ+1))
    # unique PER RUN as well as per boot => preserved, and never re-scanned by a later run
    local slog=$LOGDIR/srv_${RUNID}_${BOOTSEQ}_${kind}_p${port}.log
    mkdir -p "$dir"
    if ! port_free "$port"; then
        log "BOOT-ABORT: port $port already serving (foreign server; will not touch)"
        return 1
    fi
    local bin; local -a args
    if [ "$kind" = fork ]; then bin=$FORKSRV; args=("${FORK_COMMON[@]}"); else bin=$ORACLESRV; args=("${ORACLE_COMMON[@]}"); fi
    local -a ts=()
    [ -n "$SRV_CORES" ] && ts=(taskset -c "$SRV_CORES")
    "${ts[@]}" "$bin" --port "$port" --dir "$dir" --logfile "$slog" "${args[@]}" "$@" >>"$slog" 2>&1 &
    local pid=$!
    OUR_PIDS+=("$pid")
    local i
    for i in $(seq 1 100); do
        if ! kill -0 "$pid" 2>/dev/null; then log "BOOT-FAIL($kind): died, log=$slog"; return 1; fi
        if timeout 2 "$CLI" -p "$port" -t 1 ping 2>/dev/null | grep -q PONG; then break; fi
        sleep 0.2
    done
    assert_server "$port" "$pid" || { log "BOOT-FAIL($kind): port $port not served by pid $pid"; return 1; }
    # identity control: fork must expose tomokv INFO fields, oracle must not
    local st; st=$(tcli "$port" INFO stats)
    if [ "$kind" = fork ]; then
        printf '%s' "$st" | grep -q tomokv_ex_queue_depth || { log "BOOT-FAIL: fork identity check (no tomokv fields)"; return 1; }
    else
        printf '%s' "$st" | grep -q tomokv_ex_queue_depth && { log "BOOT-FAIL: oracle identity check (has tomokv fields?)"; return 1; }
    fi
    BOOT_PID=$pid
    LAST_SRV_LOG=$slog
    return 0
}

# is_our_server: PID-reuse guard — only ever signal a pid whose comm is one of the binaries THIS
# SUITE ACTUALLY LAUNCHED.
#
# It used to hardcode "redis-server", and that hung preflight for 8 hours (preflight8, 2026-08-03).
# Two safety mechanisms collided: preflight stages the binary under test as a PRIVATE name
# (/tmp/tomo_pfbin_<pid>/redis-pf) precisely so other sessions' `pkill -9 -x redis-server` cannot
# reap it — and that rename silently disarmed this guard. stop_srv then took the path
#     is_our_server -> false  =>  kill -TERM never sent
#     100 x kill -0           =>  still alive (nothing killed it)
#     still alive, guard false =>  kill -9 never sent either
#     wait "$pid"             =>  child is ALIVE, blocks forever
# The comment on that wait said "our dead child: returns immediately". It was never killed.
# Evidence: every historical run in preflight_feature_sweep.sh.log used bins/stable/redis-server and
# finished in 444-1362s; the first run with bin=redis-pf never wrote a DONE line.
#
# Derive the whitelist from the binaries we run instead of naming one. comm truncates at 15 chars,
# so truncate the basenames the same way or a long private name would never match.
_comm15() { printf '%.15s' "$(basename "$1")"; }
OUR_COMMS=" $(_comm15 "$FORKSRV") $(_comm15 "$ORACLESRV") "
is_our_server() {
    local c; c=$(cat "/proc/$1/comm" 2>/dev/null) || return 1
    [ -n "$c" ] || return 1
    case "$OUR_COMMS" in *" $c "*) return 0 ;; esac
    return 1
}

stop_srv() { # pid
    local pid=${1:-} i
    [ -z "$pid" ] && return 0
    is_our_server "$pid" && kill -TERM "$pid" 2>/dev/null
    for i in $(seq 1 100); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    if kill -0 "$pid" 2>/dev/null && is_our_server "$pid"; then
        kill -9 "$pid" 2>/dev/null; sleep 0.3
    fi
    # NEVER `wait` on a pid that is still alive: bash blocks forever and the suite hangs instead of
    # failing. That is exactly how the comm-mismatch above burned 8 hours of a release gate. A
    # harness that hangs yields no verdict at all, which is strictly worse than one that fails.
    if kill -0 "$pid" 2>/dev/null; then
        log "stop_srv: pid $pid (comm=$(cat "/proc/$pid/comm" 2>/dev/null), allowed=$OUR_COMMS) SURVIVED teardown — refusing to wait on a live child"
        return 1
    fi
    wait "$pid" 2>/dev/null   # confirmed dead above, so this returns immediately
    return 0
}

cleanup() {
    local p
    for p in "${OUR_PIDS[@]:-}"; do
        [ -n "$p" ] && is_our_server "$p" && kill -9 "$p" 2>/dev/null
    done
    return 0
}
trap cleanup EXIT
# abort paths (^C / kill / hangup) must still run cleanup: route them through EXIT
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM

lg_run() { # run a load-gen command, optionally pinned
    if [ -n "$LG_CORES" ]; then taskset -c "$LG_CORES" "$@"; else "$@"; fi
}

crash_scan() { # logfile -> echoes matches (empty = clean)
    # positive control: a scan over a missing/empty log must NOT certify "clean" —
    # every boot writes a banner, so an empty file means the check is vacuous.
    if [ ! -s "$1" ]; then printf 'SERVER-LOG-MISSING-OR-EMPTY (%s): cannot certify clean\n' "$1"; return 0; fi
    grep -aE "$CRASH_RE" "$1" 2>/dev/null | head -3
}

info_field() { # "$info_blob" field -> value (single-INFO-call parsing)
    printf '%s' "$1" | tr -d '\r' | awk -F: -v f="$2" '$1==f{print $2; exit}'
}

# a DEBUG DIGEST reply is exactly 40 hex chars and not all-zero; anything else
# (error text, "Could not connect", empty) must never pass a digest check.
is_digest() {
    printf '%s' "$1" | grep -qE '^[0-9a-f]{40}$' || return 1
    [ "$1" != "0000000000000000000000000000000000000000" ]
}

# ---------------------------------------------------------------------------
# embedded python helper: exact-xxh64 keygen + RESP oracle comparator
# ---------------------------------------------------------------------------
cat > "$PY" <<'PYEOF'
#!/usr/bin/env python3
# oracle_helper.py — deterministic stream generator + lockstep comparator for
# the THredis fork vs stock Redis. Speaks RESP directly (binary-safe).
import sys, os, socket, argparse, random, time, pickle

M=(1<<64)-1
P1=0x9E3779B185EBCA87;P2=0xC2B2AE3D27D4EB4F;P3=0x165667B19E3779F9
P4=0x85EBCA77C2B2AE63;P5=0x27D4EB2F165667C5
def _rl(x,r):return ((x<<r)|(x>>(64-r)))&M
def _rd(a,i):a=(a+i*P2)&M;a=_rl(a,31);return (a*P1)&M
def _mg(a,v):v=_rd(0,v);a^=v;return (a*P1+P4)&M
def xxh64(d):
    # byte-exact mirror of src/server.c xxh64 (seed 0)
    n=len(d);p=0
    if n>=32:
        v1=(P1+P2)&M;v2=P2;v3=0;v4=(0-P1)&M
        while p+32<=n:
            v1=_rd(v1,int.from_bytes(d[p:p+8],'little'));p+=8
            v2=_rd(v2,int.from_bytes(d[p:p+8],'little'));p+=8
            v3=_rd(v3,int.from_bytes(d[p:p+8],'little'));p+=8
            v4=_rd(v4,int.from_bytes(d[p:p+8],'little'));p+=8
        h=(_rl(v1,1)+_rl(v2,7)+_rl(v3,12)+_rl(v4,18))&M
        h=_mg(h,v1);h=_mg(h,v2);h=_mg(h,v3);h=_mg(h,v4)
    else:h=P5
    h=(h+n)&M
    while p+8<=n:
        h^=_rd(0,int.from_bytes(d[p:p+8],'little'));h=(_rl(h,27)*P1+P4)&M;p+=8
    if p+4<=n:
        h^=(int.from_bytes(d[p:p+4],'little')*P1)&M;h=(_rl(h,23)*P2+P3)&M;p+=4
    while p<n:
        h^=(d[p]*P5)&M;h=(_rl(h,11)*P1)&M;p+=1
    h^=h>>33;h=(h*P2)&M;h^=h>>29;h=(h*P3)&M;h^=h>>32
    return h
def bucket(k):return xxh64(k)&16383
def worker(k,W):return (bucket(k)*W)//16384   # mirrors ex_bucket_table init: (b*W)/16384

# positive control for the mirror itself: canonical XXH64 seed-0 vectors PLUS two
# >=32-byte inputs cross-checked against the compiled server.c routine (covers the
# 4-lane main loop, the 8/4-byte tails, and the final avalanche). A drifted mirror
# would silently degrade hot-key targeting into vacuous coverage — fail loudly instead.
def xxh64_selfcheck():
    return (xxh64(b'')==0xEF46DB3751D8E999 and xxh64(b'a')==0xD24EC4F1A98C6E5B and
            xxh64(b'abc')==0x44BC2CF5AD770999 and xxh64(b'hot:0')==0x161254E3E3D96BF8 and
            xxh64(bytes(range(64)))==0xF7C67301DB6713F0 and
            xxh64(bytes(range(37)))==0xD93FA2DFEE5C24C9 and worker(b'hot:0',2)==1)

class R:
    def __init__(s,port,timeout=30):
        s.s=socket.create_connection(('127.0.0.1',port),timeout=timeout)
        s.s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        s.f=s.s.makefile('rb')
    def enc(s,args):
        o=[b'*%d\r\n'%len(args)]
        for a in args:
            if isinstance(a,int):a=str(a).encode()
            elif isinstance(a,str):a=a.encode()
            o+= [b'$%d\r\n'%len(a),a,b'\r\n']
        return b''.join(o)
    def cmd(s,*a):s.s.sendall(s.enc(list(a)));return s.read()
    def pipeline(s,ops):
        s.s.sendall(b''.join(s.enc(o) for o in ops))
        return [s.read() for _ in ops]
    def read(s):
        ln=s.f.readline()
        if not ln:raise IOError('conn closed')
        t=ln[0:1];b=ln[1:-2]
        if t==b'+':return b
        if t==b'-':return ('err',b.decode('utf-8','replace'))
        if t==b':':return int(b)
        if t==b'$':
            n=int(b)
            if n==-1:return None
            d=s.f.read(n+2);return d[:-2]
        if t==b'*':
            n=int(b)
            if n==-1:return None
            return [s.read() for _ in range(n)]
        raise IOError('bad resp %r'%ln)

SIZES=[1,44,45,170,192,255,4096,65536]
SORTSET={b'SINTER',b'SUNION',b'SDIFF',b'SMEMBERS',b'KEYS'}
TTL_S={b'TTL'};TTL_MS={b'PTTL'}

def norm(cmd,rep):
    if isinstance(rep,tuple) and rep[0]=='err':
        return ('err',rep[1].split(' ',1)[0])      # error CLASS only (version-tolerant text)
    c=cmd.upper()
    if c in SORTSET and isinstance(rep,list):
        return sorted((x if x is not None else b'') for x in rep)
    if c==b'HGETALL' and isinstance(rep,list):
        return sorted((rep[i],rep[i+1]) for i in range(0,len(rep),2))
    return rep

def rep_eq(cmd,a,b):
    c=cmd.upper()
    if c in TTL_S or c in TTL_MS:
        if isinstance(a,int) and isinstance(b,int):
            if a<0 or b<0: return a==b
            return abs(a-b)<= (3 if c in TTL_S else 3000)
        return a==b
    return norm(cmd,a)==norm(cmd,b)

# ---------------- generator ----------------
def load_lines(path):
    if not path or not os.path.exists(path):return []
    with open(path,'rb') as f:return [l.rstrip(b'\n') for l in f if l.strip()]

def gen_stream(seed,nops,W,reduced,hot,sb):
    rng=random.Random(seed)
    BLOB=bytes(rng.randrange(256) for _ in range(1<<20))
    def val(sz):
        if sz>len(BLOB):sz=len(BLOB)
        o=rng.randrange(0,len(BLOB)-sz+1) if sz<len(BLOB) else 0
        stamp=(b'%08x'%rng.randrange(1<<32))
        v=stamp+BLOB[o:o+sz]
        return v[:sz]
    sizes=[s for s in SIZES if (not reduced or s<=4096)]
    gk=[b's:%d'%i for i in range(360)]
    bink=[]
    for i in range(24):
        bink.append(b'b:'+bytes([i])+b'\x00\xff'+bytes(rng.randrange(256) for _ in range(rng.randrange(1,12))))
    ctr=[b'c:%d'%i for i in range(24)]
    hk=[b'h:%d'%i for i in range(36)];sk=[b'st:%d'%i for i in range(36)]
    zk=[b'z:%d'%i for i in range(36)];lk=[b'l:%d'%i for i in range(36)]
    sa=[b'sa:%d'%i for i in range(8)];za=[b'za:%d'%i for i in range(8)]
    li0=b'li:0'
    ops=[];inj_get=[-1]
    def emit(*a):
        ops.append([x if isinstance(x,bytes) else str(x).encode() for x in a])
    # --- seed strings (boundary sizes guaranteed >=8 keys each) ---
    for i,k in enumerate(gk):
        sz=sizes[i%len(sizes)] if i<len(sizes)*8 else rng.choice([1,8,21,44,45,100,170,192,255,700])
        if i%7==3: emit(b'SETEX',k,600+rng.randrange(3000),val(sz))
        else: emit(b'SET',k,val(sz))
    for k in bink: emit(b'SET',k,b'\x00'+val(rng.choice([1,44,45,255]))+b'\xff\x00')
    for k in ctr: emit(b'SET',k,rng.randrange(-1000,1000))
    for k in hot: emit(b'SET',k,val(rng.choice([8,44,170])))
    for k in sb: emit(b'SET',k,val(45))
    for k in hk:
        a=[b'HSET',k]
        for f in range(rng.randrange(2,8)): a+=[b'f%d'%f, val(rng.choice([1,44,100]))]
        emit(*a)
    for k in sk: emit(b'SADD',k,*[b'm%d'%rng.randrange(40) for _ in range(rng.randrange(2,20))])
    for k in zk:
        a=[b'ZADD',k]
        for m in range(rng.randrange(2,12)): a+=[rng.randrange(-1000,1000), b'zm%d'%rng.randrange(40)]
        emit(*a)
    for k in lk: emit(b'RPUSH',k,*[val(rng.choice([1,20,44])) for _ in range(rng.randrange(2,12))])
    for i,k in enumerate(sa): emit(b'SADD',k,*[b'e%d'%j for j in range(i,i+12)])
    for i,k in enumerate(za):
        a=[b'ZADD',k]
        for j in range(i,i+10): a+=[j*3-10, b'ze%d'%j]
        emit(*a)
    emit(b'RPUSH',li0,*[rng.randrange(-500,500) for _ in range(20)])
    # --- random mutations ---
    budget=max(0,nops-len(ops)-1200)
    anyk=gk+bink+list(hot)
    W_=[  # (weight, fn)
        (14,lambda: emit(b'GET',rng.choice(anyk))),
        (8, lambda: emit(b'SET',rng.choice(gk),val(rng.choice(sizes)))),
        (3, lambda: emit(b'APPEND',rng.choice(gk[:24]),val(rng.randrange(1,64)))),
        (3, lambda: emit(b'SETRANGE',rng.choice(gk[24:48]),rng.randrange(0,300),val(rng.randrange(1,32)))),
        (3, lambda: emit(b'GETRANGE',rng.choice(gk),rng.randrange(0,64),rng.randrange(-1,300))),
        (4, lambda: emit(b'INCR',rng.choice(ctr))),
        (2, lambda: emit(b'DECR',rng.choice(ctr))),
        (3, lambda: emit(b'INCRBY',rng.choice(ctr),rng.randrange(-500,500))),
        (2, lambda: emit(b'SETNX',rng.choice(gk),val(20))),
        (1, lambda: emit(b'SETNX',b'nx:%d'%rng.randrange(200),val(20))),
        (2, lambda: emit(b'GETSET',rng.choice(gk),val(rng.choice([1,44,100])))),
        (1, lambda: emit(b'GETDEL',rng.choice(gk))),
        (2, lambda: emit(b'SETEX',rng.choice(gk),600+rng.randrange(3000),val(44))),
        (3, lambda: emit(b'EXPIRE',rng.choice(anyk),600+rng.randrange(3000))),
        (2, lambda: emit(b'TTL',rng.choice(anyk))),
        (2, lambda: emit(b'PTTL',rng.choice(anyk))),
        (1, lambda: emit(b'PERSIST',rng.choice(anyk))),
        (2, lambda: emit(b'TYPE',rng.choice(anyk+sk+zk))),
        (2, lambda: emit(b'EXISTS',*rng.sample(anyk,rng.randrange(2,6)))),
        (1, lambda: emit(b'DEL',rng.choice(gk))),
        (1, lambda: emit(b'DEL',*rng.sample(anyk,rng.randrange(2,5)))),
        (1, lambda: emit(b'UNLINK',*rng.sample(anyk,rng.randrange(2,5)))),
        (4, lambda: emit(b'SADD',rng.choice(sk),*[b'm%d'%rng.randrange(40) for _ in range(rng.randrange(1,6))])),
        (2, lambda: emit(b'SREM',rng.choice(sk),*[b'm%d'%rng.randrange(40) for _ in range(rng.randrange(1,4))])),
        (2, lambda: emit(b'SMEMBERS',rng.choice(sk))),
        (3, lambda: emit(b'SINTER',*rng.sample(sa,rng.randrange(2,5)))),
        (2, lambda: emit(b'SUNION',*rng.sample(sa,rng.randrange(2,5)))),
        (2, lambda: emit(b'SDIFF',*rng.sample(sa,rng.randrange(2,4)))),
        (2, lambda: (lambda ks: emit(b'SINTERCARD',len(ks),*ks))(rng.sample(sa,rng.randrange(2,4)))),
        (4, lambda: (lambda k: emit(b'ZADD',k,rng.randrange(-1000,1000),b'zm%d'%rng.randrange(40)))(rng.choice(zk))),
        (3, lambda: emit(b'ZRANGE',rng.choice(zk),0,-1,*([b'WITHSCORES'] if rng.random()<0.5 else []))),
        (2, lambda: (lambda ks: emit(b'ZINTER',len(ks),*ks,*([b'WITHSCORES'] if rng.random()<0.5 else [])))(rng.sample(za,rng.randrange(2,4)))),
        (2, lambda: (lambda ks: emit(b'ZINTERCARD',len(ks),*ks))(rng.sample(za,rng.randrange(2,4)))),
        (4, lambda: (lambda k: emit(b'HSET',k,b'f%d'%rng.randrange(10),val(rng.choice([1,44,100]))))(rng.choice(hk))),
        (2, lambda: emit(b'HDEL',rng.choice(hk),b'f%d'%rng.randrange(10))),
        (3, lambda: emit(b'HGETALL',rng.choice(hk))),
        (3, lambda: emit(b'LPUSH',rng.choice(lk),val(rng.choice([1,20,44])))),
        (3, lambda: emit(b'LRANGE',rng.choice(lk),0,rng.randrange(-1,20))),
        (1, lambda: emit(b'SORT',li0)),
        (1, lambda: emit(b'GET',rng.choice(sk))),                     # WRONGTYPE poke
        (1, lambda: emit(b'SADD',rng.choice(gk),b'x')),               # WRONGTYPE poke
        # xshard extras (ported two-hop / stores)
        (1, lambda: (emit(b'SET',b'r:src%d'%rng.randrange(30),val(30)),
                     emit(b'RENAME',b'r:src%d'%rng.randrange(30),b'r:dst%d'%rng.randrange(30)))),
        (1, lambda: emit(b'RENAMENX',b'r:dst%d'%rng.randrange(30),b'r:nx%d'%rng.randrange(30))),
        (1, lambda: emit(b'COPY',rng.choice(gk),b'cp:%d'%rng.randrange(40),b'REPLACE')),
        (1, lambda: emit(b'SMOVE',rng.choice(sa),rng.choice(sa),b'e%d'%rng.randrange(20))),
        (1, lambda: emit(b'LMOVE',rng.choice(lk),rng.choice(lk),b'LEFT',b'RIGHT')),
        (1, lambda: (lambda ks: emit(b'SINTERSTORE',b'ss:%d'%rng.randrange(12),*ks))(rng.sample(sa,2))),
        (1, lambda: emit(b'ZUNIONSTORE',b'zs:%d'%rng.randrange(12),2,rng.choice(za),rng.choice(za))),
    ]
    tot=sum(w for w,_ in W_)
    marked=False
    for i in range(budget):
        r=rng.randrange(tot);acc=0
        for w,fn in W_:
            acc+=w
            if r<acc: fn();break
        if not marked and i>budget*0.6 and ops and ops[-1][0]==b'GET':
            inj_get[0]=len(ops)-1;marked=True
    # --- multi-key phase (incl >64-keys-per-shard shapes on the hot pool) ---
    for sz in (2,8,32,64):
        for _ in range(4):
            emit(b'MGET',*rng.sample(anyk,min(sz,len(anyk))))
    for _ in range(3):
        emit(b'MGET',*rng.sample(anyk,min(150,len(anyk))))
    for _ in range(6):
        emit(b'MGET',*rng.sample(list(hot),min(100,len(hot))))        # >64 keys on ONE shard
    for _ in range(4):
        a=[b'MSET']
        for k in rng.sample(anyk,rng.randrange(2,32)): a+=[k,val(rng.choice([1,44,170]))]
        emit(*a)
    a=[b'MSET']
    for k in list(hot)[:80]: a+=[k,val(44)]
    emit(*a)                                                          # >64/shard write wave
    a=[b'MSETNX']
    for i in range(6): a+=[b'mn:%d'%i,val(20)]
    emit(*a); emit(*a)                                                # 1 then 0
    for k in sb: emit(b'GET',k)                                       # same-BUCKET collision reads
    if len(hot)>=10: emit(b'DEL',*random.Random(seed+1).sample(list(hot),10))
    emit(b'EXISTS',*rng.sample(anyk,8))
    emit(b'UNLINK',*rng.sample(anyk,6))
    # --- ttl tail ---
    for k in rng.sample(anyk,40): emit(b'EXPIRE',k,600+rng.randrange(3000))
    for k in rng.sample(anyk,10): emit(b'PERSIST',k)
    for k in rng.sample(anyk,15): emit(b'TTL',k)
    for k in rng.sample(anyk,15): emit(b'PTTL',k)
    if inj_get[0]<0:
        emit(b'GET',gk[0]);inj_get[0]=len(ops)-1
    return ops,inj_get[0]

# ---------------- state readback ----------------
def enum_keys(r,mode):
    # NB: both modes dedup — the SCAN contract allows returning a key more than
    # once; comparing raw lists would false-diff a legal duplicate against the
    # oracle. Keyspaces are sets; compare them as sets (sorted for determinism).
    if mode=='keys':
        ks=r.cmd(b'KEYS',b'*')
        return sorted(set(ks if isinstance(ks,list) else []))
    out=[];cur=b'0';it=0
    while True:
        rep=r.cmd(b'SCAN',cur,b'COUNT',b'1000')
        cur=rep[0];out+=rep[1];it+=1
        if cur==b'0' or it>20000:break
    return sorted(set(out))

def read_state(r,keys):
    st={}
    B=300
    for i in range(0,len(keys),B):
        chunk=keys[i:i+B]
        treps=r.pipeline([[b'TYPE',k] for k in chunk])
        ops=[];meta=[]
        for k,t in zip(chunk,treps):
            t=t if isinstance(t,bytes) else b'?'
            if t==b'string': ops.append([b'GET',k])
            elif t==b'list': ops.append([b'LRANGE',k,0,-1])
            elif t==b'set': ops.append([b'SMEMBERS',k])
            elif t==b'zset': ops.append([b'ZRANGE',k,0,-1,b'WITHSCORES'])
            elif t==b'hash': ops.append([b'HGETALL',k])
            else: ops.append([b'TYPE',k])
            ops.append([b'PTTL',k]);meta.append((k,t))
        reps=r.pipeline(ops)
        for j,(k,t) in enumerate(meta):
            v=reps[2*j];ttl=reps[2*j+1]
            if t==b'set' and isinstance(v,list): v=sorted(x or b'' for x in v)
            if t==b'hash' and isinstance(v,list): v=sorted((v[x],v[x+1]) for x in range(0,len(v),2))
            st[k]=(t,v,ttl if isinstance(ttl,int) else -3)
    return st

def ttl_band(a,b,tol=5000):
    if a<0 or b<0: return a==b
    return abs(a-b)<=tol

def cmp_state(fst,ost):
    diffs=[];ttlbad=0;maxsk=0
    for k in set(fst)|set(ost):
        f=fst.get(k);o=ost.get(k)
        if f is None or o is None:
            diffs.append((k,'missing',f is None,o is None));continue
        if f[0]!=o[0] or f[1]!=o[1]:
            diffs.append((k,'value',repr(f[:2])[:60],repr(o[:2])[:60]));continue
        if not ttl_band(f[2],o[2]):
            ttlbad+=1;diffs.append((k,'ttl',f[2],o[2]))
        elif f[2]>=0: maxsk=max(maxsk,abs(f[2]-o[2]))
    return diffs,ttlbad,maxsk

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('mode',choices=['compare','hotkeys','samebucket','ringdecay','snapshot','verify'])
    ap.add_argument('--fork-port',type=int,default=0)
    ap.add_argument('--oracle-port',type=int,default=0)
    ap.add_argument('--seed',type=int,default=0xC0FFEE)
    ap.add_argument('--ops',type=int,default=12000)
    ap.add_argument('--workers',type=int,default=2)
    ap.add_argument('--reduced',action='store_true')
    ap.add_argument('--enum',default='scan',choices=['scan','keys'])
    ap.add_argument('--hot-file',default='');ap.add_argument('--sb-file',default='')
    ap.add_argument('--inject',default='none',choices=['none','op','state'])
    ap.add_argument('--wid',type=int,default=1);ap.add_argument('--count',type=int,default=140)
    ap.add_argument('--snap',default='')
    a=ap.parse_args()

    if not xxh64_selfcheck():
        # keep stdout clean for the key-emitting modes (their output is consumed as keys)
        out=sys.stderr if a.mode in ('hotkeys','samebucket') else sys.stdout
        print('CHK xxh64-selftest ok=0 detail=python-xxh64-mirror-drifted-from-server.c',file=out)
        return 3
    if a.mode=='hotkeys':
        n=0;i=0
        while n<a.count and i<3000000:
            k=b'hot:%d'%i
            if worker(k,a.workers)==a.wid:
                sys.stdout.buffer.write(k+b'\n');n+=1
            i+=1
        return 0 if n==a.count else 3
    if a.mode=='samebucket':
        seen={}
        for i in range(400000):
            k=b'sbk:%d'%i;b=bucket(k)
            seen.setdefault(b,[]).append(k)
            if len(seen[b])>=a.count:
                for k2 in seen[b]:sys.stdout.buffer.write(k2+b'\n')
                return 0
        return 3
    if a.mode=='ringdecay':
        r=R(a.fork_port);m=R(a.fork_port)
        def used():
            rep=m.cmd(b'INFO',b'memory')
            for ln in rep.split(b'\r\n'):
                if ln.startswith(b'used_memory:'):return int(ln.split(b':')[1])
            return -1
        for i in range(500): r.cmd(b'SET',b'rd:%d'%i,b'x'*64)
        for _ in range(3):
            r.pipeline([[b'GET',b'rd:%d'%(i%500)] for i in range(4000)])
        m1=used()
        time.sleep(10)          # burst conn stays OPEN and idle -> decay cron shrinks its ring
        m2=used()
        print('M1=%d M2=%d DROP=%d'%(m1,m2,m1-m2))
        return 0

    hot=load_lines(a.hot_file);sb=load_lines(a.sb_file)
    if not hot:   # slow fallback (cache file missing)
        hot=[];i=0
        while len(hot)<140 and i<3000000:
            k=b'hot:%d'%i
            if worker(k,a.workers)==a.workers-1:hot.append(k)
            i+=1
    ops,inj_idx=gen_stream(a.seed,a.ops,a.workers,a.reduced,hot,sb)

    fork=R(a.fork_port)
    if a.mode=='snapshot':
        B=400
        for i in range(0,len(ops),B): fork.pipeline(ops[i:i+B])
        keys=enum_keys(fork,a.enum)
        st=read_state(fork,keys)
        with open(a.snap,'wb') as f: pickle.dump({'ts':time.time(),'st':st,'keys':keys},f)
        if len(keys)<50: print('CHK snapshot ok=0 detail=implausibly-few-keys=%d'%len(keys));return 3
        print('CHK snapshot ok=1 detail=keys=%d'%len(keys))
        return 0
    if a.mode=='verify':
        with open(a.snap,'rb') as f: snap=pickle.load(f)
        elapsed=(time.time()-snap['ts'])*1000
        keys=enum_keys(fork,a.enum)
        ok_enum = keys==snap['keys']
        print('CHK enum ok=%d detail=now=%d,snap=%d'%(1 if ok_enum else 0,len(keys),len(snap['keys'])))
        st=read_state(fork,keys)
        diffs=0;first=''
        for k in set(st)|set(snap['st']):
            f=st.get(k);o=snap['st'].get(k)
            if f is None or o is None: diffs+=1;first=first or repr(k)[:60];continue
            if f[0]!=o[0] or f[1]!=o[1]: diffs+=1;first=first or repr(k)[:60];continue
            if o[2]>=0:
                exp=o[2]-elapsed
                if f[2]<0 or abs(f[2]-exp)>8000: diffs+=1;first=first or ('ttl:'+repr(k)[:50])
            elif f[2]!=o[2]: diffs+=1;first=first or ('ttl:'+repr(k)[:50])
        print('CHK readback ok=%d detail=diffs=%d,first=%s'%(1 if diffs==0 else 0,diffs,first or '-'))
        return 0 if (ok_enum and diffs==0) else 2
    # mode == compare
    orc=R(a.oracle_port)
    opdiffs=0;applied=0;B=400;first=''
    for i in range(0,len(ops),B):
        chunk=ops[i:i+B]
        ochunk=chunk
        if a.inject=='op' and i<=inj_idx<i+B:
            k=chunk[inj_idx-i][1]
            ochunk=list(chunk);ochunk[inj_idx-i]=[b'INCR',k]   # deliberate divergence
        fr=fork.pipeline(chunk);orr=orc.pipeline(ochunk)
        for j,(op,x,y) in enumerate(zip(chunk,fr,orr)):
            applied+=1
            if not rep_eq(op[0],x,y):
                opdiffs+=1
                if opdiffs<=15:
                    d='op#%d %s fork=%s oracle=%s'%(i+j,repr(op[:3])[:90],repr(x)[:80],repr(y)[:80])
                    print(d,file=sys.stderr)
                    first=first or d[:120]
    print('CHK opcompare ok=%d detail=applied=%d,opdiffs=%d,%s'%(1 if opdiffs==0 else 0,applied,opdiffs,(first.replace('\t',' ').replace('detail=','d=') or '-')))
    if a.inject=='state':
        fork.cmd(b'SET',b'__diverge:selftest',b'x')
    dbf=fork.cmd(b'DBSIZE');dbo=orc.cmd(b'DBSIZE')
    print('CHK dbsize ok=%d detail=fork=%s,oracle=%s'%(1 if dbf==dbo else 0,dbf,dbo))
    kf=enum_keys(fork,a.enum);ko=enum_keys(orc,a.enum)
    ok_enum = kf==ko
    print('CHK enum ok=%d detail=fork=%d,oracle=%d'%(1 if ok_enum else 0,len(kf),len(ko)))
    fst=read_state(fork,kf);ost=read_state(orc,ko)
    diffs,ttlbad,maxsk=cmp_state(fst,ost)
    for d in diffs[:10]: print('STATEDIFF %s'%repr(d)[:160],file=sys.stderr)
    print('CHK readback ok=%d detail=keys=%d,diffs=%d'%(1 if not diffs else 0,len(kf),len(diffs)))
    print('CHK ttl ok=%d detail=ttl_mismatch=%d,max_skew_ms=%d'%(1 if ttlbad==0 else 0,ttlbad,maxsk))
    if len(kf)<max(50,a.ops//400):
        print('CHK plausibility ok=0 detail=implausibly-few-keys=%d'%len(kf));return 3
    bad = (opdiffs>0) or (dbf!=dbo) or (not ok_enum) or diffs
    return 2 if bad else 0

if __name__=='__main__':
    try:
        sys.exit(main())
    except (IOError,OSError,socket.timeout) as e:
        print('CHK infra ok=0 detail=%s'%str(e)[:120]);sys.exit(3)
PYEOF

# hot/samebucket key caches (deterministic; computed once, reused everywhere)
HOTFILE=$WORK/hotkeys_w2.txt
SBFILE=$WORK/samebucket_12.txt
[ -s "$HOTFILE" ] || timeout 300 python3 "$PY" hotkeys --workers 2 --wid 1 --count 140 > "$HOTFILE" || true
[ -s "$SBFILE" ] || timeout 300 python3 "$PY" samebucket --count 12 > "$SBFILE" || true

# map python CHK lines -> TSV rows.  args: section config rc outfile [prefix]
emit_chk_rows() {
    local sec=$1 cfg=$2 rc=$3 out=$4 pre=${5:-}
    local any=0 line name ok detail res
    while IFS= read -r line; do
        case "$line" in
            "CHK "*)
                any=1
                name=$(printf '%s' "$line" | awk '{print $2}')
                ok=$(printf '%s' "$line" | grep -oE 'ok=[01]' | head -1 | cut -d= -f2)
                detail=${line#*detail=}
                if [ "$rc" = 3 ]; then res=SUSPECT
                elif [ "$ok" = 1 ]; then res=PASS
                else res=FAIL; fi
                row "$sec" "${pre}${name}" "$cfg" "$res" "$detail"
                ;;
        esac
    done < "$out"
    [ "$any" = 1 ] || row "$sec" "${pre}run" "$cfg" SUSPECT "helper produced no CHK output (rc=$rc), see $out and $out.err"
}

# RESP pipe generators (ASCII keys/values; --pipe is the fast path)
pipe_set() { # port n prefix vlen start
    local port=$1 n=$2 pre=$3 vl=${4:-8} st=${5:-0}
    awk -v n="$n" -v pre="$pre" -v vl="$vl" -v st="$st" 'BEGIN{
        v=""; for(i=0;i<vl;i++) v=v "x";
        for(i=0;i<n;i++){k=pre (st+i);
        printf "*3\r\n$3\r\nSET\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n",length(k),k,length(v),v}}' \
      | lg_run timeout 180 "$CLI" -p "$port" --pipe >/dev/null 2>&1
}
pipe_del() { # port n prefix start
    local port=$1 n=$2 pre=$3 st=${4:-0}
    awk -v n="$n" -v pre="$pre" -v st="$st" 'BEGIN{for(i=0;i<n;i++){k=pre (st+i);
        printf "*2\r\n$3\r\nDEL\r\n$%d\r\n%s\r\n",length(k),k}}' \
      | lg_run timeout 180 "$CLI" -p "$port" --pipe >/dev/null 2>&1
}

# ===========================================================================
# SECTION A — ORACLE EQUIVALENCE
# ===========================================================================
section_A() {
    local sec=A cfg="io2ex2/default-vs-stock"
    log "=== SECTION A: oracle equivalence ==="
    local opid fpid flog o rc inj
    boot_srv oracle "$ORACLE_PORT" "$WORK/a_oracle" || { row $sec boot "$cfg" FAIL "oracle boot failed"; return; }
    opid=$BOOT_PID
    boot_srv fork "$FORK_PORT" "$WORK/a_fork" "${DEF_TOPO[@]}" \
        || { row $sec boot "$cfg" FAIL "fork boot failed"; stop_srv "$opid"; return; }
    fpid=$BOOT_PID; flog=$LAST_SRV_LOG

    # --- KNOWN list: commands the fork rejects BY DESIGN (expected error asserted;
    #     a silent behavior change flips these to FAIL) ---
    known_probe() { # name expected-substring cmd...
        local name=$1 exp=$2; shift 2
        local out; out=$(tcli "$FORK_PORT" "$@")
        if printf '%s' "$out" | grep -qF "$exp"; then
            row $sec "known-reject-$name" "$cfg" KNOWN "rejected with expected message"
        else
            row $sec "known-reject-$name" "$cfg" FAIL "expected [$exp], got: $(printf '%s' "$out" | head -c 120)"
        fi
    }
    # MULTI/WATCH/keyed-EVAL are SUPPORTED since the single-shard MULTI/EVAL merges (#92, 2026-08)
    # — verified live 2026-08-11 (MULTI->OK, WATCH->OK, keyed EVAL executes, EXEC applies). Their
    # old known-reject probes below are replaced with FUNCTIONAL probes per this file's own
    # precedent for ported commands.
    out=$(printf 'MULTI\nSET __fsq_tx a\nEXEC\n' | "$CLI" -p "$FORK_PORT" 2>&1; tcli "$FORK_PORT" GET __fsq_tx)
    if printf '%s' "$out" | grep -q "a$"; then row $sec multi-exec-applies "$cfg" PASS "MULTI/EXEC SET visible"
    else row $sec multi-exec-applies "$cfg" FAIL "got: $(printf '%s' "$out" | head -c 100)"; fi
    out=$(tcli "$FORK_PORT" WATCH __fsq_tx)
    if [ "$out" = "OK" ]; then row $sec watch-accepted "$cfg" PASS "WATCH OK"
    else row $sec watch-accepted "$cfg" FAIL "got: $(printf '%s' "$out" | head -c 100)"; fi
    tcli "$FORK_PORT" UNWATCH >/dev/null 2>&1
    out=$(tcli "$FORK_PORT" EVAL 'redis.call("SET", KEYS[1], "ev") return redis.call("GET", KEYS[1])' 1 __fsq_ek)
    if [ "$out" = "ev" ]; then row $sec keyed-eval-executes "$cfg" PASS "keyed EVAL write round-trips"
    else row $sec keyed-eval-executes "$cfg" FAIL "got: $(printf '%s' "$out" | head -c 100)"; fi
    # LCS, ZRANGESTORE, BLPOP/BRPOP, XREAD, GEORADIUS, GEOSEARCHSTORE, SORT BY/GET are now PORTED
    # across shards (validated by cmd_coverage: byte-exact output vs expected). Their old known-reject
    # probes are removed — the probes only asserted "is it rejected", which is no longer true and never
    # checked correctness. (The sort-by probe also had a bug: unquoted BY w_* glob-expanded in the shell.)
    # Add these to the oracle-equivalence stream below for stronger coverage as a follow-up.
    known_probe migrate        "$GUARD_MSG" MIGRATE 127.0.0.1 1 k 0 100

    # --- comparator SELF-TEST: injected divergences MUST be caught ---
    local st_ok=1
    for inj in op state; do
        o=$WORK/a_selftest_$inj.out
        timeout 600 python3 "$PY" compare --fork-port "$FORK_PORT" --oracle-port "$ORACLE_PORT" \
            --seed "$SEED" --ops 800 --workers 2 --reduced \
            --hot-file "$HOTFILE" --sb-file "$SBFILE" --inject "$inj" >"$o" 2>"$o.err"
        rc=$?
        if [ "$rc" = 2 ]; then
            row $sec "selftest-inject-$inj" "$cfg" PASS "comparator caught deliberate $inj divergence (rc=2)"
        else
            st_ok=0
            row $sec "selftest-inject-$inj" "$cfg" FAIL "comparator did NOT catch injected $inj divergence (rc=$rc) -> A results untrustworthy"
        fi
        tcli "$FORK_PORT" FLUSHALL >/dev/null; tcli "$ORACLE_PORT" FLUSHALL >/dev/null
    done

    # --- the main deterministic stream ---
    # precondition: the selftest FLUSHALLs must have actually emptied BOTH sides —
    # selftest leftovers would false-diff the main stream; a failed flush is a
    # harness problem (SUSPECT), not a fork divergence (FAIL).
    local dbf dbo
    dbf=$(tcli "$FORK_PORT" DBSIZE); dbo=$(tcli "$ORACLE_PORT" DBSIZE)
    if [ "$dbf" != "0" ] || [ "$dbo" != "0" ]; then
        row $sec flush-precheck "$cfg" SUSPECT "post-selftest FLUSHALL left keys (fork=$dbf oracle=$dbo); main-stream rows demoted"
        st_ok=0
    fi
    o=$WORK/a_main.out
    timeout 1800 python3 "$PY" compare --fork-port "$FORK_PORT" --oracle-port "$ORACLE_PORT" \
        --seed "$SEED" --ops "$A_OPS" --workers 2 \
        --hot-file "$HOTFILE" --sb-file "$SBFILE" >"$o" 2>"$o.err"
    rc=$?
    if [ "$st_ok" = 0 ] && [ "$rc" != 3 ]; then rc=3; fi     # broken comparator/precondition -> SUSPECT rows
    emit_chk_rows $sec "$cfg" "$rc" "$o"

    # short-TTL functional check (kept OUT of the oracle stream: fork may lack
    # active expiry on shards; lazy-on-access is the contract tested here)
    tcli "$FORK_PORT" SETEX shortttl 2 v1 >/dev/null
    sleep 3
    local g; g=$(tcli "$FORK_PORT" GET shortttl)
    if [ -z "$g" ]; then row $sec short-ttl-lazy-expire "$cfg" PASS "SETEX 2 -> nil after 3s"
    else row $sec short-ttl-lazy-expire "$cfg" FAIL "expected nil, got [$g]"; fi

    local cm; cm=$(crash_scan "$flog")
    [ -z "$cm" ] && row $sec crash-scan "$cfg" PASS "server log clean" \
                 || row $sec crash-scan "$cfg" FAIL "$cm"
    assert_server "$FORK_PORT" "$fpid" || row $sec post-alive "$cfg" FAIL "fork gone after A"
    stop_srv "$fpid"
    A_ORACLE_PID=$opid   # oracle stays up for section B
}

# ===========================================================================
# SECTION B — FEATURE-TOGGLE SEMANTICS (reduced stream must be IDENTICAL)
# ===========================================================================
b_cell() { # name enum extra-args...   (leaves the fork RUNNING in B_LAST_PID)
    local name=$1 enum=$2; shift 2
    local sec=B cfg="io2ex2/$name"
    B_LAST_PID=""
    local o rc
    boot_srv fork "$FORK_PORT" "$WORK/b_$name" "${DEF_TOPO[@]}" "$@" \
        || { row $sec cell "$cfg" FAIL "fork boot failed (flags: $*)"; return 1; }
    B_LAST_PID=$BOOT_PID
    local flog=$LAST_SRV_LOG
    tcli "$ORACLE_PORT" FLUSHALL >/dev/null
    [ "$(tcli "$ORACLE_PORT" DBSIZE)" = "0" ] || { row $sec cell "$cfg" SUSPECT "oracle flush failed"; return 1; }
    o=$WORK/b_$name.out
    timeout 900 python3 "$PY" compare --fork-port "$FORK_PORT" --oracle-port "$ORACLE_PORT" \
        --seed "$SEED" --ops "$B_OPS" --workers 2 --reduced --enum "$enum" \
        --hot-file "$HOTFILE" --sb-file "$SBFILE" >"$o" 2>"$o.err"
    rc=$?
    emit_chk_rows $sec "$cfg" "$rc" "$o"
    local cm; cm=$(crash_scan "$flog")
    [ -n "$cm" ] && row $sec crash-scan "$cfg" FAIL "$cm"
    return 0
}

b_cell_topo() { # name enum io ex  (different mandatory topology)
    local name=$1 enum=$2 io=$3 ex=$4
    local -a save=("${DEF_TOPO[@]}")
    DEF_TOPO=(--tomokv-thread-io "$io" --tomokv-thread-ex "$ex")
    b_cell "$name" "$enum"
    local rc=$?
    DEF_TOPO=("${save[@]}")
    return $rc
}

section_B() {
    log "=== SECTION B: feature-toggle semantics ==="
    local sec=B      # ('out'/'sc' locals dropped with the flat0 and xshard-guard0 probes)
    if [ -z "$A_ORACLE_PID" ] || ! assert_server "$ORACLE_PORT" "$A_ORACLE_PID"; then
        boot_srv oracle "$ORACLE_PORT" "$WORK/b_oracle" \
            || { row $sec oracle "io2ex2" FAIL "oracle boot failed; B skipped"; return; }
        A_ORACLE_PID=$BOOT_PID
    fi

    # flat0 cell REMOVED 2026-07-28: tomokv-flat-store was retired, so the "shared dicts"
    # (flat=off) arm no longer exists in the server and the cell would hard-fail at BOOT.
    # Deleted as a WHOLE construct -- the cell plus its dependent SCAN-decoy probe, which only
    # meant anything under flat=0. Stripping just the flag would have left a silent duplicate of
    # the default cell masquerading as an ablation.
    # LOST: the flat=off enumeration/decoy-SCAN semantics arm (unrecoverable; arm is gone).

    # mcmd-lock cell REMOVED 2026-07-27: always-lock IS the design, so the knob (which was
    # accepted and then overridden) is gone. Booting with an unknown option is a hard boot
    # failure, so the cell cannot stay.
    # mcmd-nodelocal cell REMOVED 2026-07-27: the knob selected the node-local borrow, which is
    # deleted. Same reason.
    b_cell thread-mode-auto scan --tomokv-thread-mode auto; stop_srv "$B_LAST_PID"

    # xshard-guard0 cell REMOVED 2026-07-28: tomokv-xshard-guard was retired, so guard=off is
    # no longer reachable. Deleted as a WHOLE construct (cell + its LCS guard-rejection probe,
    # which was the positive control FOR that knob and is meaningless with the guard always on).
    # LOST: the "guard actually gates cross-shard commands" positive control. The guard-ON
    # rejection message is still exercised elsewhere via $GUARD_MSG.

    # Cells REMOVED 2026-07-28 (knob retired => the non-default arm no longer exists; a
    # flag-stripped cell would be a silent duplicate of the default cell):
    #   xshard-pipeline0     tomokv-xshard-pipeline no
    #   express-slim0        tomokv-express-slim 0
    #   express-slim-forced  tomokv-express-slim 1
    #   pipeline-depth0      tomokv-pipeline-depth 0
    #   fake-ring0           tomokv-fake-ring-depth 0
    #   num-cdb0             tomokv-num-cdb 0
    # operand-pool cell REMOVED: the knob was deleted (measured net-negative,
    # instr/op +2.18..4.13%, allocs/op +6.6..15.7%). A cell that sets a deleted
    # knob fails the server BOOT, which the sweep correctly reports as a FAIL --
    # so every knob retirement must retire its sweep cells in the same commit.

    if [ "$SMOKE" != "1" ]; then
        # Cells REMOVED 2026-07-28 -- every one of these set a RETIRED knob to a non-default
        # value, i.e. selected a code arm that no longer exists. Booting with the flag is now a
        # hard boot failure, and stripping the flag would leave a fake ablation identical to the
        # default cell, so the cells are deleted outright:
        #   num-cdb1 / num-cdb4            tomokv-num-cdb
        #   pipeline-depth8                tomokv-pipeline-depth
        #   fake-ring8                     tomokv-fake-ring-depth
        #   fake-buf-legacy                tomokv-fake-buf
        #   pfw-all-0 / pfw-all-max        tomokv-pf-w-{struct,argv,keyobj,keybytes,hash,
        #                                    nextop,entry,value} (multi-line cells, removed whole)
        #   worker-pop-batch0 / -batch8    tomokv-worker-pop-batch
        #   drain-tail-skip0               tomokv-drain-tail-skip
        #   io-drain-userpoll0 / -poll64   tomokv-io-drain-userpoll
        #   worker-spin512                 tomokv-worker-spin
        #   mget-legacy / mget-coalesce-prefetch   tomokv-mget-coalesce
        #   setop-coalesce0                tomokv-setop-coalesce
        #   mset-move                      tomokv-mset-move
        #   localfast0                     tomokv-xshard-localfast
        #   zerocopy-off                   tomokv-zerocopy-min-value
        # LOST: semantics-under-toggle coverage for all of the above. The surviving DEFAULT arm
        # of each is still exercised by every other cell; the alternate arms are gone from the
        # server, so there is nothing left to test.
        b_cell strict-order1 scan --tomokv-strict-order 1;            stop_srv "$B_LAST_PID"
        # topology variants (different sharding shapes, same semantics).
        # ex=1 => non-shared per-worker dbs (no FLATSTORE): SCAN is decoy-inline there too => KEYS
        b_cell_topo ex1-nonshared keys 2 1;                           stop_srv "$B_LAST_PID"
        b_cell_topo ex3-oddworkers scan 2 3;                          stop_srv "$B_LAST_PID"
    fi
    stop_srv "$A_ORACLE_PID"; A_ORACLE_PID=""
}

# ===========================================================================
# SECTION C — FEATURE-EFFECT CHECKS (does it actually DO something)
# ===========================================================================
section_C() {
    log "=== SECTION C: feature-effect checks ==="
    local sec=C cfg="io2ex2/default"
    local fpid flog info i found cm
    boot_srv fork "$FORK_PORT" "$WORK/c_main" "${DEF_TOPO[@]}" \
        || { row $sec boot "$cfg" FAIL "fork boot failed; C main cells skipped"; return; }
    fpid=$BOOT_PID; flog=$LAST_SRV_LOG

    # C1: flat GROW resize log (trigger: (used+tombs) >= 70% of the 256K-slot initial table)
    if grep -aq "FLATSTORE resize:.*rebuilt" "$flog"; then
        row $sec flat-resize-precheck "$cfg" SUSPECT "resize line present BEFORE seeding (unexpected)"
    fi
    pipe_set "$FORK_PORT" 200000 "flat:" 8 0
    found=""
    for i in $(seq 1 40); do
        found=$(grep -a "FLATSTORE resize:.*rebuilt" "$flog" | head -1)
        [ -n "$found" ] && break; sleep 0.5
    done
    if [ -n "$found" ]; then
        local oldsz newsz
        oldsz=$(printf '%s' "$found" | grep -oE 'rebuilt [0-9]+' | grep -oE '[0-9]+')
        newsz=$(printf '%s' "$found" | grep -oE -- '-> [0-9]+' | grep -oE '[0-9]+')
        if [ -n "$oldsz" ] && [ -n "$newsz" ] && [ "$newsz" -gt "$oldsz" ]; then
            row $sec flat-resize-grow "$cfg" PASS "seed 200k -> $oldsz -> $newsz slots"
        else row $sec flat-resize-grow "$cfg" SUSPECT "resize line but not a grow: $found"; fi
    else row $sec flat-resize-grow "$cfg" FAIL "no FLATSTORE resize log after 200k seed (trigger=70% of 256K slots)"; fi

    # C2: flat SHRINK after mass DEL (live falls under load_pct/4 of the table)
    local grow_lines; grow_lines=$(grep -ac "FLATSTORE resize:.*rebuilt" "$flog")
    pipe_del "$FORK_PORT" 145000 "flat:" 0
    local dbs; dbs=$(tcli "$FORK_PORT" DBSIZE)
    [ "$dbs" = "55000" ] || row $sec flat-shrink-dbsize "$cfg" SUSPECT "post-DEL dbsize=$dbs (expected 55000)"
    found=""
    for i in $(seq 1 40); do
        local nl; nl=$(grep -ac "FLATSTORE resize:.*rebuilt" "$flog")
        if [ "$nl" -gt "$grow_lines" ]; then found=$(grep -a "FLATSTORE resize:.*rebuilt" "$flog" | tail -1); break; fi
        sleep 0.5
    done
    if [ -n "$found" ]; then
        local oldsz newsz
        oldsz=$(printf '%s' "$found" | grep -oE 'rebuilt [0-9]+' | grep -oE '[0-9]+')
        newsz=$(printf '%s' "$found" | grep -oE -- '-> [0-9]+' | grep -oE '[0-9]+')
        if [ -n "$newsz" ] && [ -n "$oldsz" ] && [ "$newsz" -lt "$oldsz" ]; then
            row $sec flat-resize-shrink "$cfg" PASS "mass DEL -> $oldsz -> $newsz slots"
        else row $sec flat-resize-shrink "$cfg" SUSPECT "post-DEL resize not a shrink: $found"; fi
    else row $sec flat-resize-shrink "$cfg" FAIL "no shrink resize after deleting 145k/200k keys"; fi

    # C3: QSBR batches drain to ~0 after churn stops (activity-gated: closed must move).
    # Overwrite LIVE keys (flat:150000..199999) so the old values RETIRE.
    info=$(tcli "$FORK_PORT" INFO stats)
    local closed0; closed0=$(info_field "$info" tomokv_flat_batches_closed)
    pipe_set "$FORK_PORT" 50000 "flat:" 16 150000
    sleep 3
    info=$(tcli "$FORK_PORT" INFO stats)       # ONE info call for both fields
    local closed1 pend
    closed1=$(info_field "$info" tomokv_flat_batches_closed)
    pend=$(info_field "$info" tomokv_flat_batches_pending)
    if [ "${closed1:-0}" -le "${closed0:-0}" ]; then
        row $sec qsbr-pending-drains "$cfg" SUSPECT "batches_closed did not move ($closed0->$closed1): overwrite churn produced no retire batches?"
    elif [ "${pend:-999}" -le 2 ]; then
        row $sec qsbr-pending-drains "$cfg" PASS "closed $closed0->$closed1, pending=$pend after 3s idle"
    else
        row $sec qsbr-pending-drains "$cfg" FAIL "pending=$pend still outstanding 3s after churn stopped"
    fi

    # C4: tomokv_flat_io_pinned rises during a long DEBUG DIGEST
    pipe_set "$FORK_PORT" 250000 "dg:" 64 0    # widen dataset so the digest takes a while
    info=$(tcli "$FORK_PORT" INFO stats)
    local base peak=0 v
    base=$(info_field "$info" tomokv_flat_io_pinned); base=${base:-0}
    # NB: 120s timeout, NOT tcli's 20s — the digest is deliberately long (~300k keys)
    # so the poll loop can catch io_pinned; a 20s kill would empty the digest file.
    ( timeout 120 "$CLI" -p "$FORK_PORT" DEBUG DIGEST > "$WORK/c_digest.out" 2>&1 ) &
    local dgpid=$!
    for i in $(seq 1 120); do
        kill -0 "$dgpid" 2>/dev/null || break
        info=$(tcli "$FORK_PORT" INFO stats)
        v=$(info_field "$info" tomokv_flat_io_pinned); v=${v:-0}
        [ "$v" -gt "$peak" ] && peak=$v
    done
    for i in $(seq 1 300); do kill -0 "$dgpid" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$dgpid" 2>/dev/null; wait "$dgpid" 2>/dev/null
    local dg; dg=$(head -c 60 "$WORK/c_digest.out")
    if [ "$peak" -gt "$base" ]; then
        row $sec flat-io-pinned-during-digest "$cfg" PASS "base=$base peak=$peak digest=${dg:0:16}"
    else
        row $sec flat-io-pinned-during-digest "$cfg" SUSPECT "peak=$peak base=$base (digest may have finished between polls); digest=${dg:0:16}"
    fi
    if is_digest "$dg"; then
        row $sec debug-digest-nonzero "$cfg" PASS "digest=${dg:0:20}"
    else
        row $sec debug-digest-nonzero "$cfg" FAIL "digest not a 40-hex nonzero digest: [$dg]"
    fi
    cm=$(crash_scan "$flog")
    [ -z "$cm" ] && row $sec crash-scan "$cfg" PASS "server log clean" || row $sec crash-scan "$cfg" FAIL "$cm"
    stop_srv "$fpid"

    # C6: fake-ring decay after burst->idle. DEDICATED small server so the
    # used_memory differential is attributable to the ring, not to flat-table churn.
    boot_srv fork "$FORK_PORT" "$WORK/c_decay" "${DEF_TOPO[@]}" \
        || { row $sec fake-ring-decay "$cfg" SUSPECT "boot failed"; true; }
    if [ -n "$BOOT_PID" ]; then
        fpid=$BOOT_PID
        local rd drop
        rd=$(timeout 150 python3 "$PY" ringdecay --fork-port "$FORK_PORT" 2>&1 | tail -1)
        drop=$(printf '%s' "$rd" | grep -oE 'DROP=-?[0-9]+' | cut -d= -f2)
        if [ -n "$drop" ] && [ "$drop" -ge 32768 ]; then
            row $sec fake-ring-decay "$cfg" PASS "$rd (ring freed after 10s idle on an open conn)"
        elif [ -n "$drop" ]; then
            row $sec fake-ring-decay "$cfg" SUSPECT "$rd (drop <32KB: decay not distinguishable from noise on this run)"
        else
            row $sec fake-ring-decay "$cfg" SUSPECT "ringdecay helper output: $rd"
        fi
        stop_srv "$fpid"
    fi

    # C5 exqfull-positive-control cell REMOVED 2026-07-28: it forced the back-pressure path by
    # booting with tomokv-ex-queue-depth 64, and that knob was retired (the ex ring is
    # auto-sized only). Removed as a WHOLE section -- boot + memtier saturation + the counter /
    # sentinel / ping post-state checks were all dependent on that one server.
    #
    # COVERAGE NOW LOST -- READ THIS BEFORE TRUSTING A GREEN SUITE:
    #   The ex queue-full / back-pressure path has NO POSITIVE CONTROL any more. Nothing in this
    #   sweep can make tomokv_ex_queue_full non-zero, so we can no longer show that (a) the
    #   counter is even live, or (b) the queue-full path neither wedges nor corrupts when it
    #   fires. Section F still asserts tomokv_ex_queue_full == 0 under normal load, but with no
    #   way to force a non-zero that assertion is UNCONTROLLED: a permanently-dead counter would
    #   pass it silently.
    #   TO RESTORE: needs a DEBUG-based forcing mechanism (e.g. a DEBUG subcommand that shrinks
    #   the ex ring, stalls an EX worker, or injects synthetic queue-full events) since there is
    #   no config path to a small ring. Until then this is a real hole, not a green square.

    # C7: flips>0 under thread-mode-auto with alternating p1/p32 phases
    local cfg3="io2ex2/thread-mode-auto"
    boot_srv fork "$FORK_PORT" "$WORK/c_flip" "${DEF_TOPO[@]}" \
           --tomokv-thread-mode auto \
        || { row $sec flips-under-phases "$cfg3" FAIL "boot failed"; BOOT_PID=""; }
    if [ -n "$BOOT_PID" ]; then
        fpid=$BOOT_PID; flog=$LAST_SRV_LOG
        if command -v memtier_benchmark >/dev/null; then
            lg_run timeout $((FLIP_T+60)) memtier_benchmark -s 127.0.0.1 -p "$FORK_PORT" -t 2 -c 30 --pipeline=1 \
                --ratio=1:9 --key-maximum=100000 -d 64 --test-time="$FLIP_T" --hide-histogram \
                > "$WORK/c_flip_p1.out" 2>&1
            lg_run timeout $((FLIP_T+60)) memtier_benchmark -s 127.0.0.1 -p "$FORK_PORT" -t 2 -c 8 --pipeline=32 \
                --ratio=1:9 --key-maximum=100000 -d 64 --test-time="$FLIP_T" --hide-histogram \
                > "$WORK/c_flip_p32.out" 2>&1
            sleep 2
            local nflip nclimb
            nflip=$(grep -acE 'flip: GROW-(FRONT|BACK) complete' "$flog")
            nclimb=$(grep -ac 'flip-ctl' "$flog")
            if [ "${nflip:-0}" -gt 0 ]; then
                row $sec flips-under-phases "$cfg3" PASS "completed flips=$nflip (flip-ctl lines=$nclimb) across p1/p32 phases"
            elif [ "${nclimb:-0}" -gt 0 ]; then
                row $sec flips-under-phases "$cfg3" SUSPECT "controller alive (flip-ctl lines=$nclimb) but 0 completed flips in ${FLIP_T}s phases (converged or box-noisy)"
            else
                row $sec flips-under-phases "$cfg3" FAIL "no flip-ctl activity at all under thread-mode-auto"
            fi
            cm=$(crash_scan "$flog"); [ -n "$cm" ] && row $sec flips-crash-scan "$cfg3" FAIL "$cm"
        else
            row $sec flips-under-phases "$cfg3" SUSPECT "memtier not on PATH"
        fi
        stop_srv "$fpid"
    fi

    # C8: reshard DONE with low min-ops + hot keys pinned to one worker
    local cfg4="io2ex2/key-lb2000"
    boot_srv fork "$FORK_PORT" "$WORK/c_reshard" "${DEF_TOPO[@]}" --tomokv-key-lb 2000 \
        || { row $sec reshard-done "$cfg4" FAIL "boot failed"; BOOT_PID=""; }
    if [ -n "$BOOT_PID" ]; then
        fpid=$BOOT_PID; flog=$LAST_SRV_LOG
        local hk1 hk2 hk3 hk4
        { read -r hk1; read -r hk2; read -r hk3; read -r hk4; } < "$HOTFILE"   # all on worker 1
        if [ -n "$hk4" ]; then
            tcli "$FORK_PORT" MSET "$hk1" v "$hk2" v "$hk3" v "$hk4" v >/dev/null
            awk -v a="$hk1" -v b="$hk2" -v c="$hk3" -v d="$hk4" 'BEGIN{
                for(i=0;i<75000;i++){k=(i%4==0?a:(i%4==1?b:(i%4==2?c:d)));
                printf "*2\r\n$3\r\nGET\r\n$%d\r\n%s\r\n",length(k),k}}' > "$WORK/c_hotpipe.resp"
            local pass done_seen="" armed=""
            for pass in 1 2 3 4 5 6 7 8; do
                lg_run timeout 60 "$CLI" -p "$FORK_PORT" --pipe < "$WORK/c_hotpipe.resp" >/dev/null 2>&1
                grep -aq "reshard DONE" "$flog" && { done_seen=1; break; }
                [ "$SMOKE" = "1" ] && [ "$pass" -ge 4 ] && break
            done
            sleep 2
            grep -aqE "reshard (ARM|AUTO)" "$flog" && armed=1
            # A reshard that ARMS near the end of the stimulus window is IN FLIGHT, not stuck.
            # Measured 2026-08-05: this cell tore the server down 101ms after "reshard FLIP" --
            # ownership had ALREADY changed hands -- and reported "stuck migration". The lifecycle
            # is AUTO -> ARM -> DRAINING -> FLIP -> DONE, and DONE waits on the destination
            # worker's heartbeat, so a late arm needs a beat to finish. Give it bounded time.
            if [ -z "$done_seen" ] && [ -n "$armed" ]; then
                for _ in $(seq 1 60); do
                    grep -aq "reshard DONE" "$flog" && break
                    sleep 0.5
                done
            fi
            grep -aq "reshard DONE" "$flog" && done_seen=1
            if [ -n "$done_seen" ]; then
                row $sec reshard-done "$cfg4" PASS "$(grep -a 'reshard DONE' "$flog" | head -1 | sed 's/.*ee451/ee451/')"
            elif [ -n "$armed" ] && grep -aq "reshard FLIP" "$flog"; then
                # Ownership DID change hands and only the completion tail is missing -- a different
                # thing from a migration that never flipped. Do not report both as "stuck".
                row $sec reshard-done "$cfg4" FAIL "ownership FLIPPED but no DONE within 30s (completion tail stuck): $(grep -aE 'reshard FLIP' "$flog" | tail -1)"
            elif [ -n "$armed" ]; then
                row $sec reshard-done "$cfg4" FAIL "reshard ARMED but never reached FLIP (stuck migration): $(grep -aE 'reshard (ARM|AUTO)' "$flog" | tail -1)"
            else
                row $sec reshard-done "$cfg4" SUSPECT "reshard never armed under hot-worker load (box noise or trigger gating; check $flog)"
            fi
            cm=$(crash_scan "$flog"); [ -n "$cm" ] && row $sec reshard-crash-scan "$cfg4" FAIL "$cm"
        else
            row $sec reshard-done "$cfg4" SUSPECT "hot-key cache missing/short ($HOTFILE)"
        fi
        stop_srv "$fpid"
    fi

    # C9: express-lane engagement has NO INFO/log observable in this tree
    # (server.express_hit_ewma is internal-only; moveExecutionStateSlim keeps no
    # counter). The B express-slim0/express-slim-forced cells that used to carry the
    # semantics went away with tomokv-express-slim on 2026-07-28, so the express lane
    # now has NEITHER an observable NOR a toggle cell — only its default arm runs.
    row $sec express-lane-engagement "io2ex2/express-slim" KNOWN "no observable exists (express_hit_ewma not exported, no slim-path counter) AND the B toggle cells were retired with tomokv-express-slim: default arm only; listed in coverage_gaps"
}

# ===========================================================================
# SECTION D — PERSISTENCE
# ===========================================================================
section_D() {
    log "=== SECTION D: persistence ==="
    local sec=D cfg="io2ex2/default"
    local dir=$WORK/d_rdb; rm -rf "$dir"
    local fpid o rc info i ok
    boot_srv fork "$FORK_PORT" "$dir" "${DEF_TOPO[@]}" \
        || { row $sec boot "$cfg" FAIL "boot failed; D skipped"; return; }
    fpid=$BOOT_PID
    o=$WORK/d_snapshot.out
    timeout 900 python3 "$PY" snapshot --fork-port "$FORK_PORT" --seed "$SEED" --ops "$B_OPS" --workers 2 --reduced \
        --hot-file "$HOTFILE" --sb-file "$SBFILE" --snap "$WORK/d_state.pkl" >"$o" 2>"$o.err"
    rc=$?
    emit_chk_rows $sec "$cfg" "$rc" "$o" "seed-"
    if [ "$rc" != 0 ]; then stop_srv "$fpid"; return; fi

    tcli "$FORK_PORT" BGSAVE >/dev/null
    ok=""
    for i in $(seq 1 120); do
        info=$(tcli "$FORK_PORT" INFO persistence)
        if [ "$(info_field "$info" rdb_bgsave_in_progress)" = "0" ]; then
            [ "$(info_field "$info" rdb_last_bgsave_status)" = "ok" ] && ok=1
            break
        fi
        sleep 0.5
    done
    if [ -n "$ok" ]; then row $sec bgsave "$cfg" PASS "rdb_last_bgsave_status=ok"
    else row $sec bgsave "$cfg" FAIL "bgsave did not complete ok"; stop_srv "$fpid"; return; fi

    tcli "$FORK_PORT" SHUTDOWN NOSAVE >/dev/null 2>&1
    for i in $(seq 1 100); do kill -0 "$fpid" 2>/dev/null || break; sleep 0.1; done
    if kill -0 "$fpid" 2>/dev/null; then
        row $sec shutdown "$cfg" FAIL "server did not exit on SHUTDOWN NOSAVE"; stop_srv "$fpid"; return
    fi
    wait "$fpid" 2>/dev/null
    row $sec shutdown "$cfg" PASS "clean exit"

    boot_srv fork "$FORK_PORT" "$dir" "${DEF_TOPO[@]}" \
        || { row $sec restart "$cfg" FAIL "restart from BGSAVE rdb failed"; return; }
    fpid=$BOOT_PID
    o=$WORK/d_verify.out
    timeout 900 python3 "$PY" verify --fork-port "$FORK_PORT" --snap "$WORK/d_state.pkl" >"$o" 2>"$o.err"
    rc=$?
    emit_chk_rows $sec "$cfg" "$rc" "$o" "restart-"
    stop_srv "$fpid"

    # DEBUG RELOAD — KNOWN-segfault per project memory; test either way, own boot
    local dir2=$WORK/d_reload; rm -rf "$dir2"
    boot_srv fork "$FORK_PORT" "$dir2" "${DEF_TOPO[@]}" \
        || { row $sec debug-reload "$cfg" SUSPECT "boot failed for reload cell"; return; }
    fpid=$BOOT_PID
    local flog=$LAST_SRV_LOG
    pipe_set "$FORK_PORT" 2000 "rl:" 32 0
    tcli "$FORK_PORT" SADD rlset a b c >/dev/null; tcli "$FORK_PORT" HSET rlh f v >/dev/null
    tcli "$FORK_PORT" EXPIRE rl:5 1000 >/dev/null
    local d1 d2 out
    d1=$(tcli "$FORK_PORT" DEBUG DIGEST)
    out=$(timeout 60 "$CLI" -p "$FORK_PORT" DEBUG RELOAD 2>&1)
    sleep 0.5
    if kill -0 "$fpid" 2>/dev/null && assert_server "$FORK_PORT" "$fpid"; then
        d2=$(tcli "$FORK_PORT" DEBUG DIGEST)
        # is_digest: a matching pair of error strings / zero digests must not count
        # as "survived with identical digest"
        if [ "$out" = "OK" ] && [ "$d1" = "$d2" ] && is_digest "$d1"; then
            D_RELOAD_RESULT="PASS"; D_RELOAD_DETAIL="survived + digest identical ($d1) — documented crash did NOT reproduce; upgrade the ledger"
        else
            D_RELOAD_RESULT="FAIL"; D_RELOAD_DETAIL="survived but wrong: reply=[$(printf '%s' "$out" | head -c 60)] digest $d1 -> $d2"
        fi
    else
        D_RELOAD_RESULT="KNOWN"; D_RELOAD_DETAIL="documented DEBUG RELOAD crash reproduced (reply=[$(printf '%s' "$out" | head -c 60)]); log=$flog"
    fi
    row $sec debug-reload "$cfg" "$D_RELOAD_RESULT" "$D_RELOAD_DETAIL"
    stop_srv "$fpid"
}

# ===========================================================================
# SECTION E — SCRIPT FENCE   +   SECTION G — KNOWN-ISSUES LEDGER (same boot)
# ===========================================================================
section_EG() {
    log "=== SECTION E: script fence / G: known-issues ledger ==="
    local sec=E cfg="io2ex2/default"
    local fpid flog out i
    boot_srv fork "$FORK_PORT" "$WORK/e_fence" "${DEF_TOPO[@]}" \
        || { row $sec boot "$cfg" FAIL "boot failed; E+G skipped"; return; }
    fpid=$BOOT_PID; flog=$LAST_SRV_LOG

    # E1: keyed EVAL executes (supported since the single-shard EVAL merge; was a reject probe)
    out=$(tcli "$FORK_PORT" EVAL "return 1" 1 k1)
    if [ "$out" = "1" ]; then row $sec keyed-eval-executes "$cfg" PASS "keyed EVAL returns"
    else row $sec keyed-eval-executes "$cfg" FAIL "got: $(printf '%s' "$out" | head -c 100)"; fi

    # E2: sequential evals, no gate leak (epoch-monotone regression)
    local seq_ok=1
    for i in $(seq 1 10); do
        out=$(tcli "$FORK_PORT" EVAL "return $i" 0)
        [ "$out" = "$i" ] || { seq_ok=0; break; }
    done
    [ "$seq_ok" = 1 ] && row $sec sequential-evals "$cfg" PASS "10 sequential evals clean (no -BUSY leak)" \
                      || row $sec sequential-evals "$cfg" FAIL "eval #$i returned [$out]"

    # E3/E4/E5: one long busy EVAL; 20 concurrent SETs; concurrent EVAL -> -BUSY;
    # foreign SCRIPT KILL terminates it; next script clean
    local BUSY='local x=0 for i=1,600000000 do x=x+1 end return x'
    ( timeout 60 "$CLI" -p "$FORK_PORT" EVAL "$BUSY" 0 > "$WORK/e_busy.out" 2>&1 ) &
    local bg=$!
    sleep 0.4
    local setok=0
    for i in $(seq 1 20); do
        # BOUNDED RETRY-UNTIL-SUCCESS (up to 3). The slow-script listener scram (server, 2026-08-05)
        # RSTs the conns queued in the scripting thread's backlog when it leaves the accept group — a
        # designed fast-failure replacing the old silent hang-until-timeout. Real clients retry on
        # ECONNRESET and the retry lands on a live listener by construction (the dead one is out of the
        # group). A one-shot CLI must mirror that. retry-ONCE flaked to 16/20 under sustained full-
        # preflight load (2026-08-06: proven 5/5 = 20/20 in isolation, so the fence is fine — the test
        # was under-retrying, not the server dropping writes). 3 tries mirrors a real client and stays
        # discriminating: a server that ACTUALLY black-holes (no scram) hangs every attempt and still fails.
        out=""
        # 5 tries (was 3): 3 flaked to 17/20 under the full 20-suite gate (2026-08-11) while 5/5
        # isolated rounds ran 20/20 — same under-retry-under-load class as the 2026-08-06 note.
        # Still discriminating: a server that actually black-holes hangs every attempt.
        for attempt in 1 2 3 4 5; do
            out=$(timeout 30 "$CLI" -p "$FORK_PORT" SET "ek:$i" "v$i" 2>&1)
            [ "$out" = "OK" ] && break
        done
        [ "$out" = "OK" ] && setok=$((setok+1))
    done
    local busy_seen=""
    for i in 1 2 3; do
        kill -0 "$bg" 2>/dev/null || break
        out=$(timeout 10 "$CLI" -p "$FORK_PORT" EVAL "return 7" 0 2>&1)
        printf '%s' "$out" | grep -qF "$BUSY_MSG" && { busy_seen=1; break; }
    done
    out=$(tcli "$FORK_PORT" SCRIPT KILL)
    local kill_state=""
    if [ "$out" = "OK" ]; then kill_state=ok
    elif printf '%s' "$out" | grep -qi "NOTBUSY"; then kill_state=notbusy
    fi
    for i in $(seq 1 300); do kill -0 "$bg" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$bg" 2>/dev/null; wait "$bg" 2>/dev/null
    local bgout; bgout=$(head -c 200 "$WORK/e_busy.out")
    if kill -0 "$fpid" 2>/dev/null && [ "$setok" -eq 20 ]; then
        row $sec busy-eval-concurrent-set "$cfg" PASS "20/20 SETs ok during busy EVAL, server alive"
    else
        row $sec busy-eval-concurrent-set "$cfg" FAIL "sets_ok=$setok/20 alive=$(kill -0 "$fpid" 2>/dev/null && echo y || echo n)"
    fi
    [ -n "$busy_seen" ] && row $sec concurrent-eval-busy "$cfg" PASS "second EVAL got -BUSY TomoKV" \
        || row $sec concurrent-eval-busy "$cfg" SUSPECT "never observed -BUSY (script may have ended before probe)"
    if [ "$kill_state" = ok ] && printf '%s' "$bgout" | grep -qi "killed"; then
        row $sec foreign-script-kill "$cfg" PASS "SCRIPT KILL +OK, owner got: $(printf '%s' "$bgout" | head -c 80)"
    elif [ "$kill_state" = ok ]; then
        row $sec foreign-script-kill "$cfg" SUSPECT "KILL +OK but owner reply: $(printf '%s' "$bgout" | head -c 80)"
    elif [ "$kill_state" = notbusy ]; then
        row $sec foreign-script-kill "$cfg" SUSPECT "script finished before KILL landed (NOTBUSY; timing on a busy box)"
    else
        row $sec foreign-script-kill "$cfg" FAIL "SCRIPT KILL replied [$out]"
    fi
    out=$(tcli "$FORK_PORT" EVAL "return 42" 0)
    [ "$out" = "42" ] && row $sec post-kill-script-clean "$cfg" PASS "next EVAL returned 42" \
        || row $sec post-kill-script-clean "$cfg" FAIL "next EVAL: [$out]"

    # full mode: repeat short busy+SET rounds (the original crash was instant)
    if [ "$E_REPS" -gt 5 ]; then
        local SHORT='local x=0 for i=1,60000000 do x=x+1 end return x'
        local surv=0 r b2
        for r in $(seq 1 "$E_REPS"); do
            ( timeout 30 "$CLI" -p "$FORK_PORT" EVAL "$SHORT" 0 >/dev/null 2>&1 ) &
            b2=$!
            for i in 1 2 3 4 5; do timeout 15 "$CLI" -p "$FORK_PORT" SET rk v >/dev/null 2>&1; done
            for i in $(seq 1 200); do kill -0 "$b2" 2>/dev/null || break; sleep 0.05; done
            kill -9 "$b2" 2>/dev/null; wait "$b2" 2>/dev/null
            kill -0 "$fpid" 2>/dev/null && timeout 5 "$CLI" -p "$FORK_PORT" -t 1 ping 2>/dev/null | grep -q PONG && surv=$((surv+1))
        done
        [ "$surv" -eq "$E_REPS" ] && row $sec busy-eval-reps "$cfg" PASS "survived $surv/$E_REPS busy-eval+SET rounds" \
            || row $sec busy-eval-reps "$cfg" FAIL "survived only $surv/$E_REPS rounds"
    fi

    # ---------------- SECTION G (same default boot) ----------------
    sec=G
    # MULTI/WATCH are SUPPORTED since the single-shard MULTI merge (#92); the reject-message
    # tracking cells flipped to acceptance tracking 2026-08-11 (same retirement as section A).
    out=$(tcli "$FORK_PORT" MULTI)
    if [ "$out" = "OK" ]; then row $sec multi-accepted "$cfg" KNOWN "MULTI supported (OK)"
    else row $sec multi-accepted "$cfg" FAIL "MULTI reply: $(printf '%s' "$out" | head -c 100)"; fi
    tcli "$FORK_PORT" DISCARD >/dev/null 2>&1
    out=$(tcli "$FORK_PORT" WATCH wk)
    if [ "$out" = "OK" ]; then row $sec watch-accepted "$cfg" KNOWN "WATCH supported (OK)"
    else row $sec watch-accepted "$cfg" FAIL "WATCH reply: $(printf '%s' "$out" | head -c 100)"; fi
    tcli "$FORK_PORT" UNWATCH >/dev/null 2>&1
    tcli "$FORK_PORT" SET gskey shardval >/dev/null
    local direct inner
    direct=$(tcli "$FORK_PORT" GET gskey)
    inner=$(tcli "$FORK_PORT" EVAL "return redis.call('get', ARGV[1])" 0 gskey)
    if [ "$direct" = "shardval" ] && [ -z "$inner" ]; then
        row $sec decoy-blind-inner-eval "$cfg" KNOWN "inner redis.call GET reads decoy -> nil (pre-phase-2, documented)"
    elif [ "$direct" = "shardval" ] && [ "$inner" = "shardval" ]; then
        row $sec decoy-blind-inner-eval "$cfg" FAIL "inner EVAL now sees shard data — behavior changed (improvement?); update the ledger"
    else
        row $sec decoy-blind-inner-eval "$cfg" FAIL "direct=[$direct] inner=[$inner]"
    fi
    # LCS is now PORTED across shards (cmd_coverage validates its output); the old "guard message
    # intact" probe is removed — it asserted rejection, which no longer holds and never checked output.
    row $sec debug-reload-ledger "$cfg" "${D_RELOAD_RESULT:-SUSPECT}" "${D_RELOAD_DETAIL:-section D reload cell did not run}"

    local cm; cm=$(crash_scan "$flog")
    [ -z "$cm" ] && row E crash-scan "$cfg" PASS "server log clean" || row E crash-scan "$cfg" FAIL "$cm"
    stop_srv "$fpid"
}

# ===========================================================================
# SECTION F — STRESS SPOT-CHECKS
# ===========================================================================
f_cell() { # name extra-args...
    local name=$1; shift
    local sec=F cfg="$name"
    local fpid flog info i cm
    boot_srv fork "$FORK_PORT" "$WORK/f_${name//\//_}" "$@" \
        || { row $sec churn "$cfg" FAIL "boot failed (flags: $*)"; return; }
    fpid=$BOOT_PID; flog=$LAST_SRV_LOG
    for i in $(seq 0 31); do tcli "$FORK_PORT" SET "fsent:$i" "sv-$i-$TREE_REV" >/dev/null; done
    if ! command -v memtier_benchmark >/dev/null; then
        row $sec churn "$cfg" SUSPECT "memtier not on PATH; stress skipped"; stop_srv "$fpid"; return
    fi
    local mt=$WORK/f_${name//\//_}.memtier
    lg_run timeout $((STRESS_T+120)) memtier_benchmark -s 127.0.0.1 -p "$FORK_PORT" -t 2 -c 25 --pipeline=4 \
        --ratio=1:1 --key-pattern=R:R --key-maximum=500000 -d 64 --test-time="$STRESS_T" \
        --hide-histogram > "$mt" 2>&1
    local mrc=$?
    # NB: memtier Totals LAST column is KB/sec; col2 = Ops/sec (plausibility gate).
    # opsec must be validated NUMERIC before the -lt test: with a garbage token the
    # old `-lt 5000 2>/dev/null` errored (=false) and fell through to PASS.
    local opsec; opsec=$(awk '/^Totals/{print $2; exit}' "$mt" | cut -d. -f1)
    if [ "$mrc" -ne 0 ]; then
        row $sec churn "$cfg" SUSPECT "memtier rc=$mrc (see $mt)"
    elif ! printf '%s' "$opsec" | grep -qE '^[0-9]+$'; then
        row $sec churn "$cfg" SUSPECT "could not parse memtier Totals ops/sec (got [$opsec]; see $mt)"
    elif [ "$opsec" -lt 5000 ]; then
        row $sec churn "$cfg" SUSPECT "implausible load: memtier ops/sec=$opsec (<5000) — load did not run properly"
    else
        row $sec churn "$cfg" PASS "churn ${STRESS_T}s at $opsec ops/s"
    fi
    if ! assert_server "$FORK_PORT" "$fpid"; then
        row $sec post-alive "$cfg" FAIL "server dead/hijacked after churn; log=$flog"; stop_srv "$fpid"; return
    fi
    local sok=0 v
    for i in $(seq 0 31); do
        v=$(tcli "$FORK_PORT" GET "fsent:$i"); [ "$v" = "sv-$i-$TREE_REV" ] && sok=$((sok+1))
    done
    [ "$sok" -eq 32 ] && row $sec sentinel-readback "$cfg" PASS "32/32 sentinels intact" \
        || row $sec sentinel-readback "$cfg" FAIL "sentinels intact: $sok/32"
    local dg; dg=$(timeout 120 "$CLI" -p "$FORK_PORT" DEBUG DIGEST 2>&1)
    if is_digest "$dg"; then
        row $sec digest "$cfg" PASS "digest=${dg:0:20}"
    else
        row $sec digest "$cfg" FAIL "digest not a 40-hex nonzero digest: $(printf '%s' "$dg" | head -c 80)"
    fi
    info=$(tcli "$FORK_PORT" INFO stats)   # ONE call for the counter read
    local qf; qf=$(info_field "$info" tomokv_ex_queue_full)
    [ "${qf:-x}" = "0" ] && row $sec exqueue-full-zero "$cfg" PASS "tomokv_ex_queue_full=0 under normal load" \
        || row $sec exqueue-full-zero "$cfg" SUSPECT "tomokv_ex_queue_full=$qf (nonzero under normal load — undersized auto ring?)"
    local rss; rss=$(awk '/VmRSS/{print $2}' "/proc/$fpid/status" 2>/dev/null)
    if [ -n "$rss" ] && [ "$rss" -lt 3000000 ] 2>/dev/null; then
        row $sec rss-bound "$cfg" PASS "VmRSS=${rss}kB (<3GB)"
    else
        row $sec rss-bound "$cfg" FAIL "VmRSS=${rss:-unknown}kB (bound 3GB)"
    fi
    cm=$(crash_scan "$flog")
    [ -z "$cm" ] && row $sec crash-scan "$cfg" PASS "server log clean" || row $sec crash-scan "$cfg" FAIL "$cm"
    stop_srv "$fpid"
}

section_F() {
    log "=== SECTION F: stress spot-checks (${STRESS_T}s per config) ==="
    f_cell "io2ex2/default"     "${DEF_TOPO[@]}"
    f_cell "numa2-io1ex2pn"     --tomokv-nodes 2 --tomokv-thread-io 1 --tomokv-thread-ex 2
    f_cell "io2ex2/thread-mode-auto"   "${DEF_TOPO[@]}" --tomokv-thread-mode auto
    f_cell "io2ex2/thread-mode-static" "${DEF_TOPO[@]}" --tomokv-thread-mode static
}

# ===========================================================================
# main
# ===========================================================================
START_TS=$(date +%s)
log "feature_sweep start (SMOKE=$SMOKE) tree=$TREE rev=$TREE_REV bin=$FORKSRV sha=$(sha256sum \"$FORKSRV\" 2>/dev/null | cut -c1-12)"
[ -s "$HOTFILE" ] || log "WARNING: hot-key cache empty; helper will regenerate (slow)"

section_A     2>>"$LOGDIR/sc_A.log"
section_B     2>>"$LOGDIR/sc_B.log"
section_C     2>>"$LOGDIR/sc_C.log"
section_D     2>>"$LOGDIR/sc_D.log"
section_EG    2>>"$LOGDIR/sc_E.log"
section_F     2>>"$LOGDIR/sc_F.log"

ELAPSED=$(( $(date +%s) - START_TS ))
printf '# done in %ss: FAIL=%d SUSPECT=%d (remaining rows are PASS/KNOWN)\n' "$ELAPSED" "$NFAIL" "$NSUSPECT" >> "$TSV"
log "DONE in ${ELAPSED}s — FAIL=$NFAIL SUSPECT=$NSUSPECT — results: $TSV"
[ "$NFAIL" -eq 0 ]
