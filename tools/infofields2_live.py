#!/usr/bin/env python3
"""Serial infofields2 proof runner on the assigned server/load CPUs."""
import argparse
import json
import os
from pathlib import Path
import random
import signal
import socket
import subprocess
import time

from infofields_monitor_strict import load_differ

ROOT = Path(__file__).resolve().parents[1]
ORACLE = Path('/home/user/Projects/redis74/src/redis-server')
PORT, ORACLE_PORT = 18899, 18900
SERVER, LOAD = '112-119', '120-127'


def run(cmd, output, env=None, timeout=None):
    print('COMMAND', json.dumps(cmd), flush=True)
    with output.open('w') as log:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout)
    return dict(command=cmd, log=str(output), exit=result.returncode)


def quiet(out):
    # An initial attempt and up to three retries, spread across ten minutes.
    for attempt in range(4):
        rows = [run(['bash', 'tools/quietcheck.sh', SERVER + ',' + LOAD, str(port)],
                    out / ('quiet-%d-%d.log' % (attempt, port)))
                for port in (PORT, ORACLE_PORT)]
        if all(row['exit'] == 0 for row in rows):
            return rows
        if attempt != 3:
            print('QUIET REFUSAL; retry in 200 seconds', flush=True)
            time.sleep(200)
    raise RuntimeError('quiet preflight refused after the initial attempt and three retries')


def boot(cmd, logfile, port):
    print('BOOT', json.dumps(cmd), flush=True)
    with logfile.open('w') as log:
        process = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError('boot exited: ' + str(logfile))
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                return process
        except OSError:
            time.sleep(.1)
    process.terminate()
    process.wait(timeout=15)
    raise RuntimeError('boot timeout: ' + str(logfile))


def stop(process):
    process.send_signal(signal.SIGTERM)
    code = process.wait(timeout=15)
    assert code == 0, ('orderly termination', process.pid, code)
    return dict(pid=process.pid, exit=code, signal='SIGTERM', forced=False)


def witnesses(out, smoke=False):
    d = load_differ()
    results = []
    for geometry in ('split', 'armed-fused'):
        for atomic in (0, 1):
            for loaded in ((False,) if smoke else (False, True)):
                label = '%s-a%d-config%d' % (geometry, atomic, loaded)
                directory = out / label
                directory.mkdir(parents=True)
                quiet(directory)
                conf = directory / 'loaded.conf'
                conf.write_text('save ""\n')
                oracle_dir = directory / 'oracle'
                target_dir = directory / 'target'
                oracle_dir.mkdir(); target_dir.mkdir()
                shape = ['--ratio', '6:2'] if geometry == 'split' else ['--thread-mode', 'fused', '--read-local', '1']
                target_cmd = ['taskset', '-c', SERVER, str(ROOT / 'build/infofields/POST/tomokv')]
                if loaded:
                    target_cmd += [str(conf.resolve())]
                target_cmd += ['--port', str(PORT), '--bind', '127.0.0.1', '--shards', '16', '--databases', '16', '--atomic', str(atomic), '--save', '', '--dir', str(target_dir.resolve())] + shape
                if not smoke:
                    target_cmd += ['--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
                oracle_cmd = ['taskset', '-c', SERVER, str(ORACLE), '--port', str(ORACLE_PORT), '--bind', '127.0.0.1', '--save', '', '--appendonly', 'no', '--dir', str(oracle_dir.resolve())]
                target = oracle = None
                row = dict(run_id=label, target=target_cmd, oracle=oracle_cmd)
                try:
                    target = boot(target_cmd, directory / 'target.log', PORT)
                    oracle = boot(oracle_cmd, directory / 'oracle.log', ORACLE_PORT)
                    peers = [d.conn('127.0.0.1', port) for port in (PORT, ORACLE_PORT)]
                    try:
                        sock, file = peers[0]
                        sock.sendall(d.enc(['INFO', 'server']))
                        identity = d.infofields_sections(d.read_reply(file))[b'Server']
                        assert identity[b'config_file'] == (str(conf.resolve()).encode() if loaded else b'')
                        row['config_file'] = identity[b'config_file'].decode()
                        import contextlib
                        with (directory / 'rate-peak.log').open('w') as log, contextlib.redirect_stdout(log):
                            d.run_infofields_properties(peers)
                        row['rate_peak'] = 'PASS'
                    finally:
                        for sock, file in peers:
                            file.close(); sock.close()
                    d.TH, d.TP, d.OH, d.OP = '127.0.0.1', PORT, '127.0.0.1', ORACLE_PORT
                    if smoke:
                        row['monitor'] = run(['taskset', '-c', LOAD, 'python3', 'tests/differ.py', d.TH, str(PORT), d.OH, str(ORACLE_PORT), 'monitor', '7'], directory / 'monitor.log')
                        assert row['monitor']['exit'] == 0, row
                        row['strict_refused'] = run(['taskset', '-c', LOAD, 'python3', 'tools/infofields_monitor_strict.py', d.TH, str(PORT), d.OH, str(ORACLE_PORT)], directory / 'strict-refused.log')
                        row['strict_scripts'] = run(['taskset', '-c', LOAD, 'python3', 'tools/infofields_monitor_strict.py', d.TH, str(PORT), d.OH, str(ORACLE_PORT), '--scripts'], directory / 'strict-scripts.log')
                    else:
                        row['infofix'] = run(['taskset', '-c', LOAD, 'python3', 'tests/infofix.py', '127.0.0.1', str(PORT)], directory / 'infofix.log')
                        assert row['infofix']['exit'] == 0, row
                finally:
                    if target:
                        row['target_stop'] = stop(target)
                    if oracle:
                        row['oracle_stop'] = stop(oracle)
                    results.append(row)
                    (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
                print('WITNESS PASS', label, flush=True)
    return results


def matrix(out):
    results = []
    for arm in ('POST', 'PRE'):
        for geometry in ('split', 'armed-fused'):
            label = 'infofields2-%s-%s' % (arm, geometry)
            directory = out / label
            directory.mkdir(parents=True)
            screening = quiet(directory)
            environment = os.environ.copy()
            changes = dict(REDIS74_ROOT='/home/user/Projects/redis74',
                GATE_DIFFER_ORACLE_BIN=str(ORACLE),
                GATE_DIFFER_PROOF_SUITES='docs/infofields/suites.txt',
                GATE_DIFFER_PROOF_SEEDS='docs/infofields/seeds.txt',
                GATE_LOAD_CORES=LOAD, GATE_DIFFER_GEOMETRY=geometry,
                GATE_DIFFER_OUT=str(directory), GATE_RUN_ID=label)
            environment.update(changes)
            command = ['bash', 'tests/differ_gate.sh', 'build/infofields/%s/tomokv' % arm,
                       str(PORT), str(ORACLE_PORT), SERVER, '6:2']
            row = run(command, directory / 'differ.log', environment, timeout=1200)
            row.update(run_id=label, environment=changes, quiet=screening)
            results.append(row)
            (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
            print('MATRIX FINISHED', label, row['exit'], flush=True)
    return results


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('smoke', 'controller', 'matrix'))
    p.add_argument('output', type=Path)
    a = p.parse_args()
    os.chdir(ROOT)
    os.sched_setaffinity(0, set(range(120, 128)))
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    if a.phase == 'matrix':
        matrix(a.output)
    else:
        witnesses(a.output, smoke=a.phase == 'smoke')
