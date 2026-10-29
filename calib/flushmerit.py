#!/usr/bin/env python3
"""Shared mechanics for the three flushmerit instruments (stdlib only).

Fresh owned servers, strict RESP, mirrored ABBA/ABCCBA blocks, explicit CPU
placement, durable per-run evidence and a single final queue verdict.
"""
import argparse
import contextlib
from collections import Counter
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import signal
import socket
import statistics
import subprocess
import sys
import time


class Invalid(RuntimeError):
    pass


class RespError(Invalid):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def encode(*args):
    parts = [b'*%d\r\n' % len(args)]
    for value in args:
        value = value if isinstance(value, bytes) else str(value).encode()
        parts += [b'$%d\r\n' % len(value), value, b'\r\n']
    return b''.join(parts)


class Resp:
    def __init__(self, port, timeout=60):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile('rb')

    def close(self):
        self.file.close()
        self.sock.close()

    def read(self):
        line = self.file.readline()
        require(line.endswith(b'\r\n'), f'short RESP line: {line!r}')
        kind, rest = line[:1], line[1:-2]
        if kind == b'+':
            return rest
        if kind == b'-':
            raise RespError(rest.decode(errors='replace'))
        if kind == b':':
            return int(rest)
        if kind in (b'$', b'*'):
            size = int(rest)
            require(size >= -1, 'invalid RESP length')
            if size == -1:
                return None
            if kind == b'*':
                return [self.read() for _ in range(size)]
            body = self.file.read(size + 2)
            require(len(body) == size + 2 and body[-2:] == b'\r\n', 'short RESP bulk')
            return body[:-2]
        raise Invalid(f'unknown RESP tag {kind!r}')

    def cmd(self, *args):
        self.sock.sendall(encode(*args))
        return self.read()


def ok(reply):
    require(reply == b'OK', f'expected OK, received {reply!r}')


def parse_info(raw):
    require(isinstance(raw, bytes), 'INFO was not a bulk string')
    return dict(line.split(':', 1) for line in raw.decode().splitlines()
                if ':' in line and not line.startswith('#'))


def info(conn):
    return parse_info(conn.cmd('INFO', 'everything'))


FLUSH_COUNTERS = tuple('atomic_flush_' + field for field in
                       ('units', 'range_reads', 'post_versions', 'script_conflicts',
                        'collapses', 'slow_collapses'))
WAIT_COUNTERS = ('atomic_txn_place_waits', 'atomic_txn_writer_waits', 'atomic_txn_waits')
COUNTERS = FLUSH_COUNTERS + WAIT_COUNTERS + (
    'atomic_predecessor_reads', 'atomic_txn_executed', 'atomic_txn_order_violations',
    'keyspace_misses', 'expired_keys', 'evicted_keys', 'rejected_connections',
    'total_error_replies', 'send_errors', 'peer_aborts')


def deltas(before, after):
    values = {}
    for key in COUNTERS:
        require((key in before) == (key in after), f'INFO field disappeared: {key}')
        values[key] = None if key not in before else int(after[key]) - int(before[key])
        require(values[key] is None or values[key] >= 0, f'counter reset: {key}')
    for key in ('atomic_txn_order_violations', 'expired_keys', 'evicted_keys',
                'rejected_connections', 'total_error_replies', 'send_errors', 'peer_aborts'):
        require(values[key] in (None, 0), f'nonzero {key}: {values[key]}')
    return values


def distribution(values):
    """Exact nearest-rank quantiles. Values and returned quantities use ns."""
    require(bool(values), 'empty latency distribution')
    require(all(isinstance(x, int) and x >= 0 for x in values), 'invalid latency')
    ordered = sorted(values)
    return {**{name: ordered[max(0, math.ceil(q * len(ordered)) - 1)]
               for name, q in (('p50', .5), ('p95', .95), ('p99', .99), ('p99.9', .999))},
            'max': ordered[-1], 'n': len(ordered), 'unit': 'ns', 'method': 'nearest-rank'}


def cpus(spec):
    result = []
    for part in spec.split(','):
        ends = part.split('-')
        require(1 <= len(ends) <= 2, 'invalid CPU range')
        lo, hi = int(ends[0]), int(ends[-1])
        require(0 <= lo <= hi, 'invalid CPU range')
        result.extend(range(lo, hi + 1))
    require(result and len(set(result)) == len(result), 'empty or duplicate CPU list')
    return result


def common_parser(description):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--selftest', action='store_true')
    p.add_argument('--candidate')
    p.add_argument('--reference')
    p.add_argument('--third', help='optional C arm, e.g. PAD-A behaviour twin')
    p.add_argument('--third-kind', choices=('behaviour-twin', 'inverse-control'))
    p.add_argument('--output', type=Path)
    p.add_argument('--port', type=int, default=20100)
    p.add_argument('--server-cores', default='0-31')
    p.add_argument('--load-cores', default='32-111')
    p.add_argument('--ratio', help='split io:ex counts; default scales 6:2 to server CPUs')
    p.add_argument('--blocks', type=int, default=3)
    p.add_argument('--modes', default='1s,2s')
    p.add_argument('--databases', default='1,16')
    p.add_argument('--atomics', default='0,1')
    p.add_argument('--flushes', default='SYNC,ASYNC')
    p.add_argument('--smoke', action='store_true', help='explicitly non-merit, allows short/reduced cells')
    p.add_argument('--timeout', type=float, default=120, help='command and drain timeout, seconds')
    return p


def choices(value, allowed):
    selected = value.split(',')
    require(selected and len(set(selected)) == len(selected) and set(selected) <= set(allowed),
            f'invalid selection {value!r}; choose from {allowed}')
    return selected


def configure(args):
    require(args.reference and args.candidate and args.output, 'reference, candidate and output are required')
    require(0 < args.port < 32768 and args.blocks > 0 and args.timeout > 0, 'invalid port/blocks/timeout')
    server, load = cpus(args.server_cores), cpus(args.load_cores)
    require(not set(server) & set(load), 'server/load CPU sets must be disjoint')
    # All orchestration, seeding and subprocesses inherit the load allocation;
    # the server explicitly receives the separate server allocation.
    os.sched_setaffinity(0, set(load))
    if args.ratio is None:
        require(len(server) % 4 == 0, 'auto 6:2 ratio needs a multiple of four server CPUs')
        args.ratio = f'{len(server) * 3 // 4}:{len(server) // 4}'
    ratio = [int(x) for x in args.ratio.split(':')]
    require(len(ratio) == 2 and min(ratio) > 0 and sum(ratio) == len(server), 'ratio must use every server CPU')
    choices(args.modes, ('1s', '2s'))
    choices(args.databases, ('1', '16'))
    choices(args.atomics, ('0', '1'))
    choices(args.flushes, ('SYNC', 'ASYNC'))
    require(bool(args.third) == bool(args.third_kind), '--third and --third-kind must be supplied together')
    arms = dict(A=str(Path(args.reference).resolve()), B=str(Path(args.candidate).resolve()))
    if args.third:
        arms['C'] = str(Path(args.third).resolve())
    require(all(Path(b).is_file() and os.access(b, os.X_OK) for b in arms.values()), 'binary missing/not executable')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    return arms


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as file:
        for chunk in iter(lambda: file.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=1, allow_nan=False, default=str) + '\n')
    temporary.replace(path)


def order(arms):
    # A/B remains ABBA with two arms; three arms use the symmetric extension,
    # equal replication and equal mean temporal position for every arm.
    return 'ABCCBA' if 'C' in arms else 'ABBA'


def summary(tool, records, expected, smoke=False, error=None):
    valid = len(records) == expected and expected > 0 and all(r.get('valid') for r in records) and not error
    count = sum(bool(r.get('valid')) for r in records)
    return (f'{tool}: status={"VALID" if valid else "INVALID"} kind={"SMOKE_ONLY" if smoke else "MERIT"}'
            f' valid={count}/{expected} runs={len(records)} DQ=0 DF=0'), valid


def campaign(args, tool, cells, runner, calibrate=None):
    records, expected, error, arms, hashes = [], 0, None, {}, {}
    owns_output = False
    try:
        arms = configure(args)
        owns_output = True
        hashes = {arm: sha256(binary) for arm, binary in arms.items()}
        expected = len(cells) * args.blocks * len(order(arms))
        save(args.output / 'manifest.json', dict(args=vars(args), arms=arms, sha256=hashes,
             order=order(arms), cells=cells, expected_runs=expected,
             quantiles='nearest-rank; load-client histograms round up by <1000 ns', clock='CLOCK_MONOTONIC', tool_sha256={
                 p.name: sha256(p) for p in Path(__file__).parent.glob('*.py')}))
        calibration = calibrate(args, arms, cells) if calibrate else None
        for block in range(1, args.blocks + 1):
            for cell in cells:
                for seq, arm in enumerate(order(arms), 1):
                    folder = args.output / cell['name'] / f'b{block}-{seq}-{arm}'
                    folder.mkdir(parents=True)
                    record = dict(cell=cell, block=block, seq=seq, arm=arm, valid=False, folder=str(folder))
                    try:
                        record.update(runner(args, cell, arms[arm], folder, calibration))
                        require(record.get('valid'), 'invalid run')
                    except Exception as exc:
                        record['error'] = f'{type(exc).__name__}: {exc}'
                        raise
                    finally:
                        records.append(record)
                        save(folder / 'record.json', record)
                        save(args.output / 'records.json', records)
                        print(f'{tool}: {cell["name"]} b{block} {seq}:{arm} valid={record["valid"]}', flush=True)
        require(hashes == {arm: sha256(binary) for arm, binary in arms.items()}, 'binary changed during campaign')
        aggregate(args.output, tool, records)
    except (Exception, KeyboardInterrupt) as exc:
        error = f'{type(exc).__name__}: {exc}'
        print(error, file=sys.stderr, flush=True)
    line, valid = summary(tool, records, expected, args.smoke, error)
    if owns_output:
        save(args.output / 'verdict.json', dict(valid=valid, error=error, summary=line))
        (args.output / 'summary.txt').write_text(line + '\n')
    print(line, flush=True)
    return 0 if valid else 1


def argv(args, cell, binary, folder):
    command = ['taskset', '-c', args.server_cores, binary, '--port', str(args.port),
               '--bind', '127.0.0.1', '--save', '', '--appendonly', 'no', '--dir', str(folder),
               '--enable-debug-command', 'yes', '--shards', '16', '--thread-mode', cell['mode'],
               '--read-local', str(cell['read_local']), '--atomic', str(cell['atomic']),
               '--databases', str(cell['databases']), '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
    if cell['mode'] == '2s':
        command += ['--ratio', args.ratio]
    return command


def free_port(port):
    with socket.socket() as probe:
        # No SO_REUSEPORT: an existing listener must refuse the entire run.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', port))


@contextlib.contextmanager
def server(args, cell, binary, folder):
    free_port(args.port)
    command = argv(args, cell, binary, folder)
    save(folder / 'server-argv.json', command)
    conn, process = None, None
    with open(folder / 'server.log', 'wb') as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       cwd=folder, env=dict(os.environ, LC_ALL='C'), start_new_session=True)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                require(process.poll() is None, f'server exited: {process.returncode}; see {folder}/server.log')
                try:
                    conn = Resp(args.port, min(1, args.timeout))
                    require(conn.cmd('PING') == b'PONG', 'bad PING')
                    break
                except (ConnectionError, OSError):
                    if conn:
                        conn.close()
                        conn = None
                    time.sleep(.05)
            require(conn is not None, 'server boot timed out')
            conn.sock.settimeout(args.timeout)
            # PING and INFO must belong to the PID we launched, never a racing listener.
            boot = info(conn)
            require(int(boot['process_id']) == process.pid, 'listener is not the owned process')
            require(boot.get('thread_mode') == cell['mode'] and int(boot['shards']) == 16 and
                    int(boot['read_local']) == cell['read_local'] and int(boot['atomic']) == cell['atomic'],
                    'boot configuration mismatch')
            require(conn.cmd('CONFIG', 'GET', 'databases') == [b'databases', str(cell['databases']).encode()],
                    'database image mismatch')
            save(folder / 'boot-info.json', boot)
            yield process, conn
            require(process.poll() is None, 'server exited during run')
        finally:
            if conn:
                conn.close()
            if process and process.poll() is None:
                # Only our child is signalled; no port-based shutdown/kill.
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            if process:
                save(folder / 'server-exit.json', dict(returncode=process.returncode))
                require(process.returncode == 0, f'server teardown failed: {process.returncode}')


def rss(pid):
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1]) * 1024
    raise Invalid('missing VmRSS')


def routes(conn, keys):
    rows = conn.cmd('DEBUG', 'SHARDS', *keys)
    require(isinstance(rows, list) and len(rows) == len(keys) and
            all(isinstance(row, list) and len(row) == 2 and isinstance(row[0], int) and
                0 <= row[0] < 16 and isinstance(row[1], int) for row in rows), 'invalid DEBUG SHARDS')
    return rows


def pick_keys(conn, per_shard=1):
    selected = [[] for _ in range(16)]
    for offset in range(0, 65536, 512):
        keys = [f'fm{i:014d}'.encode() for i in range(offset, offset + 512)]
        for key, (sid, _) in zip(keys, routes(conn, keys)):
            if len(selected[sid]) < per_shard:
                selected[sid].append(key)
        if all(len(row) == per_shard for row in selected):
            result = [key for row in selected for key in row]
            return result, routes(conn, result)
    raise Invalid('could not find keys on all 16 shards')


def check_size(conn, expected):
    actual = conn.cmd('DBSIZE')
    require(type(actual) is int and actual == expected, f'DBSIZE {actual!r} != {expected}')
    return actual


def check_keyspace(conn, expected):
    fields = parse_info(conn.cmd('INFO', 'keyspace'))
    seen = 0
    for key, value in fields.items():
        if key.startswith('db') and key[2:].isdigit():
            parts = dict(pair.split('=', 1) for pair in value.split(','))
            require(int(parts['expires']) == 0, 'TTL unexpectedly present')
            require(key == 'db0' or int(parts['keys']) == 0, 'unexpected nonzero database')
            seen += int(parts['keys'])
    require(seen == expected, f'INFO keyspace keys {seen} != {expected}')


class Seed:
    """Build a bounded-memory RESP spool once per boot; exact shard quotas.

    TomoKV has no DEBUG POPULATE. DEBUG SHARDS chooses exactly N/16 keys per
    shard; batched MSET/pipelining replays the spool on every reseed. No Python
    list of ten million strings is retained and no routes are guessed from hash.
    """
    def __init__(self, conn, count, folder):
        self.path = folder / 'seed.resp'
        self.count = count
        self.batches = 0
        self.quotas = [count // 16 + (sid < count % 16) for sid in range(16)]
        self.counts = [0] * 16
        self.samples = {}
        self.value = b'v' * 64
        offset, accepted = 0, []
        with open(self.path, 'wb') as file:
            while sum(self.counts) < count:
                keys = [f'fs{i:014d}'.encode() for i in range(offset, offset + 2048)]
                offset += len(keys)
                for key, (sid, _) in zip(keys, routes(conn, keys)):
                    if self.counts[sid] < self.quotas[sid]:
                        self.counts[sid] += 1
                        self.samples[sid] = key
                        accepted.append(key)
                        if len(accepted) == 256:
                            self._write(file, accepted)
                            accepted.clear()
                require(offset <= max(65536, count * 4), 'shard quota search exhausted')
            if accepted:
                self._write(file, accepted)
        require(self.counts == self.quotas, 'nonuniform seed')
        save(folder / 'seed.json', dict(count=count, counts=self.counts, batches=self.batches,
             key_bytes=16, value_bytes=64, expires=0, spool_sha256=sha256(self.path),
             sample_keys={sid: key.decode() for sid, key in self.samples.items()}))

    def _write(self, file, keys):
        payload = encode('MSET', *(part for key in keys for part in (key, self.value)))
        file.write(len(payload).to_bytes(4, 'little') + payload)
        self.batches += 1

    def replay(self, conn):
        check_size(conn, 0)
        with open(self.path, 'rb') as file:
            pending = []
            while True:
                length = file.read(4)
                if not length:
                    break
                require(len(length) == 4, 'short seed spool length')
                n = int.from_bytes(length, 'little')
                payload = file.read(n)
                require(len(payload) == n, 'short seed spool')
                pending.append(payload)
                if len(pending) == 16:
                    self._send(conn, pending)
                    pending.clear()
            if pending:
                self._send(conn, pending)
        check_size(conn, self.count)
        check_keyspace(conn, self.count)
        if self.samples:
            values = conn.cmd('MGET', *self.samples.values())
            require(values == [self.value] * len(self.samples), 'seed sample value mismatch')
        return self.count

    @staticmethod
    def _send(conn, pending):
        conn.sock.sendall(b''.join(pending))
        for _ in pending:
            ok(conn.read())

    def close(self):
        self.path.unlink(missing_ok=True)


def sleep_until(when):
    remaining = when - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def worker_entry(index, port, cpu, timeout, ready, start, epoch, stop, folder, function):
    conn = None
    try:
        os.sched_setaffinity(0, {cpu})
        conn = Resp(port, timeout)
        ok(conn.cmd('SELECT', 0))
        ready.send((index, None))
        require(start.wait(timeout), 'start barrier timed out')
        result = function(conn, index, epoch.value, stop)
        result.update(worker=index, cpu=cpu, valid=True)
    except BaseException as exc:
        result = dict(worker=index, cpu=cpu, valid=False, error=f'{type(exc).__name__}: {exc}')
        stop.set()
        try:
            ready.send((index, result['error']))
        except OSError:
            pass
    finally:
        if conn:
            conn.close()
    # Streaming clients retain lossless counts in 1-us upper-edge buckets.
    # This bounds disk growth independently of the number of completed writes;
    # the worst quantile rounding error is <1 us. FLUSH observations stay raw.
    for key in ('rtt_ns', 'lag_ns', 'response_ns'):
        if key in result:
            result[key + '_hist'] = histogram(result.pop(key))
    save(folder / f'worker-{index}.json', result)


def load_window(args, process, conn, folder, count, function, sample=False, profile=False):
    ctx = mp.get_context('fork')
    start, stop, epoch = ctx.Event(), ctx.Event(), ctx.Value('d', 0)
    load = cpus(args.load_cores)
    children, readers, samples = [], [], []
    prof = None
    try:
        for index in range(count):
            reader, sender = ctx.Pipe(duplex=False)
            child = ctx.Process(target=worker_entry, args=(index, args.port, load[index % len(load)],
                args.timeout, sender, start, epoch, stop, folder, function))
            child.start()
            sender.close()
            readers.append(reader)
            children.append(child)
        for reader in readers:
            require(reader.poll(args.timeout), 'worker never connected')
            _, error = reader.recv()
            require(error is None, f'worker setup failed: {error}')
        before = info(conn)
        if profile:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
            from abba_profile import WindowProfile
            prof = WindowProfile(folder)
            prof.begin(process, [])
        epoch.value = time.monotonic() + .05
        start.set()
        end = epoch.value + args.secs
        while time.monotonic() < end and not stop.is_set():
            if sample:
                observed = info(conn)
                samples.append(dict(t=time.monotonic() - epoch.value,
                                    atomic_entries=int(observed['atomic_entries']),
                                    atomic_pending_entries=int(observed.get('atomic_pending_entries', 0))))
            time.sleep(.01 if sample else .02)
        deadline = end + args.timeout
        for child in children:
            child.join(max(.01, deadline - time.monotonic()))
            require(not child.is_alive() and child.exitcode == 0, 'worker did not drain cleanly')
        finished = time.monotonic()
        rows = [json.loads((folder / f'worker-{index}.json').read_text()) for index in range(count)]
        require(all(row.get('valid') for row in rows), f'worker failure: {[r for r in rows if not r.get("valid")]}')
        after = info(conn)
        delta = deltas(before, after)
        if prof:
            commands = sum(row.get('commands', 0) for row in rows)
            prof.finish(epoch.value, finished, commands)
        result = dict(workers=rows, info_before=before, info_after=after, info_delta=delta,
                      samples=samples, start_monotonic=epoch.value, end_monotonic=finished,
                      offered_seconds=args.secs, drain_seconds=max(0, finished - end))
        # Client histograms live once in worker-N.json; the window keeps
        # small summaries rather than duplicating every histogram.
        compact = dict(result, workers=[{key: value for key, value in row.items()
                       if key not in ('rtt_ns_hist', 'lag_ns_hist', 'response_ns_hist')} for row in rows])
        save(folder / 'window.json', compact)
        return result
    finally:
        stop.set()
        start.set()
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(timeout=5)
            if child.is_alive():
                child.kill()
                child.join(timeout=5)
        for reader in readers:
            reader.close()
        if prof:
            prof.close()


def offered_valid(rows, seconds, max_lag_ms, min_fraction=.99):
    for row in rows:
        require(row['completed'] == row['scheduled'] and row['completed'] > 0, 'missed offered operations')
        require(row['within_window'] >= min_fraction * row['scheduled'], 'offered load not sustainable')
        require(row_distribution(row, 'lag_ns')['p99'] <= max_lag_ms * 1e6, 'generator schedule lag too high')
        require(row['elapsed'] <= seconds + max(1, seconds * .05), 'excessive drain')


def calibrated_floor(runs, fraction):
    require(0 < fraction < 1 and runs, 'invalid calibration fraction')
    slowest = min(runs)
    require(math.isfinite(slowest) and slowest > 0, 'empty calibration capacity')
    return slowest * fraction


def base_selftest():
    import io
    import tempfile
    from unittest.mock import Mock
    assert distribution(list(range(1, 1001))) == dict(p50=500, p95=950, p99=990,
        **{'p99.9': 999}, max=1000, n=1000, unit='ns', method='nearest-rank')
    assert order({'A': 0, 'B': 0}) == 'ABBA'
    assert order({'A': 0, 'B': 0, 'C': 0}) == 'ABCCBA'
    c = object.__new__(Resp)
    c.file = io.BytesIO(b'*3\r\n+OK\r\n$3\r\nabc\r\n:7\r\n')
    assert c.read() == [b'OK', b'abc', 7]
    for raw in (b'$3\r\nab', b'-ERR bad\r\n', b'?bad\r\n'):
        c.file = io.BytesIO(raw)
        rejects(lambda: c.read())
    assert deltas({}, {})['atomic_flush_units'] is None
    rejects(lambda: deltas({'atomic_flush_units': '1'}, {}))
    rejects(lambda: deltas({'atomic_flush_units': '1'}, {'atomic_flush_units': '0'}))
    rejects(lambda: deltas({'evicted_keys': '0'}, {'evicted_keys': '1'}))
    for value in (0, None, b'1'):
        c = Mock()
        c.cmd.return_value = value
        rejects(lambda: check_size(c, 1))
    c.cmd.return_value = 1
    assert check_size(c, 1) == 1
    c.cmd.return_value = b'# Keyspace\r\ndb0:keys=1,expires=1,avg_ttl=5\r\n'
    rejects(lambda: check_keyspace(c, 1))
    assert calibrated_floor([100, 50, 75], .5) == 25
    assert summary('test', [{'valid': True}] * 4, 4)[1]
    assert not summary('test', [{'valid': True}] * 3, 4)[1]
    assert not summary('test', [{'valid': False}] * 4, 4)[1]
    rejects(lambda: distribution([]))
    assert hist_distribution(histogram([0, 1, 999, 1000, 1001]))['max'] == 2000
    hist = hist_distribution(histogram(list(range(1, 1001))))
    assert hist['n'] == 1000 and hist['p50'] == 1000 and hist['quantum_ns'] == 1000
    rejects(lambda: hist_distribution({}))
    rejects(lambda: hist_distribution({'-1000': 1}))
    rejects(lambda: hist_distribution({'1000': 0}))
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        seed_conn = Mock()
        seed_conn.cmd.side_effect = lambda *args: [[i % 16, i % 2] for i in range(len(args) - 2)]
        seed = Seed(seed_conn, 16, folder)
        assert seed.counts == [1] * 16 and seed.batches == 1
        seed_conn.cmd.side_effect = [0, 16, b'db0:keys=16,expires=0\r\n', [b'v' * 64] * 16]
        seed_conn.read.return_value = b'OK'
        seed.replay(seed_conn)
        packet = seed_conn.sock.sendall.call_args[0][0]
        parser = object.__new__(Resp)
        parser.file = io.BytesIO(packet)
        parsed = parser.read()
        assert parsed[0] == b'MSET' and len(parsed) == 33
        assert len(set(parsed[1::2])) == 16 and all(len(key) == 16 for key in parsed[1::2])
        assert parsed[2::2] == [b'v' * 64] * 16
        seed_conn.cmd.side_effect = [0]
        seed_conn.read.return_value = b'BAD'
        rejects(lambda: seed.replay(seed_conn))
        seed.close()
        assert not seed.path.exists()


def rejects(function):
    try:
        function()
    except (Invalid, ValueError):
        return
    raise AssertionError('negative control incorrectly passed')


def calibration(args, arms, cells, runner, rate_names):
    """Measure achieved client capacities, choose one conservative load for all cells,
    then demonstrate sustainability on every arm/cell before freezing that load.
    Capacity is generator+server achieved capacity, not a server saturation claim.
    """
    import copy
    probe = copy.copy(args)
    probe.secs = args.calibration_secs
    probe.profile = False
    result = dict(capacity=[], validation=[], offered={}, fraction=args.load_fraction,
                  seconds=probe.secs, scope='minimum achieved client rate across every arm/cell')
    root = args.output / 'calibration'
    root.mkdir()
    fm_path = root / 'calibration.json'
    for cell in cells:
        for arm, binary in arms.items():
            folder = root / 'capacity' / cell['name'] / arm
            folder.mkdir(parents=True)
            record = runner(probe, cell, binary, folder, None)
            result['capacity'].append(dict(cell=cell, arm=arm, result=record))
            save(fm_path, result)
    result['offered'] = {key: calibrated_floor(
        [r['result']['rates'][key] for r in result['capacity']], args.load_fraction) for key in rate_names}
    save(fm_path, result)
    for cell in cells:
        for arm, binary in arms.items():
            folder = root / 'validation' / cell['name'] / arm
            folder.mkdir(parents=True)
            record = runner(probe, cell, binary, folder, result['offered'])
            result['validation'].append(dict(cell=cell, arm=arm, result=record))
            save(fm_path, result)
    result['valid'] = True
    save(fm_path, result)
    print('calibration: sustainable fixed offered load validated on every selected cell/arm', flush=True)
    return result['offered']


def pacing_options(parser):
    parser.add_argument('--secs', type=float, default=30)
    parser.add_argument('--calibration-secs', type=float, default=3)
    parser.add_argument('--load-fraction', type=float, default=.5)
    parser.add_argument('--max-lag-ms', type=float, default=20,
                        help='reject a paced client if p99 scheduled-send lag exceeds this bound')


def check_pacing(args):
    require(args.secs > 0 and args.calibration_secs > 0 and 0 < args.load_fraction < 1 and args.max_lag_ms > 0,
            'invalid pacing settings')
    require(args.smoke or args.secs >= 10, 'merit windows must be at least ten seconds')


def aggregate(output, tool, records):
    """Pool exact latency observations by cell/arm; rates retain per-visit medians.
    Per-block/visit records remain available for paired comparisons. No rates
    are printed for smoke runs; their artifacts are explicitly SMOKE_ONLY.
    """
    groups = {}
    for record in records:
        groups.setdefault((record['cell']['name'], record['arm']), []).append(record)
    result = []
    for (cell, arm), rows in groups.items():
        row = dict(cell=cell, arm=arm, runs=len(rows))
        if tool == 'flush_latency':
            observations = [item for r in rows for item in json.loads(Path(r['observations_file']).read_text())]
            row['latency'] = distribution([item['latency_ns'] for item in observations])
            row['rss'] = {key: dict(min=min(r[key] for r in observations),
                                   median=statistics.median(r[key] for r in observations),
                                   max=max(r[key] for r in observations)) for key in
                          ('rss_before_seed_bytes', 'rss_after_seed_bytes', 'rss_after_flush_bytes', 'rss_reclaimed_bytes')}
        elif tool == 'flush_writer_wait':
            raw = {key: Counter() for key in ('rtt_ns', 'lag_ns', 'response_ns')}
            for r in rows:
                for index in range(16):
                    worker = json.loads((Path(r['folder']) / f'worker-{index}.json').read_text())
                    for key in raw:
                        raw[key].update(worker[key + '_hist'])
            row.update({key: hist_distribution(values) for key, values in raw.items()})
            row['latency_label'] = rows[0]['latency_label']
            row['claim_wait_duration_histogram'] = None
        if 'rates' in rows[0]:
            row['rates'] = {key: dict(median=statistics.median(r['rates'][key] for r in rows),
                                     min=min(r['rates'][key] for r in rows), max=max(r['rates'][key] for r in rows))
                            for key in rows[0]['rates']}
        counter_rows = [r.get('counters', r.get('info_delta', {})) for r in rows]
        row['info_delta_sum'] = {key: None if any(r.get(key) is None for r in counter_rows) else
                                sum(r[key] for r in counter_rows) for key in COUNTERS}
        result.append(row)
    save(output / 'summary.json', result)
    return result


def histogram(values):
    require(all(type(x) is int and x >= 0 for x in values), 'invalid histogram observation')
    return dict(Counter(str(((x + 999) // 1000) * 1000) for x in values))


def hist_distribution(counts):
    require(counts and all(type(v) is int and v > 0 for v in counts.values()), 'invalid/empty histogram')
    entries = sorted((int(key), count) for key, count in counts.items())
    require(entries[0][0] >= 0 and all(key % 1000 == 0 for key, _ in entries), 'bad histogram bucket')
    total = sum(counts.values())
    answer = dict(n=total, max=entries[-1][0], unit='ns', method='nearest-rank-upper-bucket', quantum_ns=1000)
    for name, q in (('p50', .5), ('p95', .95), ('p99', .99), ('p99.9', .999)):
        rank, cumulative = math.ceil(q * total), 0
        for value, count in entries:
            cumulative += count
            if cumulative >= rank:
                answer[name] = value
                break
    return answer


def row_distribution(row, key):
    return distribution(row[key]) if key in row else hist_distribution(row[key + '_hist'])


def pool_distribution(rows, key):
    pooled = Counter()
    for row in rows:
        pooled.update(row[key + '_hist'])
    return hist_distribution(pooled)
