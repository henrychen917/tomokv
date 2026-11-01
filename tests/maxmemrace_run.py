#!/usr/bin/env python3
"""Lane maxmemrace: run the CONFIG SET maxmemory toggle stress over a leg matrix.

Each leg boots one fresh server (TomoKV in a named geometry, or the Redis 7.4
oracle), runs tests/maxmemrace_stress.cc against it and records the driver's JSON.
Servers are owned by Popen PID only and stopped with SIGTERM; every boot pins
LC_ALL=C. No rate or latency is recorded or claimed.
"""
import argparse
import itertools
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
            return True
    except OSError:
        return False


def boot(argv, cores, port, log_path):
    if port_open(port):
        raise RuntimeError(f'port {port} already accepts connections')
    env = dict(os.environ, LC_ALL='C')
    with open(log_path, 'w') as log:
        proc = subprocess.Popen(['taskset', '-c', cores, *argv], stdout=log,
                                stderr=subprocess.STDOUT, env=env)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'server exited before listening: {Path(log_path).read_text()[-2000:]}')
        if port_open(port):
            return proc
        time.sleep(0.05)
    stop(proc)
    raise RuntimeError('server never listened')


def stop(proc):
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return proc.returncode


def legs(args):
    out = []
    if args.oracle:
        for policy, submit in itertools.product(args.policies, args.submits):
            out.append(dict(server='redis', mode='-', engine='-', atomic='-', read_local='-',
                            reorder='-', policy=policy, submit=submit))
    if args.binary:
        for mode, engine, atomic, read_local, reorder, policy, submit in itertools.product(
                args.modes, args.engines, args.atomics, args.read_locals, args.reorders,
                args.policies, args.submits):
            if reorder != '0' and mode != '1s':
                continue  # the shadow scheduler is fused-only
            out.append(dict(server='tomokv', mode=mode, engine=engine, atomic=atomic,
                            read_local=read_local, reorder=reorder, policy=policy, submit=submit))
    return out


def argv_for(args, leg, directory):
    port = str(args.port)
    if leg['server'] == 'redis':
        return [args.oracle, '--port', port, '--bind', '127.0.0.1', '--save', '',
                '--appendonly', 'no', '--dir', str(directory)]
    argv = [args.binary, '--port', port, '--bind', '127.0.0.1', '--shards', '16',
            '--dir', str(directory), '--save', '', '--enable-debug-command', 'yes',
            '--net-io', leg['engine'], '--atomic', leg['atomic'], '--read-local', leg['read_local']]
    if leg['reorder'] != '0':
        argv += ['--reorder', leg['reorder']]
    argv += ['--ratio', args.ratio] if leg['mode'] == '2s' else ['--thread-mode', '1s']
    return argv


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary')
    p.add_argument('--oracle')
    p.add_argument('--driver', default=str(ROOT / 'build/maxmemrace/stress'))
    p.add_argument('--port', type=int, default=20301)
    p.add_argument('--server-cores', default='32-39')
    p.add_argument('--load-cores', default='40-47')
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--toggles', type=int, default=100000)
    p.add_argument('--modes', nargs='+', default=['2s', '1s'])
    p.add_argument('--engines', nargs='+', default=['uring', 'epoll'])
    p.add_argument('--atomics', nargs='+', default=['0', '1'])
    p.add_argument('--read-locals', nargs='+', default=['0'])
    p.add_argument('--reorders', nargs='+', default=['0'])
    p.add_argument('--policies', nargs='+', default=['noeviction', 'allkeys-lru'])
    p.add_argument('--submits', nargs='+', default=['single', 'pipe'])
    p.add_argument('--driver-args', default='--bg-threads 3 --bg-conns 4 --bg-pipe 16 '
                   '--bg-mode heavy --bg-keys 256 --conns 8 --per-conn 4 --tight alt')
    p.add_argument('--label', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    if not args.binary and not args.oracle:
        p.error('need --binary and/or --oracle')
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / f'{args.label}.json'
    results = json.loads(results_path.read_text()) if results_path.exists() else []
    done = {r['leg_id'] for r in results if r.get('complete')}
    for leg in legs(args):
        keys = ('server', 'mode', 'engine', 'atomic', 'read_local', 'policy', 'submit')
        # Legs without the shadow scheduler keep their original identifiers.
        leg_id = '-'.join(str(leg[k]) for k in keys) + \
            (f"-reorder{leg['reorder']}" if leg['reorder'] not in ('0', '-') else '')
        if leg_id in done:
            continue
        with tempfile.TemporaryDirectory(dir=out_dir, prefix='leg-') as directory:
            log_path = out_dir / f'{args.label}-{leg_id}.server.log'
            argv = argv_for(args, leg, directory)
            started = time.time()
            proc = boot(argv, args.server_cores, args.port, log_path)
            record = dict(leg_id=leg_id, leg=leg, argv=argv, server_pid=proc.pid,
                          started=started, complete=False)
            try:
                driver = ['taskset', '-c', args.load_cores, args.driver, '--port', str(args.port),
                          '--toggles', str(args.toggles), '--policy', leg['policy'],
                          '--submit', leg['submit'], '--label', f'{args.label}:{leg_id}',
                          *args.driver_args.split()]
                run = subprocess.run(driver, capture_output=True, text=True)
                record.update(driver_argv=driver, driver_rc=run.returncode,
                              driver_stderr=run.stderr[-4000:])
                try:
                    record['result'] = json.loads(run.stdout)
                except json.JSONDecodeError:
                    record['driver_stdout'] = run.stdout[-4000:]
                alive = proc.poll() is None
                record['server_alive_after_driver'] = alive
            finally:
                record['server_rc'] = stop(proc)
                record['elapsed_s'] = round(time.time() - started, 3)
            record['complete'] = 'result' in record and record['server_alive_after_driver']
            results = [r for r in results if r['leg_id'] != leg_id] + [record]
            results_path.write_text(json.dumps(results, indent=1) + '\n')
            r = record.get('result', {})
            print(f"{leg_id}: rc={record['driver_rc']} cycles={r.get('cycles')} "
                  f"lift_oom={r.get('lift_oom')} tight_admitted={r.get('tight_strict_admitted')} "
                  f"evicted_after_lift={r.get('evicted_after_lift')} other={r.get('lift_other', 0) + r.get('tight_other', 0)} "
                  f"{record['elapsed_s']}s", flush=True)
        if port_open(args.port):
            raise RuntimeError(f'port {args.port} still accepts after stopping {leg_id}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
