#!/usr/bin/env python3
"""One serial PRE/POST diagnostic for the gate's failed FIFO latency-guard leg.

This repeats the existing test unchanged; it is not a replacement gate receipt.
Run only after the main selected gate has exited. Preserve the first failure.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests'))
from authfix import Run, Server


def main():
    assert os.sched_getaffinity(0) <= set(range(100, 112))
    os.environ['LC_ALL'] = 'C'
    build = ROOT/'build/cmdfix2'
    main_run = json.loads((build/'post-v2-main-uring.json').read_text())
    assert 'exit_code' in main_run, 'do not overlap the remaining selected gate'
    output = build/'fifo-diagnostic'
    output.mkdir()
    rows = []
    for arm in ('PRE', 'POST'):
        args = SimpleNamespace(output=output/arm, cores='100-107', port=21340,
                               ratio='6:2', databases=1)
        binary = build/arm
        run = Run(args, binary)
        server = Server(run, '2s-epoll-db1-a1', '2s')
        # Match job_txnorder_fifo_live's effective boot arguments exactly.
        server.args = ['taskset', '-c', args.cores, str(binary), '--port', str(args.port),
                       '--bind', '127.0.0.1', '--shards', '16', '--dir', str(server.directory),
                       '--save', '', '--ratio', '6:2', '--databases', '1', '--atomic', '1',
                       '--net-io', 'epoll', '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0',
                       '--enable-debug-command', 'yes']
        evidence = run.path/'fifo.json'
        command = ['taskset', '-c', '108-111', 'python3', 'tests/execfair.py', '127.0.0.1',
                   str(args.port), '--fifo', '--seconds', '60', '--clients', '64',
                   '--output', str(evidence)]
        with server:
            with (run.path/'test.log').open('w') as log:
                process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True)
                try:
                    code = process.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    code = 124
        clean = subprocess.run(['python3', 'tests/shutdown_report.py',
                                str(server.path/'server.log'), 'clean'], cwd=ROOT,
                               capture_output=True, text=True)
        (run.path/'shutdown.log').write_text(clean.stdout + clean.stderr)
        row = dict(arm=arm, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                   test_sha256=hashlib.sha256((ROOT/'tests/execfair.py').read_bytes()).hexdigest(),
                   command=command, server_argv=server.args, LC_ALL='C', exit_code=code,
                   shutdown_exit_code=clean.returncode,
                   result=json.loads(evidence.read_text()) if evidence.exists() else None)
        rows.append(row)
        (output/'summary.json').write_text(json.dumps(rows, indent=2)+'\n')
        print(arm, 'exit', code, 'shutdown', clean.returncode,
              'guard', row['result'].get('fifo') if row['result'] else None, flush=True)
    return int(any(row['exit_code'] or row['shutdown_exit_code'] for row in rows))


if __name__ == '__main__':
    raise SystemExit(main())
