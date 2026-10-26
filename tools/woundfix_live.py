#!/usr/bin/env python3
"""AT4-WOUND-1 correctness only: oversubscribe this lane's CPUs, measure no rates."""
import argparse
import concurrent.futures
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
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    assert args.repeats >= 20 and args.rounds > 0 and args.min_wounds >= 300000
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    injector = ROOT / 'build/woundfix/preempt'
    subprocess.run(['gcc', '-O2', '-o', str(injector), str(ROOT / 'docs/execindex/nx-preempt/preempt.c')], check=True)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    rows = json.loads((out / 'results.json').read_text()) if args.resume else []
    assert all(r['binary_sha256'] == digest and r['failures'] == 0 for r in rows)
    total_wounds = sum(r['counter_delta']['atomic_group_wounds'] for r in rows)
    cells = list(itertools.product(('1s', '2s'), (1, 16), ('uring', 'epoll')))
    cells.append(('1s', 1, 'uring'))  # the original live symptom's exact posture
    for index, (mode, databases, engine) in enumerate(cells):
        port = 20381 + index * 2
        exposure = index == len(cells)-1
        label = ('exposure-' if exposure else '') + f'{mode}-db{databases}-{engine}'
        if any(r['cell'] == label for r in rows): continue
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
                def repetition(rep):
                    # The first twenty runs each cover EXEC and bare groups.
                    # Supplemental runs accumulate the requested bare-wound
                    # exposure after every geometry has met that repeat floor.
                    bare = exposure or rep >= args.repeats
                    test = ['taskset', '-c', '40-47', 'python3', 'tests/txn_nx.py', '127.0.0.1',
                            str(port), '--rounds', str(args.rounds)] + (['--bare'] if bare else [])
                    result = subprocess.run(test, cwd=ROOT, text=True, capture_output=True, timeout=600)
                    (directory / f'rep-{rep:03d}.log').write_text(result.stdout + result.stderr)
                    summaries = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
                    assert result.returncode == 0 and len(summaries) == (1 if bare else 2), (label, rep, result.stdout, result.stderr)
                    assert all(r['completed'] == args.rounds and not r['failures'] and not r['errors'] and
                               not r['threads_alive'] for r in summaries), (label, rep, summaries)
                    return dict(rep=rep, command=test, results=summaries)
                with concurrent.futures.ThreadPoolExecutor(4) as pool:
                    for first in range(0, 4000, 4):
                        batch = list(pool.map(repetition, range(first, first + 4)))
                        after = counters(port)
                        assert after['atomic_txn_order_violations'] == 0, after
                        repetitions.extend(batch)
                        current = after['atomic_group_wounds'] - before['atomic_group_wounds']
                        (directory / 'repetitions.json').write_text(json.dumps(repetitions, indent=2) + '\n')
                        if (exposure and current >= args.min_wounds) or (not exposure and first + 4 >= args.repeats): break
                        if exposure and (first + 4) % 20 == 0:
                            print(label, 'repeats', first + 4, 'group wounds', current, 'zero wrong replies', flush=True)
                    else: raise RuntimeError('bounded repetition limit did not attain wound witness')
            finally:
                for proc in injectors: stop(proc)
                stop(server)
            assert server.returncode == 0, (label, server.returncode)
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest, 'binary changed during live proof'
        delta = {k: after[k] - before.get(k, 0) for k in after}
        assert delta['atomic_group_wounds'] > 0 and (exposure or delta['atomic_txn_wounds'] > 0), delta
        total_wounds += delta['atomic_group_wounds']
        rows.append(dict(cell=label, boot=cmd, binary_sha256=digest,
                         repeats=len(repetitions), full_repeats=0 if exposure else min(args.repeats, len(repetitions)),
                         supplemental_bare=len(repetitions) if exposure else max(0, len(repetitions)-args.repeats), rounds=args.rounds, counter_delta=delta,
                         failures=0, clients='four independent txn_nx processes, each with disjoint fresh keys',
                         injector='one spin 20us / sleep 30us process per server CPU 32-39'))
        (out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(label, 'PASS', 'repeats', len(repetitions), 'group wounds', delta['atomic_group_wounds'],
              'EXEC wounds', delta['atomic_txn_wounds'], 'order violations', after['atomic_txn_order_violations'], flush=True)
    assert total_wounds >= args.min_wounds


if __name__ == '__main__': main()
