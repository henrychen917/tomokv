#!/usr/bin/env python3
"""mset8fix: a lone IO connection refused by the global atomic window must not wait for a timer.

--atomic 1 admits every cross-shard MSET through one global credit window (16 x shards, at most
1024). A refused frame stays unconsumed on its IO thread. If that thread then has nothing else to
do it parks, and PRE has no path from another IO's credit retirement to the parked thread: only the
50 ms ring-wait timeout (or the client-cron beat) rescues it. --hz 1 removes the cron cap, so on
PRE every such stall costs a full 50 ms.

Each repetition boots a fresh server (--shards 16: a 256-credit window) and places, through
DEBUG IO-THREAD, exactly one PROBE connection alone on one IO thread and HOG connections on every
other IO thread. Every connection runs batch-synchronous pipelines of 32 MSET8 over its own eight
keys, which DEBUG SHARDS proves cover eight distinct shards (so every MSET is an admitted group).
The hogs keep far more than 256 MSETs outstanding.

A repetition PASSES iff all of these hold:
  * the window really refused admissions: INFO atomic_window_stalls grew (otherwise the leg is a
    vacuous FAIL, never a pass);
  * the probe's maximum batch latency is below --max-ms (20 ms);
  * the probe completed at least --min-share (25%) of the median hog's batches;
  * every reply was +OK, and the probe's eight keys hold its last write afterwards;
  * no connection changed IO thread during the load.
No reply is retried and no failed repetition is re-rolled: each one is a verdict.
"""
import argparse
import json
import multiprocessing
import os
from pathlib import Path
import selectors
import socket
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import Conn, encode, info, lbsignals, topology, wait_ready  # noqa: E402
from _gate_process import stop_process  # noqa: E402

PIPELINE = 32
EXPECT = b'+OK\r\n' * PIPELINE


def cpu_list(spec):
    out = set()
    for item in spec.split(','):
        lo, _, hi = item.partition('-')
        out.update(range(int(lo), int(hi or lo) + 1))
    return sorted(out)


def batch(keys, tag):
    frames = []
    for i in range(PIPELINE):
        value = f'{tag}:{i}'
        args = ['MSET']
        for key in keys:
            args += [key, value]
        frames.append(encode(*args))
    return b''.join(frames)


def driver(role, slots, start_at, seconds, pipe, cpu):
    """One protocol process. Probe and hogs never share a process (or a CPU when possible)."""
    try:
        os.sched_setaffinity(0, {cpu})
        selector = selectors.DefaultSelector()
        states = []
        for index, slot in enumerate(slots):
            sock = socket.socket(fileno=slot['fd'])
            sock.setblocking(True)
            state = dict(sock=sock, name=slot['name'], keys=slot['keys'], buf=bytearray(),
                         batches=0, sent=0, max_ns=0, latencies=[], error=None, done=False,
                         payload=batch(slot['keys'], 'h') if role == 'hog' else None,
                         next_payload=None)
            if role == 'probe':
                state['next_payload'] = batch(slot['keys'], 'p:0')
            selector.register(sock, selectors.EVENT_READ, state)
            states.append(state)
        while time.time() < start_at:
            time.sleep(min(.001, max(0, start_at - time.time())))
        deadline = time.monotonic() + seconds

        def send(state):
            if role == 'probe':
                payload = state['next_payload']
            else:
                payload = state['payload']
            state['sent'] = time.monotonic_ns()
            state['sock'].sendall(payload)
            if role == 'probe':
                state['next_payload'] = batch(state['keys'], f"p:{state['batches'] + 1}")

        for state in states:
            send(state)
        active = len(states)
        hard = deadline + 60
        while active:
            if time.monotonic() > hard:
                raise TimeoutError('replies did not drain within 60 s of the deadline')
            for key, _ in selector.select(timeout=.5):
                state = key.data
                data = state['sock'].recv(1 << 16)
                if not data:
                    raise EOFError(f"{state['name']}: server closed the connection")
                state['buf'] += data
                while True:
                    have = len(state['buf'])
                    if bytes(state['buf'][:min(have, len(EXPECT))]) != EXPECT[:min(have, len(EXPECT))]:
                        raise AssertionError(f"{state['name']}: unexpected reply bytes "
                                             f"{bytes(state['buf'][:120])!r}")
                    if have < len(EXPECT):
                        break
                    del state['buf'][:len(EXPECT)]
                    elapsed = time.monotonic_ns() - state['sent']
                    state['batches'] += 1
                    state['max_ns'] = max(state['max_ns'], elapsed)
                    if role == 'probe':
                        state['latencies'].append(elapsed)
                    if time.monotonic() < deadline:
                        send(state)
                    else:
                        state['done'] = True
                        selector.unregister(state['sock'])
                        active -= 1
                        break
                if state['done'] and state['buf']:
                    raise AssertionError(f"{state['name']}: bytes after the final batch")
        pipe.send(dict(role=role, results=[
            dict(name=s['name'], batches=s['batches'], max_ms=s['max_ns'] / 1e6,
                 latencies_ms=[x / 1e6 for x in s['latencies']]) for s in states]))
    except BaseException as error:  # the parent turns this into a FAIL verdict
        pipe.send(dict(role=role, error=repr(error)))
    finally:
        pipe.close()


def boot(a, label, read_local, databases):
    out = a.output
    out.mkdir(parents=True, exist_ok=True)
    listening = subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{a.port}'], text=True).strip()
    if listening:
        raise AssertionError(f'port {a.port} is already listening: {listening}')
    argv = ['taskset', '-c', a.cores, str(a.binary.resolve()), '--bind', '127.0.0.1',
            '--port', str(a.port), '--save', '', '--appendonly', 'no', '--dir', str(out.resolve()),
            '--databases', str(databases), '--enable-debug-command', 'yes',
            '--thread-mode', a.mode, '--read-local', str(read_local), '--atomic', '1',
            '--shards', '16', '--hz', '1', '--dynamic-hz', 'no', '--key-lb', '0',
            '--client-lb', '0', '--net-io', a.engine]
    if a.mode == '2s':
        argv += ['--ratio', a.ratio, '--flip-auto', '0']
    (out / f'{label}-argv.json').write_text(json.dumps(argv) + '\n')
    log = (out / f'{label}-server.log').open('w')
    process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                               env=dict(os.environ, LC_ALL='C'))
    return process, log


def io_thread(conn):
    reply = conn.must('DEBUG', 'IO-THREAD')
    if not isinstance(reply, int):
        raise AssertionError(f'DEBUG IO-THREAD returned {reply!r}')
    return reply


def private_keys(admin, prefix, used):
    """Eight keys on eight distinct shards, so every MSET8 is a cross-shard admitted group."""
    names = [f'{prefix}:{j}' for j in range(96)]
    chosen, shards = [], set()
    for name, (sid, _owner) in zip(names, admin.must('DEBUG', 'SHARDS', *names)):
        if sid not in shards:
            shards.add(sid)
            chosen.append(name)
        if len(chosen) == 8:
            break
    if len(chosen) != 8:
        raise AssertionError(f'{prefix}: could not find eight distinct shards')
    used.update(chosen)
    return chosen


def place(a, admin, io_threads):
    """Exactly one probe alone on IO thread P; a.hogs hog connections on every other IO thread."""
    admin_thread = io_thread(admin)
    candidates = [t for t in io_threads if t != admin_thread]
    if not candidates:
        raise AssertionError('no IO thread other than the admin connection')
    probe_thread = candidates[0]
    want = {t: (1 if t == probe_thread else a.hogs) for t in io_threads}
    by_thread = {t: [] for t in io_threads}
    extras = []
    for _ in range(40 * len(io_threads) * (a.hogs + 1)):
        if all(len(by_thread[t]) >= want[t] for t in io_threads):
            break
        conn = Conn('127.0.0.1', a.port, timeout=30)
        owner = io_thread(conn)
        if owner not in by_thread:
            raise AssertionError(f'connection placed on non-IO thread {owner} (IO: {io_threads})')
        if len(by_thread[owner]) < want[owner]:
            by_thread[owner].append(conn)
        else:
            extras.append(conn)
    else:
        raise AssertionError(f'placement did not converge: { {t: len(v) for t, v in by_thread.items()} }')
    for conn in extras:
        conn.close()
    probe = by_thread[probe_thread][0]
    hogs = [(t, c) for t in io_threads if t != probe_thread for c in by_thread[t]]
    return probe_thread, admin_thread, probe, hogs, len(extras)


def repetition(a, read_local, databases, rep):
    label = f'rl{read_local}-db{databases}-rep{rep}'
    result = dict(label=label, read_local=read_local, databases=databases, rep=rep,
                  mode=a.mode, engine=a.engine, passed=False, reasons=[])
    process, log = boot(a, label, read_local, databases)
    admin = None
    conns = []
    try:
        admin = wait_ready('127.0.0.1', a.port, process=process, timeout=60)
        server = info(admin, 'server')
        expected = dict(thread_mode=a.mode, atomic='1', shards='16', hz='1')
        for field, value in expected.items():
            if server.get(field) != value:
                raise AssertionError(f'INFO server {field}={server.get(field)!r}, wanted {value!r}')
        roles = topology(admin).roles
        io_threads = sorted(t for t, role in roles.items() if role == ('fused' if a.mode == '1s' else 'io'))
        if len(io_threads) < 2:
            raise AssertionError(f'need two IO threads, found {roles}')
        probe_thread, admin_thread, probe, hogs, closed = place(a, admin, io_threads)
        conns = [probe] + [c for _, c in hogs]
        used = set()
        probe_keys = private_keys(admin, f'aw:{label}:probe', used)
        hog_keys = [private_keys(admin, f'aw:{label}:hog{i}', used) for i in range(len(hogs))]
        result.update(io_threads=io_threads, probe_thread=probe_thread, admin_thread=admin_thread,
                      hogs_per_thread=a.hogs, hog_connections=len(hogs), placement_closed=closed,
                      outstanding_hog_msets=len(hogs) * PIPELINE, window=16 * 16)
        load = [c for c in sorted(os.sched_getaffinity(0)) if c not in set(cpu_list(a.cores))]
        if len(load) < 2:
            raise AssertionError(f'need two load CPUs outside the server mask; have {load}')
        groups = max(1, min(len(load) - 1, len(hogs)))
        before = info(admin, 'stats')
        if 'atomic_window_stalls' not in before:
            raise AssertionError('INFO stats has no atomic_window_stalls')
        context = multiprocessing.get_context('fork')
        start_at = time.time() + .5
        children = []
        plans = [('probe', [dict(fd=probe.sock.fileno(), name='probe', keys=probe_keys)], load[0])]
        for g in range(groups):
            members = [dict(fd=c.sock.fileno(), name=f'hog{i}@io{t}', keys=hog_keys[i])
                       for i, (t, c) in enumerate(hogs) if i % groups == g]
            plans.append(('hog', members, load[1 + g % (len(load) - 1)]))
        for role, slots, cpu in plans:
            parent, child = context.Pipe()
            proc = context.Process(target=driver, args=(role, slots, start_at, a.seconds, child, cpu))
            proc.start()
            child.close()
            children.append((proc, parent))
        reports = []
        for proc, pipe in children:
            if not pipe.poll(a.seconds + 90):
                raise AssertionError('a protocol process did not report')
            reports.append(pipe.recv())
            proc.join(10)
        for report in reports:
            if 'error' in report:
                raise AssertionError(f"{report['role']} driver: {report['error']}")
        after = info(admin, 'stats')
        stalls = int(after['atomic_window_stalls']) - int(before['atomic_window_stalls'])
        rows = [row for report in reports for row in report['results']]
        probe_row = next(r for r in rows if r['name'] == 'probe')
        hog_batches = sorted(r['batches'] for r in rows if r['name'] != 'probe')
        median = statistics.median(hog_batches)
        lat = sorted(probe_row['latencies_ms'])
        # Placement must not have moved under the load (client-lb 0, flip-auto 0).
        moved = [t for t, c in [(probe_thread, probe)] + hogs if io_thread(c) != t]
        final = admin.must('MGET', *probe_keys)
        want = f"p:{probe_row['batches'] - 1}:{PIPELINE - 1}".encode()
        result.update(
            window_stalls=stalls, probe_batches=probe_row['batches'], hog_median_batches=median,
            hog_min_batches=hog_batches[0], hog_max_batches=hog_batches[-1],
            probe_share=(probe_row['batches'] / median) if median else 0.0,
            probe_max_ms=probe_row['max_ms'],
            probe_p50_ms=lat[len(lat) // 2] if lat else None,
            probe_p99_ms=lat[min(len(lat) - 1, int(.99 * len(lat)))] if lat else None,
            probe_batches_ge_20ms=sum(x >= 20 for x in lat),
            probe_batches_ge_45ms=sum(x >= 45 for x in lat),
            hog_max_ms=max(r['max_ms'] for r in rows if r['name'] != 'probe'),
            moved=moved, probe_final=[v.decode() if isinstance(v, bytes) else v for v in final],
            probe_expected=want.decode())
        lbs = {t.tid: dict(role=t.role, wakes_sent=t.wakes_sent, wakes_recv=t.wakes_recv,
                           idle_ns=t.idle_ns, busy_ns=t.busy_ns)
               for t in lbsignals(admin).threads}
        result['threads'] = lbs
        if stalls <= 0:
            result['reasons'].append('vacuous: atomic_window_stalls did not grow (window never refused)')
        if probe_row['max_ms'] >= a.max_ms:
            result['reasons'].append(f"probe max batch latency {probe_row['max_ms']:.2f} ms >= {a.max_ms} ms")
        if median <= 0 or probe_row['batches'] < a.min_share * median:
            result['reasons'].append(f"probe completed {probe_row['batches']} batches < "
                                     f"{a.min_share:.0%} of the median hog's {median}")
        if any(v != want for v in final):
            result['reasons'].append(f'probe keys {final!r} do not hold its last write {want!r}')
        if moved:
            result['reasons'].append(f'connections changed IO thread during the load: {moved}')
        result['passed'] = not result['reasons']
    except BaseException as error:
        result['reasons'].append(f'error: {error!r}')
        result['passed'] = False
    finally:
        for c in conns:
            c.close()
        if admin:
            admin.close()
        forced = stop_process(process)
        log.close()
        result['server_exit'] = dict(rc=process.returncode, forced=forced)
        if forced or process.returncode != 0:
            result['passed'] = False
            result['reasons'].append(f'server exit rc={process.returncode} forced={forced}')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--cores', required=True, help='server CPUs (the slot\'s eight)')
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--mode', choices=('1s', '2s'), required=True)
    p.add_argument('--engine', choices=('uring', 'epoll'), required=True)
    p.add_argument('--read-local', default='0,1')
    p.add_argument('--databases', default='1,16')
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--seconds', type=float, default=5.0)
    p.add_argument('--hogs', type=int, default=6, help='hog connections per non-probe IO thread (>= 4)')
    p.add_argument('--max-ms', type=float, default=20.0)
    p.add_argument('--min-share', type=float, default=.25)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.hogs < 4:
        p.error('--hogs must be at least 4')
    a.output.mkdir(parents=True, exist_ok=True)
    os.environ['LC_ALL'] = 'C'
    legs = []
    for read_local in map(int, a.read_local.split(',')):
        for databases in map(int, a.databases.split(',')):
            for rep in range(a.repeats):
                row = repetition(a, read_local, databases, rep)
                legs.append(row)
                print(json.dumps({k: row.get(k) for k in (
                    'label', 'passed', 'window_stalls', 'probe_batches', 'hog_median_batches',
                    'probe_share', 'probe_max_ms', 'probe_p99_ms', 'probe_batches_ge_20ms',
                    'reasons')}), flush=True)
    passed = all(row['passed'] for row in legs) and bool(legs)
    document = dict(mode=a.mode, engine=a.engine, binary=str(a.binary), ratio=a.ratio,
                    seconds=a.seconds, hogs=a.hogs, max_ms=a.max_ms, min_share=a.min_share,
                    passed=passed, legs=legs)
    (a.output / 'result.json').write_text(json.dumps(document, indent=2) + '\n')
    print(json.dumps(dict(mode=a.mode, engine=a.engine, passed=passed,
                          failed=[row['label'] for row in legs if not row['passed']])), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
