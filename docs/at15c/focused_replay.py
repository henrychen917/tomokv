#!/usr/bin/env python3
"""Own two isolated listeners and run unchanged edgetime, optionally timestamped.

No benchmark. Geometry and flags match docs/at15b/replay.sh. Refuse occupied
ports, terminate only owned children, preserve every harness return code.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument('binary')
p.add_argument('output')
p.add_argument('--geometry', choices=['armed-fused', 'split'], default='armed-fused')
p.add_argument('--runs', type=int, default=3)
p.add_argument('--trace', action='store_true')
p.add_argument('--perf', action='store_true')
p.add_argument('--directed', action='store_true')
args = p.parse_args()
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=False)
for port in (17899, 17900):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', port))
children, files, results = [], [], []


def affinity(pid):
    return {task.name: sorted(os.sched_getaffinity(int(task.name)))
            for task in Path(f'/proc/{pid}/task').iterdir()}


def boot(label, command, port):
    log = (out / (label + '.log')).open('w')
    files.append(log)
    proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    children.append(proc)
    until = time.monotonic() + 15
    while time.monotonic() < until:
        if proc.poll() is not None:
            raise RuntimeError(f'{label} exited {proc.returncode}')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                return proc
        except OSError:
            time.sleep(.05)
    raise RuntimeError(f'{label} did not listen')


def run(label, command):
    with (out / (label + '.log')).open('w') as log:
        start = time.time_ns()
        result = subprocess.run(['taskset', '-c', '121-127', *command],
                                stdout=log, stderr=subprocess.STDOUT, timeout=180)
    results.append(dict(label=label, command=command, rc=result.returncode,
                        start_ns=start, end_ns=time.time_ns(),
                        target_affinity=affinity(target.pid),
                        oracle_affinity=affinity(oracle.pid)))
    print(label, result.returncode, flush=True)


try:
    (out / 'oracle').mkdir()
    (out / 'target').mkdir()
    oracle = boot('oracle', ['taskset', '-c', '120', 'env', 'LC_ALL=C',
                  '/home/user/Projects/redis/src/redis-server', '--port', '17900',
                  '--bind', '127.0.0.1', '--dir', str(out / 'oracle'),
                  '--dbfilename', 'dump.rdb', '--appendonly', 'no', '--save', '',
                  '--enable-debug-command', 'yes'], 17900)
    shape = ['--thread-mode', 'fused', '--read-local', '1'] if args.geometry == 'armed-fused' \
        else ['--ratio', '6:2']
    target = boot('target', ['taskset', '-c', '112-119', str(Path(args.binary).resolve()),
                  '--port', '17899', '--bind', '127.0.0.1', '--shards', '16', *shape,
                  '--databases', '16', '--atomic', '0', '--save', '',
                  '--dir', str(out / 'target'), '--enable-debug-command', 'yes'], 17899)
    (out / 'pids.json').write_text(json.dumps(dict(target=target.pid, oracle=oracle.pid)))
    perf = None
    if args.perf:
        log = (out / 'perf.log').open('w')
        files.append(log)
        perf = subprocess.Popen(['taskset', '-c', '127', 'perf', 'record', '-C', '112-119',
                    '-g', '--call-graph', 'dwarf,8192', '--switch-events', '-e', 'cycles:u',
                    '-F', '999', '-o', str(out / 'perf.data')],
                    stdout=log, stderr=subprocess.STDOUT)
        children.append(perf)
        time.sleep(.2)
        if perf.poll() is not None:
            raise RuntimeError('perf failed to start')
    for index in range(args.runs):
        label = f'edgetime-{index + 1}'
        command = ['python3', 'docs/at15c/trace_differ.py', str(out / label)] if args.trace \
            else ['python3', 'tests/differ.py']
        run(label, [*command, '127.0.0.1', '17899', '127.0.0.1', '17900', 'edgetime', '7'])
    if perf:
        perf.send_signal(signal.SIGINT)
        perf.wait(timeout=15)
        children.remove(perf)
    if args.directed:
        for suite in ('multi', 'multidb'):
            for seed in (7, 19, 20):
                run(f'{suite}-{seed}', ['python3', 'tests/differ.py',
                    '127.0.0.1', '17899', '127.0.0.1', '17900', suite, str(seed)])
        run('debug', ['python3', 'tests/debug.py', '127.0.0.1', '17899'])
finally:
    for proc in reversed(children):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    for file in files:
        file.close()
    (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
