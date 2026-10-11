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
        shape += ['--notify-keyspace-events', 'KEAmn']
    if job == 'auth':
        shape += ['--dbfilename', 'reload.tomo']
    # Rows witnessed only by existing observables run the production binary
    # itself, unarmed; only the remaining rows need the isolated witness build.
    existing = row.get('observable') == 'existing'
    binary = (args.production_binary if existing else args.binary).resolve()
    env['GATE_CANDIDATE_BINARY'] = str(binary)
    if row['id'] == '503':
        binary = binary.with_name('tomokv-asan')
        if not binary.exists():
            raise ValueError('row 503 requires the lottery ASAN binary; cannot substitute release')
        # The gate's ASAN boot judges memory errors (its separate "ASAN clean"
        # row), not exit-time leak accounting of still-connected clients.
        # The server inherits this process's environment, not the battery's env.
        os.environ['ASAN_OPTIONS'] = env['ASAN_OPTIONS'] = 'detect_leaks=0:abort_on_error=1'
        env['GATE_CANDIDATE_BINARY'] = str(binary)
    logs, counts, boots = [], [], []

    def battery(script, arguments, name):
        return run([sys.executable, str(ROOT / 'tests/lottery_test_driver.py'),
                    str(ROOT / 'tests' / script), *map(str, arguments)], directory, name, env)

    @contextlib.contextmanager
    def boot(name, extra=()):
        with server(binary, args.server_cpus, args.port, directory / name,
                    shape + list(extra)) as (admin, child):
            before = info(admin)
            path = None if existing else directory / (name + '.trace')
            if path:
                admin.must('DEBUG', 'LOTTERY', 'ARM', mask, str(path))
            record = dict(pid=child.pid, before=before, trace=path and str(path),
                          binary=str(binary))
            boots.append(record)
            try:
                yield admin, child
            finally:
                if child.poll() is None:
                    record['after'] = info(admin)
                    record['stopped'] = (not path or
                                         admin.must('DEBUG', 'LOTTERY', 'STOP') == b'OK')
                write_json(directory / 'boots.json', boots)

    if family == 'differential matrix':
        # The gate's own matrix script, focused on the four suites that carry
        # this row's class-B legs (W3 s6fix, W13 climon, W14 psfix, W15 stream;
        # flakeaudit2 keeps the other 40 suites DETERMINISTIC). Every permanent
        # seed plus one fresh rotating seed, both atomics, the row's geometry.
        # Only the Python driver boundary changes, to insert observation markers.
        original = (ROOT / 'tests/differ_gate.sh').read_text()
        anchor = 'cd "$(dirname "$0")/.."'
        if original.count(anchor) != 1 or original.count('python3 tests/differ.py') != 2:
            raise ValueError('changed differ_gate.sh driver boundary; review the adapter')
        shell = original.replace(anchor, f'cd {__import__("shlex").quote(str(ROOT))}')
        shell = shell.replace('python3 tests/differ.py',
                              'python3 tests/lottery_test_driver.py tests/differ.py')
        script = directory / 'differ.sh'
        script.write_text(shell)
        suites, seeds = directory / 'suites.txt', directory / 'seeds.txt'
        suites.write_text('s6fix\nclimon\npsfix\nstream\n')
        sys.path.insert(0, str(ROOT / 'tests'))
        from _differ_history import permanent_seeds
        fixed = permanent_seeds()
        fresh = int.from_bytes(os.urandom(4), 'little') % 1000000 + 1000
        while fresh in fixed:
            fresh += 1
        seeds.write_text(''.join(f'{seed}\n' for seed in [*fixed, fresh]))
        load = cpus(args.client_cpus)
        env.update(LOTTERY_AUTO_TRACE=str(directory / 'traces'),
                   GATE_DIFFER_GEOMETRY='armed-fused' if row['id'] == '516' else 'split',
                   GATE_DIFFER_ORACLE_CORES=str(load[0]),
                   GATE_LOAD_CORES=f'{load[1]}-{load[-1]}',
                   GATE_DIFFER_OUT=str(directory / 'matrix'),
                   GATE_DIFFER_PROOF_SUITES=str(suites), GATE_DIFFER_PROOF_SEEDS=str(seeds),
                   GATE_DIFFER_HISTORY=str(directory / 'history'),
                   REDIS74_ROOT='/home/user/Projects/redis74')
        passed, log = run(['bash', str(script), str(binary), str(args.port),
                           str(args.port + 1), args.server_cpus, '6:2'], directory, 'matrix', env)
        counters = {k: 0 for k in row['requires']}
        suite_counts = {}
        for meta in sorted((directory / 'traces').glob('*.json')):
            rec = json.loads(meta.read_text())
            if not rec.get('stopped'):
                raise ValueError(f'differ trace did not stop cleanly: {meta}')
            suite = rec['argv'][5]
            c = reduce_events(trace(rec['trace'], rec['pid']))
            suite_counts.setdefault(suite, []).append(dict(c))
        traces = len(list((directory / 'traces').glob('*.trace')))
        legs = {name: len(values) for name, values in suite_counts.items()}
        if traces != sum(legs.values()):
            raise ValueError(f'{traces} differ traces but {sum(legs.values())} closed records')
        expected = 2 * len(fixed) + 2      # both atomics x (permanent + fresh seed)
        if passed and legs != {name: expected for name in ('s6fix', 'climon', 'psfix', 'stream')}:
            raise ValueError(f'focused matrix legs {legs}; expected {expected} per suite')
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
                # The gate's throwaway boots use the first four slot CPUs (GATE_CORES).
                arguments += ['--binary', binary, '--spare-port', args.port + 2]
            passed, log = battery(family + '.py', arguments, 'row')
        logs.append(log)
    if row['id'] == '503':
        passed &= 'ERROR: AddressSanitizer' not in (directory / 'server/server.log').read_text(
            errors='replace')
    record = boots[-1]
    if 'after' not in record or not record.get('stopped'):
        raise ValueError('server exited before its witness interval closed')
    events = trace(record['trace'], record['pid']) if record['trace'] else ()
    counts.append(observed(row, events, log, record['before'], record['after']))
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
    parser.add_argument('--production-binary', type=Path, required=True)
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
