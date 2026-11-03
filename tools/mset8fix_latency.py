#!/usr/bin/env python3
"""mset8fix: the survey's hot-key MSET8 latency cell against one TomoKV binary. Correctness only.

Reproduces strings-MSET8-n100-p32 (bench-merit/SURVEY-W15-CMDS-STRINGS-11032337): the survey's
server argv (2s, --ratio 24:8, 256 shards, atomic 1, LB and FLIP off, one database), its seed
script and its MSET8 script (docs/mset8fix/latency/), run by calib/survey-client.cc with 64
connections on 64 pinned workers, pipeline 32, 64 keys, 4 s. Each connection rewrites its own
eight keys, batch-synchronously. Reports the latency distribution of every request, the
per-connection completion spread and the window refusals; it asserts nothing about rates.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from _lib import info, wait_ready  # noqa: E402
from _gate_process import stop_process  # noqa: E402

DOC = ROOT / 'docs/mset8fix/latency'


def cpus(spec):
    out = []
    for item in spec.split(','):
        lo, _, hi = item.partition('-')
        out += list(range(int(lo), int(hi or lo) + 1))
    return out


def client(a, folder, script, connections, pipeline, seconds, count=None):
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('ready', 'go'):
        (folder / name).unlink(missing_ok=True)
    argv = ['taskset', '-c', a.load_cpus, str(a.client), '--port', str(a.port), '--script', str(script),
            '--out', str(folder / 'client.json'), '--connections', str(connections),
            '--threads', str(connections), '--pipeline', str(pipeline), '--keys', '64',
            '--seconds', str(seconds), '--timeout', '120', '--cpus', ','.join(map(str, cpus(a.load_cpus))),
            '--ready', str(folder / 'ready'), '--go', str(folder / 'go')]
    if count:
        argv += ['--count', str(count)]
    (folder / 'client-argv.json').write_text(json.dumps(argv, indent=2) + '\n')
    with (folder / 'client.log').open('w') as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, LC_ALL='C'))
        deadline = time.monotonic() + 60
        while not (folder / 'ready').exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f'client did not arm: {(folder / "client.log").read_text()[-2000:]}')
            time.sleep(.01)
        (folder / 'go').write_text('')
        rc = proc.wait(timeout=seconds + 180)
    if rc:
        raise RuntimeError(f'client rc={rc}: {(folder / "client.log").read_text()[-2000:]}')
    return json.loads((folder / 'client.json').read_text())


def percentile(bins, total, q):
    target = q * total
    seen = 0
    for edge, n in bins:
        seen += n
        if seen >= target:
            return edge
    return bins[-1][0]


def visit(a, rep):
    folder = a.output / f'rep{rep}'
    folder.mkdir(parents=True, exist_ok=True)
    listening = subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{a.port}'], text=True).strip()
    if listening:
        raise AssertionError(f'port {a.port} is already listening: {listening}')
    argv = ['taskset', '-c', a.server_cpus, str(a.binary.resolve()), '--bind', '127.0.0.1', '--port', str(a.port),
            '--dir', str(folder.resolve()), '--save', '', '--databases', '1', '--maxclients', '20064',
            '--appendonly', 'no', '--appendfsync', 'everysec', '--auto-aof-rewrite-percentage', '0',
            '--thread-mode', '2s', '--read-local', str(a.read_local), '--shards', '256', '--atomic', '1',
            '--key-lb', '0', '--client-lb', '0', '--ratio', a.ratio, '--flip-auto', '0']
    (folder / 'server-argv.json').write_text(json.dumps(argv, indent=2) + '\n')
    log = (folder / 'server.log').open('w')
    process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, LC_ALL='C'))
    admin = None
    try:
        admin = wait_ready('127.0.0.1', a.port, process=process, timeout=60)
        client(a, folder / 'seed', DOC / 'seed-script.resp', 32, 8, 3600, count=64)
        before = info(admin, 'stats')
        load = client(a, folder / 'load', DOC / 'mset8-script.resp', 64, 32, a.seconds)
        after = info(admin, 'stats')
        if not load.get('valid'):
            raise AssertionError('client reported an invalid run')
        merged = {}
        per = []
        for worker in load['workers']:
            for edge, n in worker['rtt']['bins']:
                merged[edge] = merged.get(edge, 0) + n
            slow = sum(n for edge, n in worker['rtt']['bins'] if edge >= 20_000_000)
            per.append(dict(completed=worker['completed'], max_ms=worker['rtt']['max'] / 1e6, ge20ms=slow))
        bins = sorted(merged.items())
        total = sum(n for _, n in bins)
        completions = sorted(p['completed'] for p in per)
        median = statistics.median(completions)
        row = dict(rep=rep, requests=total, seconds=a.seconds,
                   p50_ms=percentile(bins, total, .50) / 1e6, p99_ms=percentile(bins, total, .99) / 1e6,
                   p999_ms=percentile(bins, total, .999) / 1e6,
                   max_ms=max(w['rtt']['max'] for w in load['workers']) / 1e6,
                   requests_ge_20ms=sum(n for edge, n in bins if edge >= 20_000_000),
                   connections_stalled=sum(p['ge20ms'] > 0 for p in per),
                   connections_starved=sum(p['completed'] < .25 * median for p in per),
                   slowest_connection=completions[0], median_connection=median,
                   fastest_connection=completions[-1],
                   slowest_over_median=completions[0] / median if median else 0.0,
                   window_stalls=int(after['atomic_window_stalls']) - int(before['atomic_window_stalls']),
                   per_connection=per)
        (folder / 'summary.json').write_text(json.dumps(row, indent=2) + '\n')
        return row
    finally:
        if admin:
            admin.close()
        forced = stop_process(process)
        log.close()
        if forced or process.returncode != 0:
            raise AssertionError(f'server exit rc={process.returncode} forced={forced}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--client', type=Path, default=ROOT / 'build/mset8fix/survey-client',
                   help='g++ -std=c++20 -O2 -pthread calib/survey-client.cc -o build/mset8fix/survey-client')
    p.add_argument('--server-cpus', required=True)
    p.add_argument('--load-cpus', required=True)
    p.add_argument('--ratio', default='24:8')
    p.add_argument('--read-local', type=int, default=0)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--seconds', type=float, default=4.0)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    rows = [visit(a, rep) for rep in range(a.repeats)]
    keys = ('p50_ms', 'p99_ms', 'p999_ms', 'max_ms', 'requests_ge_20ms', 'connections_stalled',
            'connections_starved', 'slowest_connection', 'median_connection', 'slowest_over_median',
            'window_stalls', 'requests')
    for row in rows:
        print(json.dumps({k: row[k] for k in keys}), flush=True)
    (a.output / 'result.json').write_text(json.dumps(dict(binary=str(a.binary), ratio=a.ratio,
        read_local=a.read_local, server_cpus=a.server_cpus, load_cpus=a.load_cpus,
        visits=[{k: r[k] for k in keys} for r in rows]), indent=2) + '\n')


if __name__ == '__main__':
    main()
