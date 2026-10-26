#!/usr/bin/env python3
"""AT4-WOUND-1 correctness only: oversubscribe this lane's CPUs, measure no rates."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import _lib


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()


def counters(port):
    conn = _lib.Conn('127.0.0.1', port, timeout=30)
    try:
        raw = conn.must('INFO', 'stats').decode()
    finally:
        conn.close()
    return {k: int(v) for k, v in (line.split(':', 1) for line in raw.splitlines() if ':' in line)
            if k.startswith(('atomic_txn_', 'atomic_group_')) and v.lstrip('-').isdigit()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/woundfix/live')
    parser.add_argument('--rounds', type=int, default=8192)
    parser.add_argument('--repeats', type=int, default=20)
    parser.add_argument('--min-wounds', type=int, default=300000)
    args = parser.parse_args()
    assert args.repeats >= 20 and args.rounds > 0 and args.min_wounds >= 300000
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    injector = ROOT / 'build/woundfix/preempt'
    subprocess.run(['gcc', '-O2', '-o', str(injector), str(ROOT / 'docs/execindex/nx-preempt/preempt.c')], check=True)
    rows = []; total_wounds = 0
    cells = list(itertools.product(('1s', '2s'), (1, 16), ('uring', 'epoll')))
    for index, (mode, databases, engine) in enumerate(cells):
        port = 20381 + index * 2
        label = f'{mode}-db{databases}-{engine}'
        directory = out / label; directory.mkdir(exist_ok=True)
        data = ROOT / 'build/woundfix/live-data' / label; data.mkdir(parents=True, exist_ok=True)
        cmd = ['taskset', '-c', '32-39', str(binary), '--bind', '127.0.0.1', '--port', str(port),
               '--shards', '16', '--thread-mode', mode, '--databases', str(databases),
               '--atomic', '1', '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0',
               '--enable-debug-command', 'yes', '--net-io', engine, '--dir', str(data), '--save', '']
        if mode == '2s': cmd += ['--ratio', '6:2']
        # A listener already occupying our port is never reused or terminated.
        with socket.socket() as check:
            check.bind(('127.0.0.1', port))
        with (directory / 'server.log').open('w') as log:
            server = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            injectors = []
            try:
                for _ in range(150):
                    if server.poll() is not None: raise RuntimeError(f'{label}: boot exited {server.returncode}')
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.2): pass
                        break
                    except OSError: time.sleep(.2)
                else: raise RuntimeError('boot timeout')
                before = counters(port)
                injectors = [subprocess.Popen(['taskset', '-c', str(cpu), str(injector), '20', '30'])
                             for cpu in range(32, 40)]
                repetitions = []
                for rep in range(500):
                    test = ['taskset', '-c', '40-47', 'python3', 'tests/txn_nx.py', '127.0.0.1',
                            str(port), '--rounds', str(args.rounds)]
                    result = subprocess.run(test, cwd=ROOT, text=True, capture_output=True, timeout=600)
                    (directory / f'rep-{rep:03d}.log').write_text(result.stdout + result.stderr)
                    summaries = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
                    assert result.returncode == 0 and len(summaries) == 2, (label, rep, result.stdout, result.stderr)
                    assert all(r['completed'] == args.rounds and not r['failures'] and not r['errors'] and
                               not r['threads_alive'] for r in summaries), (label, rep, summaries)
                    after = counters(port)
                    assert after['atomic_txn_order_violations'] == 0, after
                    repetitions.append(dict(rep=rep, command=test, results=summaries, counters=after))
                    current = after['atomic_group_wounds'] - before['atomic_group_wounds']
                    (directory / 'repetitions.json').write_text(json.dumps(repetitions, indent=2) + '\n')
                    if rep + 1 >= args.repeats and (index != len(cells)-1 or total_wounds+current >= args.min_wounds): break
                else: raise RuntimeError('bounded repetition limit did not attain wound witness')
            finally:
                for proc in injectors: stop(proc)
                stop(server)
            assert server.returncode == 0, (label, server.returncode)
        delta = {k: after[k] - before.get(k, 0) for k in after}
        assert delta['atomic_group_wounds'] > 0 and delta['atomic_txn_wounds'] > 0, delta
        total_wounds += delta['atomic_group_wounds']
        rows.append(dict(cell=label, boot=cmd, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                         repeats=len(repetitions), rounds=args.rounds, counter_delta=delta,
                         failures=0, injector='one spin 20us / sleep 30us process per server CPU 32-39'))
        (out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(label, 'PASS', 'repeats', len(repetitions), 'group wounds', delta['atomic_group_wounds'],
              'EXEC wounds', delta['atomic_txn_wounds'], 'order violations', after['atomic_txn_order_violations'], flush=True)
    assert total_wounds >= args.min_wounds


if __name__ == '__main__': main()
