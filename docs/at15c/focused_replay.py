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
import select
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
p.add_argument('--warmup', action='store_true',
               help='run the six preceding seed-7 harness suites before edgetime')
p.add_argument('--stop-on-failure', action='store_true')
p.add_argument('--observed-mask', action='store_true',
               help='diagnostic control: recreate the broadened server masks observed in full replays')
p.add_argument('--compiler-control', action='store_true',
               help='labelled contention control: eight owned serverless compiles on CPUs 112-119')
p.add_argument('--absolute-control', action='store_true',
               help='separate diagnostic: replace only the two PTTL queries with PEXPIRETIME')
args = p.parse_args()
assert not args.absolute_control or args.trace
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=False)
for port in (17899, 17900):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', port))
children, files, descriptors, results = [], [], [], []
compilers = []


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
        compiling_before = [proc.pid for proc in compilers if proc.poll() is None]
        env = dict(os.environ)
        if args.absolute_control:
            env['AT15C_ABSOLUTE_CONTROL'] = '1'
        result = subprocess.run(['taskset', '-c', '121-127', *command], env=env,
                                stdout=log, stderr=subprocess.STDOUT, timeout=180)
    results.append(dict(label=label, command=command, rc=result.returncode,
                        start_ns=start, end_ns=time.time_ns(),
                        compilers_before=compiling_before,
                        compilers_after=[proc.pid for proc in compilers if proc.poll() is None],
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
    if args.warmup:
        for suite in ('string', 'list', 'set', 'zset', 'hash', 'hexpire'):
            run('warmup-' + suite, ['python3', 'tests/differ.py',
                '127.0.0.1', '17899', '127.0.0.1', '17900', suite, '7'])
    if args.observed_mask:
        before = dict(target=affinity(target.pid), oracle=affinity(oracle.pid))
        for server in (target, oracle):
            for task in Path(f'/proc/{server.pid}/task').iterdir():
                os.sched_setaffinity(int(task.name), set(range(112, 128)))
        (out / 'affinity-control.json').write_text(json.dumps(dict(
            kind='recreate observed broadened masks; separate diagnostic control',
            before=before, after=dict(target=affinity(target.pid), oracle=affinity(oracle.pid))),
            indent=2) + '\n')
    if args.compiler_control:
        commands = []
        for index in range(8):
            command = ['taskset', '-c', str(112 + index), 'g++', '-std=c++20', '-O2', '-g',
                       '-march=native', '-pthread', '-DTOMO_JEMALLOC', '-I.',
                       '--param', 'inline-unit-growth=0', '--param', 'large-unit-insns=127577',
                       '-c', 'src/cmd/xshard.cc', '-o', str(out / f'compiler-{index}.o')]
            log = (out / f'compiler-{index}.log').open('w')
            files.append(log)
            compiler = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                        start_new_session=True)
            compilers.append(compiler)
            commands.append(dict(pid=compiler.pid, command=command))
        (out / 'compiler-control.json').write_text(json.dumps(dict(
            kind='deliberately recreate observed compiler contention; not a regression measurement',
            commands=commands), indent=2) + '\n')
    perf = None
    if args.perf:
        log = (out / 'perf.log').open('w')
        files.append(log)
        control_read, control_write = os.pipe()
        ack_read, ack_write = os.pipe()
        descriptors.extend((control_write, ack_read))
        perf_command = ['taskset', '-c', '127', 'perf', 'record', '-C', '112-119',
                    '-g', '--clockid', 'mono', '--call-graph', 'dwarf,8192', '--switch-events', '-e', 'cycles:u',
                    '-F', '999', '-D', '-1', '--control', f'fd:{control_read},{ack_write}',
                    '-o', str(out / 'perf.data')]
        (out / 'perf-command.json').write_text(json.dumps(perf_command) + '\n')
        perf = subprocess.Popen(perf_command,
                    stdout=log, stderr=subprocess.STDOUT, pass_fds=(control_read, ack_write))
        children.append(perf)
        os.close(control_read)
        os.close(ack_write)
        os.write(control_write, b'enable\n')
        ack = os.read(ack_read, 64) if select.select([ack_read], [], [], 15)[0] else b''
        # perf 7.0 writes sizeof("ack\n"), including the terminating NUL.
        if ack not in (b'ack\n', b'ack\n\0'):
            raise RuntimeError('perf did not acknowledge enabled events')
        (out / 'perf-enabled.json').write_text(json.dumps(dict(
            mono_ns=time.monotonic_ns(), wall_ns=time.time_ns(), ack_hex=ack.hex())) + '\n')
    for index in range(args.runs):
        label = f'edgetime-{index + 1}'
        command = ['python3', 'docs/at15c/trace_differ.py', str(out / label)] if args.trace \
            else ['python3', 'tests/differ.py']
        run(label, [*command, '127.0.0.1', '17899', '127.0.0.1', '17900', 'edgetime', '7'])
        if args.stop_on_failure and results[-1]['rc']:
            data = json.loads((out / (label + '.json')).read_text())
            replies = {(event['side'], event['op']): bytes.fromhex(event['reply'])
                       for event in data['events'] if event['kind'] == 'reply'}
            if any(abs(int(replies['target', op][1:-2])-int(replies['oracle', op][1:-2])) > 1
                   for op in (1526, 2910)):
                break
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
    for proc in compilers:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)
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
    for descriptor in descriptors:
        os.close(descriptor)
    (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
