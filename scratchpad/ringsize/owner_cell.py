#!/usr/bin/env python3
"""THE CELL THAT DECIDES THIS LANE -- written to run on the owner's 32-core box, not on this rig.

WHY IT EXISTS
    This lane measured its whole matrix at two shards on two cores, the only geometry in which its
    null passes on the six cores it owns, and shelved itself on the result. The owner then ran the
    governing control at sixteen shards and the sign flipped: read-local WINS +14.0% on the
    alternating shape there (24.17M against 21.21M) where it LOST 45.9% on the small rig, and LOSES
    4.2% on the blocked shape (20.21M against 21.10M). That losing case is exactly the regime this
    lane exists to fix -- the ring fills, the connection disarms, and the armed cost is paid for
    nothing -- so the shelve verdict cannot stand on the small rig's numbers.

THE ONE CORRECTION TO THE PROPOSED ACCEPTANCE RULE
    "POST at or above the read-local-0 line" compares across two trees: that line was measured on
    mainline t9final, while PRE and POST are t-rlbatch (479922c0a) with and without this lane's
    header. PRE *must* be t-rlbatch -- it already carries the base lane's demote-wave fix, and
    rebuilding this change on mainline instead would measure two changes at once. So the
    read-local-0 line is measured HERE, from the SAME tree, as a third arm:

        PRE   tomokv-pre   --read-local 1    base lane: ring overflows, connection disarms
        POST  tomokv-post  --read-local 1    this lane: ring sized to the ROB window
        RL0   tomokv-pre   --read-local 0    the ordinary owner-task path, same tree  <- the line

    RL0 is the same in either binary (with the feature off no sidecar is allocated); PRE carries it
    so that one binary supplies the PRE/RL0 pair and only the knob differs between them.

SHAPES, and why these three
    A connection's live writes are those published and unretired inside its 32-deep pipeline window,
    and memtier emits its ratio as repeating BLOCKS -- which this lane established by measurement:
    at the identical 50% write fraction, --ratio=1:1 demoted 738 reads and --ratio=50:50 demoted
    2,072,492. So the ratio is a write RUN LENGTH, and the ring's sixteen slots are a threshold on it.

        1:1     alternating   at most 15 live writes  -> ring NEVER fills   (control: must not move)
        5:5     blocked       about 17 live writes    -> just over          (the owner's -4.2% cell)
        10:10   blocked       about 22 live writes    -> firmly over        (the longer run)

USAGE
    owner_cell.py <serverCpuList> <clientCpuList> [--rounds N]
      e.g.  owner_cell.py 0-15 16-31 --rounds 2

    The server takes one cpu per shard. The client list must be disjoint from the server's cpus AND
    from their SMT siblings: a server measured with a co-tenant on its own execution units reports
    an IPC and a cycles/op that belong to the co-tenant.
"""
import argparse, csv, hashlib, os, re, signal, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

# PINNED SOURCE IS NOT A PINNED BINARY. These digests are what this lane measured and what its notes
# describe; a rebuild that changed either makes every number here a different experiment.
ARMS = {
    'PRE':  (os.path.join(ROOT, 'build', 'tomokv-pre'),  'a5906e93547614a42067c7da9931f93b', 1),
    'POST': (os.path.join(ROOT, 'build', 'tomokv-post'), '5764edfb188073474bb613683af0b1fd', 1),
    'RL0':  (os.path.join(ROOT, 'build', 'tomokv-pre'),  'a5906e93547614a42067c7da9931f93b', 0),
}
SHAPES = ['10:10', '1:1', '5:5']

# THE LOAD LADDER, because the first run of this cell measured the load generator.
#
# Eight generator threads is what a two-core server needs and nowhere near what sixteen shards need.
# The first run drew 10.8-11.2 of 16 cores armed and 12.0-12.2 unarmed at 7.7-8.1 M ops/s, against
# 20-24 M in the owner's own saturated control -- so nothing was saturated, every rate was the
# generator's number, and PRE against POST came back a null that could not mean anything. A cell
# that cannot saturate must say so instead of reporting the null.
#
# So the geometry is no longer written down: it is found. The ladder holds the server fixed and
# grows the generator until BOTH conditions hold -- the rate stops rising (a rung buys less than
# GAIN_STOP) and the server is genuinely busy (idle under IDLE_MAX of its allocation). The first
# rung that satisfies both is where the three arms are measured. If no rung does, the run says
# NOT SATURATED and the report refuses to read a rate from it.
#
# Connections stay at 512 through the first three rungs so that only generator PARALLELISM changes
# -- 32 x 16 is the owner's own rig shape and reached 20-24 M there -- and only then does the
# connection count grow. Pipeline depth is never laddered: the shape arithmetic depends on it
# (a 10:10 block puts about twenty-two live writes in a 32-deep window), so moving it would change
# the experiment rather than the load.
LADDER = [(8, 64), (16, 32), (32, 16), (32, 32), (32, 64)]
GAIN_STOP = 0.015      # a rung that buys less than 1.5% is the plateau
IDLE_MAX = 0.02        # server must be within 2% of its core allocation
# Visit order within a round: three arms, balanced against drift in both directions.
ORDER = ['PRE', 'POST', 'RL0', 'RL0', 'POST', 'PRE']


def cpus(spec):
    out = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, **kw)


def port_free(port):
    r = sh(['ss', '-H', '-ltn', f'sport = :{port}'])
    return not r.stdout.strip()


def wait_pinned(pid, want, label, timeout=5.0):
    """Wait for the mask we asked for, do not accept the first one readable.

    `taskset -c LIST cmd` forks, sets its OWN affinity, and only then execs, so a check that takes
    the first readable value can read the inherited full-machine mask from a process that is about
    to be pinned correctly -- and fail a run over a race. It killed a phase on this lane once.
    """
    want = cpus(want)
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with open(f'/proc/{pid}/status') as f:
                m = re.search(r'^Cpus_allowed_list:\s*(.+)$', f.read(), re.M)
        except OSError:
            break
        if m:
            last = m.group(1).strip()
            if cpus(last) == want:
                return True
        time.sleep(0.02)
    print(f'PIN FAIL: {label} (pid {pid}) settled on [{last}], expected [{sorted(want)[0]}..]',
          file=sys.stderr)
    return False


class Server:
    def __init__(self, binary, read_local, srvcpus, port, shards, logpath):
        self.port, self.log = port, logpath
        if not port_free(port):
            raise RuntimeError(f'port {port} is already in use')
        self.fh = open(logpath, 'w')
        self.p = subprocess.Popen(
            ['taskset', '-c', srvcpus, binary, '--port', str(port), '--bind', '127.0.0.1',
             '--shards', str(shards), '--thread-mode', 'fused',
             '--read-local', str(read_local), '--atomic', '0', '--enable-debug-command', 'yes'],
            stdout=self.fh, stderr=subprocess.STDOUT)
        if not wait_pinned(self.p.pid, srvcpus, 'server'):
            self.stop(); raise RuntimeError('server pin failed')
        for _ in range(300):
            if self.p.poll() is not None:
                self._die('BOOT DIED')
            if not port_free(port):
                return
            time.sleep(0.2)
        self._die('BOOT TIMEOUT')

    def _die(self, why):
        # A FAILED BOOT PRINTS ITS OWN LOG. The server always says why it refused -- "16 threads but
        # only 8 allowed cpus" is a correct refusal that reads as a mystery until somebody prints it.
        self.fh.flush()
        tail = open(self.log).read().splitlines()[-25:]
        raise RuntimeError(f'{why} -- last lines of {self.log}:\n  ' + '\n  '.join(tail))

    def info(self, field):
        r = sh([CLI, '-p', str(self.port), 'info', 'all'])
        m = re.search(rf'^{re.escape(field)}:(.*)$', r.stdout.replace('\r', ''), re.M)
        return float(m.group(1)) if m else 0.0

    def cpu_jiffies(self):
        with open(f'/proc/{self.p.pid}/stat') as f:
            parts = f.read().rsplit(')', 1)[1].split()
        return int(parts[11]) + int(parts[12])          # utime + stime

    def stop(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.p.kill(); self.p.wait()
        self.fh.close()


CLI = os.environ.get('CLI', '/tmp/claude-1000/redis74/src/redis-cli')


def pick_fills_event():
    ev = os.environ.get('FILLS', 'ls_any_fills_from_sys.dram_io_all')
    r = sh(['perf', 'stat', '-e', ev, '-x,', '-o', '/dev/null', '--', 'true'])
    return ev if r.returncode == 0 else 'cache-misses'


def run_cell(srv, arm, read_local, shape, clicpus, args, out, rnd, vi, fills_ev):
    base = {k: srv.info(k) for k in ('read_local_hits', 'read_local_fallback_inflight_write',
                                     'read_local_fallbacks', 'total_commands_processed')}
    j0, t0 = srv.cpu_jiffies(), time.time()
    tag = f'{arm}-{rnd}-{vi}-{shape.replace(":", "x")}'
    perf_out = os.path.join(out, f'perf-{tag}.txt')
    mt_out = os.path.join(out, f'mt-{tag}.txt')
    # PERF FOLLOWS THE SERVER PROCESS, not its cpus: `-C` counts every cycle those cpus spend in C0,
    # the idle task's included, which makes cycles/op and fills/op properties of the cpu rather than
    # of the server. perf cannot take a pid AND a command (it counts the command and reports
    # <not counted> for the pid, silently), so it attaches first and is stopped with SIGINT.
    perf = subprocess.Popen(['perf', 'stat', '-e', f'instructions,cycles,{fills_ev}',
                             '-x,', '-o', perf_out, '-p', str(srv.p.pid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(mt_out, 'w') as mf:
        mt = subprocess.Popen(
            ['taskset', '-c', clicpus, 'memtier_benchmark', '-s', '127.0.0.1',
             '-p', str(srv.port), '--hide-histogram', f'--key-maximum={args.keymax}',
             '--key-minimum=1', '--data-size=32', '--key-pattern=R:R', f'--ratio={shape}',
             '-t', str(args.threads), '-c', str(args.conns), f'--pipeline={args.pipeline}',
             f'--test-time={args.secs}'], stdout=mf, stderr=subprocess.STDOUT)
        if not wait_pinned(mt.pid, clicpus, 'load generator'):
            perf.send_signal(signal.SIGINT); mt.kill(); raise RuntimeError('generator pin failed')
        mt.wait()
    perf.send_signal(signal.SIGINT); perf.wait()
    j1, t1 = srv.cpu_jiffies(), time.time()
    wall = max(0.001, t1 - t0)

    totals = None
    for line in open(mt_out):
        if line.startswith('Totals'):
            totals = line.split()
    if not totals:
        raise RuntimeError(f'{tag}: memtier produced no Totals line; see {mt_out}')
    rate, p50, p99 = float(totals[1]), float(totals[5]), float(totals[6])

    ctr = {k: srv.info(k) - v for k, v in base.items()}
    cmds = ctr['total_commands_processed']
    # A RATE IS NOT EVIDENCE THAT WORK HAPPENED. memtier counts an error reply as an operation, so a
    # cell whose every command was rejected reports a plausible throughput while the server's own
    # counter does not move. That is not hypothetical: it cost this lane an entire regime table,
    # 730k ops/s of "-ERR wrong number of arguments" with the command counter moving by four.
    if cmds < 1000 or cmds < 0.5 * rate * wall:
        errs = [l for l in open(mt_out) if re.search('error|ERR |refused', l, re.I)][:6]
        raise RuntimeError(f'VACUOUS CELL {tag}: memtier claims {rate:.0f} ops/s but the server\'s '
                           f'total_commands_processed moved by {cmds:.0f}.\n  ' + '  '.join(errs))

    perf_vals = {}
    for line in open(perf_out):
        f = line.split(',')
        if len(f) > 2 and re.match(r'^[0-9]+$', f[0]):
            perf_vals[f[2]] = float(f[0])
    mux = min([float(f.split(',')[4]) for f in open(perf_out)
               if len(f.split(',')) > 4 and re.match(r'^[0-9.]+$', f.split(',')[4].strip() or 'x')]
              or [100.0])

    row = dict(round=rnd, visit=vi, arm=arm, readlocal=read_local, shape=shape,
               rate=rate, p50=p50, p99=p99, cmds=cmds,
               instr=perf_vals.get('instructions', 0), cycles=perf_vals.get('cycles', 0),
               fills=perf_vals.get(fills_ev, 0),
               hits=ctr['read_local_hits'], demoted=ctr['read_local_fallback_inflight_write'],
               fallbacks=ctr['read_local_fallbacks'],
               srv_cores=(j1 - j0) / os.sysconf('SC_CLK_TCK') / wall, srv_cpus=NSRV,
               threads=args.threads, conns=args.threads * args.conns, wall=wall, mux=mux)
    tot = row['hits'] + row['fallbacks']
    row['cpu_per_mop'] = row['srv_cores'] / (rate / 1e6) if rate else float('nan')
    print(f"  {arm:<5} rl={read_local} {shape:<6} rate={rate/1e6:8.3f}M  "
          f"instr/op={row['instr']/cmds:7.0f}  demoted={row['demoted']:12,.0f}  "
          f"local={100*row['hits']/tot if tot else 0:5.1f}%  "
          f"srv={row['srv_cores']:5.2f}/{NSRV} cores  cpu/Mop={row['cpu_per_mop']:.3f}")
    return row


NSRV = 0        # size of the server's cpu allocation; set in main(), carried into every row


def run_ladder(args, fills_ev):
    """Grow the generator until the server is the thing being measured, and say so if it never is.

    Escalates on the POST arm at the 10:10 shape -- the arm under test, in the regime the fix bites.
    Returns (threads, conns_per_thread, saturated, rows).
    """
    print('\n=== LOAD LADDER: growing the generator until the server is the bottleneck ===')
    binary, _, rl = ARMS['POST']
    rows, best = [], 0.0
    chosen = None
    for i, (th, cn) in enumerate(LADDER):
        args.threads, args.conns = th, cn
        srv = Server(binary, rl, args.srvcpus, args.port, args.shards,
                     os.path.join(args.out, f'srv-ladder-{th}x{cn}.log'))
        try:
            preload(srv, args)
            row = run_cell(srv, 'LADDER', rl, '10:10', args.clicpus, args, args.out,
                           0, i + 1, fills_ev)
        finally:
            srv.stop(); time.sleep(2)
        rows.append(row)
        idle = 1.0 - row['srv_cores'] / NSRV
        gain = (row['rate'] - best) / best if best else 1.0
        print(f"    rung {i+1}: {th}x{cn} = {th*cn} conns   {row['rate']/1e6:.3f} M ops/s   "
              f"gain {gain*100:+.1f}%   server idle {idle*100:.1f}%")
        best = max(best, row['rate'])
        # BOTH conditions, and in this order: a rung that stopped gaining while the server is still
        # idle is a generator that ran out of capacity, not a server that ran out of headroom.
        if idle <= IDLE_MAX and gain < GAIN_STOP and i > 0:
            chosen = (th, cn)
            print(f"    -> SATURATED at rung {i+1}: idle {idle*100:.1f}% <= {IDLE_MAX*100:.0f}% "
                  f"and the last rung bought {gain*100:+.1f}%")
            break
        if idle <= IDLE_MAX and i == len(LADDER) - 1:
            chosen = (th, cn)
            print(f"    -> SATURATED at the last rung: idle {idle*100:.1f}%")
            break
    if chosen is None:
        last = rows[-1]
        idle = 1.0 - last['srv_cores'] / NSRV
        print(f"    -> NOT SATURATED: the ladder ran out at {LADDER[-1]} with the server "
              f"{idle*100:.1f}% idle. The generator is the wall, not the server.")
        print("       Rates from this run are the generator's; only CPU per unit work may be read.")
        chosen = LADDER[-1]
    return chosen[0], chosen[1], chosen is not None and (1.0 - rows[-1]['srv_cores'] / NSRV) <= IDLE_MAX, rows


def preload(srv, args):
    """dbsize pinned to keymax: a GET mix on an unpopulated keyspace is a MISS mix."""
    pre = subprocess.Popen(
        ['taskset', '-c', args.clicpus, 'memtier_benchmark', '-s', '127.0.0.1',
         '-p', str(args.port), '--hide-histogram', f'--key-maximum={args.keymax}',
         '--key-minimum=1', '--data-size=32', '--key-pattern=P:P', '--ratio=1:0',
         '-t', '8', '-c', '8', '--pipeline=32', '-n', str(args.keymax // 64)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_pinned(pre.pid, args.clicpus, 'preload'):
        raise RuntimeError('preload pin failed')
    pre.wait()
    size = sh([CLI, '-p', str(args.port), 'dbsize']).stdout.strip()
    if size != str(args.keymax):
        raise RuntimeError(f'dbsize={size} keymax={args.keymax}: a GET mix on an unpopulated '
                           f'keyspace measures a different server')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('srvcpus'); ap.add_argument('clicpus')
    ap.add_argument('--rounds', type=int, default=2)
    ap.add_argument('--shards', type=int, default=16)
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--conns', type=int, default=64)     # 8 x 64 = 512 connections
    ap.add_argument('--pipeline', type=int, default=32)
    ap.add_argument('--secs', type=int, default=15)
    ap.add_argument('--keymax', type=int, default=200000)
    ap.add_argument('--port', type=int, default=8300)
    ap.add_argument('--out', default='/tmp/ringsize-owner-cell')
    ap.add_argument('--shapes', default=','.join(SHAPES),
                    help='comma-separated memtier ratios; these are write RUN LENGTHS, not fractions')
    ap.add_argument('--no-ladder', action='store_true',
                    help='trust --threads/--conns instead of finding saturation (not recommended: '
                         'the first run of this cell measured the load generator)')
    args = ap.parse_args()

    global NSRV
    os.makedirs(args.out, exist_ok=True)
    NSRV = len(cpus(args.srvcpus))
    if cpus(args.srvcpus) & cpus(args.clicpus):
        sys.exit('REFUSING: server and load generator share cpus')
    if len(cpus(args.srvcpus)) < args.shards:
        sys.exit(f'REFUSING: {args.shards} shards but only {len(cpus(args.srvcpus))} server cpus '
                 f'-- the server refuses this too, and is right to')
    seen = {}
    for arm, (binary, want, rl) in ARMS.items():
        if not os.path.exists(binary):
            sys.exit(f'MISSING {arm} binary: {binary}')
        got = md5(binary)
        if got != want:
            sys.exit(f'{arm} DIGEST MISMATCH: {binary} is {got}, expected {want}')
        seen[arm] = got
        print(f'{arm:<5} {binary} md5={got} read-local={rl}')
    if seen['PRE'] == seen['POST']:
        sys.exit('REFUSING: the two arms are byte-identical -- one of them did not rebuild')

    fills_ev = pick_fills_event()
    shapes = [x.strip() for x in args.shapes.split(',') if x.strip()]
    print(f'fills event: {fills_ev}   shapes: {" ".join(shapes)}   '
          f'server {NSRV} cpus [{args.srvcpus}], generator [{args.clicpus}]')

    saturated = True
    if not args.no_ladder:
        th, cn, saturated, _ = run_ladder(args, fills_ev)
        args.threads, args.conns = th, cn
    print(f'\n=== MEASURING at {args.threads}x{args.conns} = {args.threads*args.conns} '
          f'connections, p{args.pipeline}, saturated={saturated} ===')
    with open(os.path.join(args.out, 'geometry.txt'), 'w') as g:
        g.write(f'threads={args.threads}\nconns={args.conns}\n'
                f'total_conns={args.threads*args.conns}\npipeline={args.pipeline}\n'
                f'srv_cpus={NSRV}\nsaturated={"yes" if saturated else "no"}\n')

    csv_path = os.path.join(args.out, 'owner_cell.csv')
    new = not os.path.exists(csv_path)
    fh = open(csv_path, 'a', newline='')
    writer = None
    for rnd in range(1, args.rounds + 1):
        for vi, arm in enumerate(ORDER, 1):
            binary, _, rl = ARMS[arm]
            srv = Server(binary, rl, args.srvcpus, args.port, args.shards,
                         os.path.join(args.out, f'srv-{arm}-{rnd}-{vi}.log'))
            try:
                preload(srv, args)
                for shape in shapes:
                    row = run_cell(srv, arm, rl, shape, args.clicpus, args, args.out,
                                   rnd, vi, fills_ev)
                    if writer is None:
                        writer = csv.DictWriter(fh, fieldnames=list(row))
                        if new:
                            writer.writeheader()
                    writer.writerow(row); fh.flush()
            finally:
                srv.stop()
                time.sleep(3)
        print(f'round {rnd} done @ {time.strftime("%T")}')
    fh.close()
    print(f'\nwrote {csv_path}')
    subprocess.run([sys.executable, os.path.join(HERE, 'owner_cell_report.py'), csv_path])


if __name__ == '__main__':
    main()
