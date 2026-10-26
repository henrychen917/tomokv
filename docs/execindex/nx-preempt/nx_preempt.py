#!/usr/bin/env python3
"""Live AT4-WOUND-1 window check (run from the worktree on CPUs 96-111, ports 46800-46899): tests/txn_nx.py --bare on PRE and POST release boots
(fused, uring, --atomic 1, the debug-0 failure's geometry), while spin/sleep injectors
pinned to the server CPUs make it likely that a wounder is descheduled between its two
CASes. Correctness only: no rate is measured or compared. Blocks alternate PRE/POST/POST/PRE.
"""
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path('/home/user/Projects/cx-execindex')
OUT = ROOT / 'docs/execindex/nx-preempt'
ARMS = {'PRE': ROOT / 'build/execindex/PRE', 'POST': ROOT / 'build/execindex/POST'}
# Build first: gcc -O2 -o build/execindex/preempt docs/execindex/nx-preempt/preempt.c
INJECTOR = ROOT / 'build/execindex/preempt'
CLI = '/home/user/Projects/redis74/src/redis-cli'
BLOCK_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 120
ROUNDS = 8192


def busy_local_ports():
    out = subprocess.run(['taskset', '-c', '104-111', 'ss', '-tanH'], capture_output=True, text=True).stdout
    return {int(m.group(1)) for line in out.splitlines()
            for m in [re.search(r':(\d+)$', line.split()[3] if len(line.split()) > 3 else '')] if m}


def pick_port(avoid):
    busy = busy_local_ports()
    for port in range(46897, 46800, -2):  # odd: plain connect() never draws it first
        if port not in busy and port + 1 not in busy and port not in avoid:
            return port
    raise SystemExit('no free port')


def info(port):
    out = subprocess.run(['taskset', '-c', '104-111', CLI, '-p', str(port), 'INFO'],
                         capture_output=True, text=True, timeout=30).stdout
    return {k: int(v) for k, v in (line.strip().split(':', 1) for line in out.splitlines() if ':' in line)
            if k.startswith(('atomic_txn_', 'atomic_group_')) and v.strip().lstrip('-').isdigit()}


def boot(binary, port, log):
    data = tempfile.mkdtemp(prefix='nx-preempt-')
    args = ['taskset', '-c', '96-103', str(binary), '--port', str(port), '--bind', '127.0.0.1',
            '--shards', '16', '--dir', data, '--save', '', '--databases', '1', '--thread-mode', 'fused',
            '--atomic', '1', '--enable-debug-command', 'yes', '--key-lb', '0', '--client-lb', '0',
            '--flip-auto', '0', '--net-io', 'uring']
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(150):
        if proc.poll() is not None:
            raise RuntimeError(f'server exited during boot ({proc.returncode})')
        try:
            socket.create_connection(('127.0.0.1', port), timeout=0.5).close()
            return proc, args
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError('server never listened')


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def block(arm, index, used_ports):
    port = pick_port(used_ports)
    used_ports.add(port)
    log = (OUT / f'{index}-{arm}-server.log').open('w')
    proc, args = boot(ARMS[arm], port, log)
    injectors = []
    reps = []
    try:
        before = info(port)
        injectors = [subprocess.Popen(['taskset', '-c', str(cpu), str(INJECTOR), '20', '30'])
                     for cpu in range(96, 104)]
        started = time.time()
        failures = 0
        while time.time() - started < BLOCK_SECONDS and failures < 3:
            result = subprocess.run(['taskset', '-c', '104-111', 'python3', 'tests/txn_nx.py', '127.0.0.1',
                                     str(port), '--bare', '--rounds', str(ROUNDS)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=1800)
            path = OUT / f'{index}-{arm}-rep{len(reps)}.log'
            path.write_text(result.stdout + result.stderr)
            summary = next((json.loads(line) for line in reversed(result.stdout.splitlines())
                            if line.startswith('{')), None)
            reps.append(dict(exit_code=result.returncode, log=path.name,
                             completed=summary and summary['completed'], failures=summary and summary['failures'],
                             examples=summary and summary['examples'], errors=summary and summary['errors']))
            failures += (summary or {}).get('failures', 0)
        elapsed = time.time() - started
    finally:
        for p in injectors:
            p.terminate()
        for p in injectors:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
    after = info(port)
    stop(proc)
    log.close()
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in sorted(set(after) | set(before))
             if after.get(k, 0) != before.get(k, 0)}
    return dict(block=index, arm=arm, binary=str(ARMS[arm]), port=port, boot=args,
                injectors='8 x (spin 20 us, sleep 30 us), one per server CPU 96-103',
                seconds=round(elapsed, 1), iterations=sum(r['completed'] or 0 for r in reps),
                failures=sum(r['failures'] or 0 for r in reps), reps=reps, counter_deltas=delta)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, used = [], set()
    for index, arm in enumerate(['PRE', 'POST', 'POST', 'PRE']):
        row = block(arm, index, used)
        rows.append(row)
        (OUT / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
        deltas = row['counter_deltas']
        print(f"block {index} {arm}: {row['iterations']} bare iterations in {row['seconds']}s, "
              f"{row['failures']} failures, group_wounds={deltas.get('atomic_group_wounds')}, "
              f"group_retries={deltas.get('atomic_group_retries')}, "
              f"order_violations={deltas.get('atomic_txn_order_violations', 0)}", flush=True)
        for rep in row['reps']:
            for example in rep['examples'] or []:
                print('   ', example, flush=True)


if __name__ == '__main__':
    main()
