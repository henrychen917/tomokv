#!/usr/bin/env python3
"""One fresh class-B row. Invoked in the runner's owned process group."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import traceback

from _gate_process import cpus, info, server
from lottery_evidence import observed, reduce_events, trace
from lottery_runner import ROOT, registry, write_json


def run(argv, directory, name, env):
    path = directory / (name + '.log')
    with path.open('w') as log:
        child = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = child.wait()
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
    return code == 0, path.read_text(errors='replace')


def attempt(row, args):
    os.sched_setaffinity(0, cpus(args.client_cpus))
    directory = args.output.resolve()
    mask = sum(1 << int(p[1:]) for p in set(row['primitives']))
    env = dict(os.environ, LOTTERY_PORT=str(args.port), LOTTERY_FAMILY=row['family'],
               LOTTERY_MASK=str(mask), GATE_CORES=args.server_cpus,
               GATE_LOAD_CORES=args.client_cpus, GATE_CANDIDATE_BINARY=str(args.binary),
               GATE_SPARE_PORT=str(args.port + 2), PYTHONUNBUFFERED='1',
               TMPDIR=str(directory))
    family, job = row['family'], row['job']
    mode = 'fused' if job.startswith(('fused-', 'feature-armed-')) else 'split'
    atomic = int(job.rsplit('-', 1)[-1]) if job[-1:] in ('0', '1') else 0
    if family in ('atomic_torn', 'atomic_hazards'):
        atomic = 1
    shape = ['--shards', '16', '--atomic', str(atomic)]
    if mode == 'fused':
        shape += ['--thread-mode', 'fused', '--read-local', str(int(job.startswith('feature-armed-')))]
    else:
        shape += ['--ratio', '6:2']
    if job.startswith('debug-'):
        shape += ['--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
    if job == 'notify':
        shape += ['--notify-keyspace-events', 'KEA']
    binary = args.binary.resolve()
    if row['id'] == '503':
        binary = binary.with_name('tomokv-asan')
        if not binary.exists():
            raise ValueError('row 503 requires the lottery ASAN binary; cannot substitute release')
        env['ASAN_OPTIONS'] = 'detect_leaks=1:abort_on_error=1'
    logs, counts, boots = [], [], []

    def battery(script, arguments, name):
        return run([sys.executable, str(ROOT / 'tests/lottery_test_driver.py'),
                    str(ROOT / 'tests' / script), *map(str, arguments)], directory, name, env)

    @contextlib.contextmanager
    def boot(name, extra=()):
        with server(binary, args.server_cpus, args.port, directory / name,
                    shape + list(extra)) as (admin, child):
            before = info(admin)
            path = directory / (name + '.trace')
            admin.must('DEBUG', 'LOTTERY', 'ARM', mask, str(path))
            record = dict(pid=child.pid, before=before, trace=str(path), binary=str(binary))
            boots.append(record)
            try:
                yield admin, child
            finally:
                if child.poll() is None:
                    record['after'] = info(admin)
                    record['stopped'] = admin.must('DEBUG', 'LOTTERY', 'STOP') == b'OK'
                write_json(directory / 'boots.json', boots)

    if family == 'differential matrix':
        # Reuse the complete gate matrix, including seeds/repeats/coverage. Only
        # replace its Python driver boundary to insert observation markers.
        original = (ROOT / 'tests/differ_gate.sh').read_text()
        shell = original.replace('cd "$(dirname "$0")/.."', f'cd {__import__("shlex").quote(str(ROOT))}')
        shell = shell.replace('python3 tests/differ.py',
                              'python3 tests/lottery_test_driver.py tests/differ.py')
        script = directory / 'differ.sh'
        script.write_text(shell)
        env.update(LOTTERY_AUTO_TRACE=str(directory / 'traces'),
                   GATE_DIFFER_GEOMETRY='armed-fused' if row['id'] == '516' else 'split',
                   GATE_DIFFER_ORACLE_CORES='120', GATE_LOAD_CORES='121-127',
                   GATE_DIFFER_OUT=str(directory / 'matrix'),
                   REDIS74_ROOT='/home/user/Projects/redis74')
        passed, log = run(['bash', str(script), str(binary), str(args.port),
                           str(args.port + 1), args.server_cpus, '6:2'], directory, 'matrix', env)
        counters = {k: 0 for k in row['requires']}
        suite_counts = {}
        for meta in sorted((directory / 'traces').glob('*.json')):
            rec = json.loads(meta.read_text())
            suite = rec['argv'][5]
            c = reduce_events(trace(rec['trace'], rec['pid']))
            suite_counts.setdefault(suite, []).append(dict(c))
        # A compound public row needs every leg of every relevant submechanism.
        for witness, suite in [('W13', 'climon'), ('W14', 'psfix'), ('W15', 'stream')]:
            values = suite_counts.get(suite, [])
            counters[witness] = int(bool(values) and all(v.get(witness, 0) > 0 for v in values))
        coverage = []
        for path in (directory / 'matrix').rglob('*s6fix*.txt'):
            text = path.read_text(errors='replace')
            coverage.append(all(re.search(rf'A4 {side} distinct=200 missing=0 unexpected=0 nulls=0', text)
                                for side in ('target', 'oracle')))
        counters['W3'] = int(bool(coverage) and all(coverage))
        write_json(directory / 'differ-witnesses.json', suite_counts)
        return passed, counters, boots

    if family == 'TLS partial handshake/teardown':
        certs = directory / 'certs'
        ok, log = run([sys.executable, 'tests/tls.py', '--generate', str(certs)], directory, 'certificates', env)
        if not ok:
            raise ValueError('TLS certificate generation failed')
        shape += ['--tls-port', str(args.port + 1), '--tls-cert-file', str(certs / 'server.crt'),
                  '--tls-key-file', str(certs / 'server.key'), '--tls-ca-cert-file', str(certs / 'ca.crt'),
                  '--tls-auth-clients', 'no', '--tls-protocols', 'TLSv1.2 TLSv1.3',
                  '--tls-ciphers', 'ECDHE-RSA-AES256-SHA384',
                  '--tls-ciphersuites', 'TLS_AES_256_GCM_SHA384',
                  '--tls-prefer-server-ciphers', 'yes']
    if family in ('snapshot capture/reload', 'snapshot groups'):
        shape += ['--net-io', job.split('-')[1], '--dbfilename', 'cut.tomo']
    if family == 'snapshot groups':
        is_exec = row['id'] in ('344', '352')
        shape[shape.index('--atomic') + 1] = str(0 if is_exec else 1)

    with boot('server') as (admin, child):
        if family == 'snapshot capture/reload':
            passed, log = battery('snap_cut_battery.py', [args.port, 'save'], 'save')
        elif family == 'snapshot groups':
            passed, log = battery('snap_cut_battery.py', [args.port, 'atomic_groups',
                directory / 'server/data/cut.tomo', 'exec' if is_exec else 'mset', 3 if is_exec else 5], 'groups')
            passed &= 'ATOMIC_GROUP_CUT PASS' in log
        elif family == 'spinprobe':
            arguments = [args.port, child.pid] + (['--idle-only'] if row['id'] == '122' else [])
            passed, log = battery('spinprobe.py', arguments, 'row')
        elif family == 'TLS partial handshake/teardown':
            passed, log = battery('tls.py', ['127.0.0.1', args.port + 1, certs, 'no',
                '--plain-port', args.port, '--full', '--expect-ktls', 'no'], 'row')
        elif family == 'flip saturated':
            # Copy the gate's row body, with its exact producer geometry and
            # assertions, but run inside this attempt's owned process group.
            gate = (ROOT / 'tests/gate.sh').read_text()
            start = gate.index('  taskset -c "$LOAD_CORES" memtier_benchmark', gate.index('job_flip_saturated(){'))
            end = gate.index('\n) && ok "FLIP applies under saturated load"', start)
            script = directory / 'flip.sh'
            script.write_text('set -u\n' + gate[start:end] + '\n')
            env.update(LOAD_CORES=args.client_cpus, PORT=str(args.port))
            passed, log = run(['bash', str(script)], directory, 'row', env)
        else:
            arguments = ['127.0.0.1', args.port]
            if family in ('atomic_torn', 'xmove') and row['id'] != '503':
                arguments += ['--release-build']
            if family == 'servertail':
                arguments += ['--binary', binary, '--cores', args.server_cpus,
                              '--spare-port', args.port + 2]
            passed, log = battery(family + '.py', arguments, 'row')
        logs.append(log)
    record = boots[-1]
    counts.append(observed(row, trace(record['trace'], record['pid']), log,
                           record['before'], record['after']))
    if family == 'snapshot capture/reload':
        # Reload rows always create a fresh witnessed capture first. Capture
        # rows also retain the exact disk oracle instead of trusting BGSAVE OK.
        with boot('reload', ['--dir', directory / 'server/data']) as (admin, child):
            ok, log = battery('snap_cut_battery.py', [args.port, 'verify_cut'], 'verify')
            passed &= ok and 'VERIFY_CUT PASS' in log
            logs.append(log)
    write_json(directory / 'counter-receipts.json', counts)
    return bool(passed), counts[0], boots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--row', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--server-cpus', required=True)
    parser.add_argument('--client-cpus', required=True)
    args = parser.parse_args()
    row = next(r for r in registry() if r['id'] == args.row)
    receipt = dict(row=args.row, nonce=args.nonce, completed=True, passed=False,
                   evidence_complete=False, counters={})
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        passed, counters, boots = attempt(row, args)
        receipt.update(passed=passed, counters=counters, evidence_complete=True,
                       server_pids=[b['pid'] for b in boots])
    except KeyboardInterrupt:
        receipt.update(completed=False, reason='attempt interrupted')
    except Exception as exc:
        traceback.print_exc()
        receipt['error'] = f'{type(exc).__name__}: {exc}'
    write_json(args.output / 'receipt.json', receipt)
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
