#!/usr/bin/env python3
"""NT4.2 incidence probe: the round-4 audit's nt4_probe.py cells, re-pinned.

Same boot argv as lane perfio's boot() (paper rl=0, uring, 16 shards, atomic 1,
key-lb/client-lb on), same memtier argv and the same directed-split observer
control; only CPUs (server 64-71, memtier 73-79), the port and the cell list are
local. Run against an observer build (tools/respresume_observer.py). Reports both
witnesses per completed command:
  perfio_reparsed_arguments  completed argv discarded at Incomplete (audit metric)
  rr_decoded - rr_completed  length lines decoded more than once (independent)
Never compare rates from this build or from shared cores.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from _lib import encode, info, wait_ready  # noqa: E402

CELLS = (('SET', 1024, 32, 512), ('MSET', 64, 8, 512))


def counters(c, command):
    fields = info(c, 'stats')
    cs = info(c, 'commandstats')['cmdstat_' + command.lower()]
    calls = int(dict(item.split('=', 1) for item in cs.split(','))['calls'])
    return dict(incomplete=int(fields['perfio_incomplete']),
                reparsed=int(fields['perfio_reparsed_arguments']),
                decoded=int(fields['rr_decoded_lines']),
                completed=int(fields['rr_completed_lines']), calls=calls)


def delta(after, before):
    return {k: after[k] - before[k] for k in after}


def boot_argv(args, mode, directory):
    # perfio.boot(opts, name, extra) with oracle=False, ratio 6:2, net_io uring, read_local 0.
    argv = ['taskset', '-c', args.server_cpus, str(args.binary.resolve()),
            '--bind', '127.0.0.1', '--port', str(args.port), '--dir', str(directory),
            '--save', '', '--appendonly', 'no', '--enable-debug-command', 'yes',
            '--thread-mode', mode, '--shards', '16', '--net-io', 'uring', '--flip-auto', '0',
            '--key-lb', '0', '--client-lb', '0', '--enable-debug-command', 'yes',
            '--atomic', '1', '--key-lb', '1', '--client-lb', '1']
    argv += ['--read-local', '0'] if mode == '1s' else ['--ratio', '6:2']
    return argv


def run_cell(args, mode, command, size, depth, conns, results):
    name = f'{mode}-{command}-{size}-p{depth}-c{conns}'
    directory = args.output.resolve() / name
    directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', args.port)) != 0, 'owned port already busy'
    argv = boot_argv(args, mode, directory)
    with (directory / 'server.log').open('w') as log:
        p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    c = None
    try:
        c = wait_ready('127.0.0.1', args.port, timeout=15, process=p, log_path=directory / 'server.log')
        if command == 'MSET':
            assert c.must('MSET', 'memtier-1', 'v') == b'OK'
            # Directed split: the observer must see the claimed path in this binary.
            armed = counters(c, command)
            frame = encode('MSET', *[x for i in range(8) for x in (f'arm-{i}', 'v')])
            c.raw(frame[:-9])
            time.sleep(.02)
            c.raw(frame[-9:])
            assert c.read() == b'OK'
            fired = delta(counters(c, command), armed)
            assert fired['incomplete'] >= 1, fired
            control = dict(event='observer_control', mode=mode, **fired,
                           replayed_lines=fired['decoded'] - fired['completed'])
            print(json.dumps(control), flush=True)
            results.append(control)
        else:
            assert c.must('SET', 'memtier-1', 'v') == b'OK'
        before = counters(c, command)
        threads = 4
        clients = conns // threads
        requests = (1_000_000 + conns - 1) // conns
        load = ['taskset', '-c', args.load_cpus, 'memtier_benchmark', '-s', '127.0.0.1',
                '-p', str(args.port), '--protocol=redis', '-t', str(threads), '-c', str(clients),
                '--key-minimum=1', '--key-maximum=2000000', f'--data-size={size}',
                f'--pipeline={depth}', f'--requests={requests}', '--distinct-client-seed',
                '--hide-histogram', f'--json-out-file={directory / "memtier.json"}']
        if command == 'MSET':
            load += ['--command=MSET ' + ' '.join(['__key__ __data__'] * 8), '--command-key-pattern=P']
        else:
            load += ['--ratio=1:0', '--key-pattern=P:P']
        with (directory / 'load.log').open('w') as log:
            subprocess.run(load, stdout=log, stderr=subprocess.STDOUT, timeout=300, check=True)
        d = delta(counters(c, command), before)
        assert d['calls'] >= 1_000_000, d
        row = dict(event='cell', name=name, argv=argv, load=load, commands=d['calls'],
                   incomplete=d['incomplete'], reparsed_arguments=d['reparsed'],
                   decoded_lines=d['decoded'], completed_lines=d['completed'],
                   replayed_lines=d['decoded'] - d['completed'],
                   reparsed_per_command=d['reparsed'] / d['calls'],
                   incomplete_per_million=d['incomplete'] * 1e6 / d['calls'],
                   replayed_lines_per_command=(d['decoded'] - d['completed']) / d['calls'])
        print(json.dumps(row), flush=True)
        results.append(row)
    finally:
        if c:
            c.close()
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
    assert p.returncode == 0, (p.returncode, (directory / 'server.log').read_text()[-2000:])
    deadline = time.monotonic() + 5
    while True:
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', args.port)) != 0:
                break
        assert time.monotonic() < deadline, 'owned listener did not retire after child exit'
        time.sleep(.01)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--binary', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--port', type=int, default=25410)
    ap.add_argument('--server-cpus', default='64-71')
    ap.add_argument('--load-cpus', default='73-79')
    args = ap.parse_args()
    assert 25400 <= args.port <= 25449
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for mode in ('1s', '2s'):
        for command, size, depth, conns in CELLS:
            run_cell(args, mode, command, size, depth, conns, results)
            (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    (args.output / 'binary.sha256').write_text(
        hashlib.sha256(args.binary.read_bytes()).hexdigest() + '  ' + str(args.binary) + '\n')


if __name__ == '__main__':
    main()
