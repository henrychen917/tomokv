#!/usr/bin/env python3
"""Run snapfix2 correctness receipts on CPUs 0-15 / ports 20100-20199 only.

No performance workloads, full gate, debugger, or core capture. Each command is
recorded with its input digest, exit code and output digest, including failures.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/snapfix2'
ORACLE = '/home/user/Projects/redis/src/redis-server'
ARMS = {'pre': 'build/snapfix2/pre/tomokv', 'base': 'build/snapfix2/base/tomokv',
        'post': 'build/tomokv'}
JOBS = '''snapfix_shutdown snapfix_bgsave_script snapfix_bgsave_exec snapfix2_tables
snapshot-epoll snapshot-uring persistfix2_lastsave persistfix2_shutdown persistfix2_commands
persistfix2_errors persistfix_units dump_restore debug-0 debug-1 aof-epoll aof-uring
aof_frame aoforder notify_aof serverfix_waitaof iofix-signal climonfix
txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 txnorder2
txnorder_wake txnorder_index execfair txn_group_fused txn_group_split
script_bounds scriptfix lualibs flip fliplisten flipctl flip_saturated flip_unit
flipfix_units atomic_units atomic_batteries atomfix5_watch atomfix5_accounting
moverfix fused-0 fused-1 source_identity storage_units'''.split()


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run(label, cmd, binary, timeout=3600, env=None):
    directory = OUT / label
    directory.parent.mkdir(parents=True, exist_ok=True)
    log = directory.with_suffix('.log')
    record = dict(command=cmd, environment=env or {}, binary=binary,
                  binary_sha256=sha(binary), oracle_sha256=sha(ORACLE))
    started = time.monotonic()
    with log.open('w') as f:
        p = subprocess.Popen(cmd, cwd=ROOT, env=os.environ | (env or {}),
                             stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            record['exit'] = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            record['timeout'] = timeout
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            record['exit'] = p.returncode
    record.update(seconds=round(time.monotonic()-started, 3), log_sha256=sha(log))
    # Tests have completed their reload checks before returning. Keep digests of
    # their snapshot/AOF payloads instead of committing or retaining those data.
    removed = {}
    if directory.is_dir():
        for path in directory.rglob('*'):
            if path.is_file() and path.suffix in {'.tomo', '.rdb', '.aof', '.tmp'}:
                removed[str(path.relative_to(directory))] = dict(
                    bytes=path.stat().st_size, sha256=sha(path))
                path.unlink()
    record['removed_data'] = removed
    directory.with_suffix('.command.json').write_text(json.dumps(record, indent=2)+'\n')
    print(label, 'exit', record['exit'], 'seconds', record['seconds'], flush=True)
    return record, log


def matrix(script, case, label, arm='post', extra=(), timeout=1500):
    return run(label, ['taskset', '-c', '8-15', 'python3', 'tests/'+script+'.py',
                      '--case', case, '--binary', ARMS[arm], '--oracle', ORACLE,
                      '--cores', '0-7', '--port', '20100', '--output', str(OUT/label),
                      *extra], ARMS[arm], timeout)


def prune_gate_run(run_dir, archive):
    """The recorder hashed every artifact. Preserve large text compressed,
    then discard the completed run's temporary binaries, source trees and data."""
    run_dir, archive = Path(run_dir), Path(archive)
    assert run_dir.parent == ROOT / 'build' and run_dir.name.startswith('gate-run.')
    receipt = archive / 'record.json'
    record = json.loads(receipt.read_text())
    kept = {}
    for path in run_dir.rglob('*'):
        if path.is_file() and path.suffix in {'.log', '.txt', '.json', '.tsv'} and path.stat().st_size > 512*1024:
            target = archive / (str(path.relative_to(run_dir))+'.gz')
            target.parent.mkdir(parents=True, exist_ok=True)
            with path.open('rb') as src, gzip.open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            kept[str(target.relative_to(archive))] = sha(target)
    record.update(compressed_large_text=kept, removed_run_artifacts=True)
    receipt.write_text(json.dumps(record, indent=2)+'\n')
    shutil.rmtree(run_dir)


def gate(engine, differ=False, extra=False, fused=False, table_arm=None, auth=False):
    label = ('auth-' if auth else 'extra-' if extra else 'differ-' if differ else 'proof-')+engine
    if extra or auth:
        label += '-1s' if fused else '-2s'
    jobs = ('auth' if auth else 'release_batteries asan_batteries' if extra else
            'differ-split differ-armed' if differ else ' '.join(JOBS))
    if extra:
        # The gate's Lua/script-surface batteries live inside its feature jobs.
        # Keep their complete boot lifetimes, including the shutdown witnesses.
        shape = 'armed' if fused else 'split'
        jobs += f' feature-{shape}-0 feature-{shape}-1 notify'
        if not fused:
            # These contain the serverless snapshot migration and retirement
            # callers as well as their existing negative controls.
            jobs += ' core_units wait_units'
    if extra and fused:
        # Mirror the ordinary split boots that use the gate's existing mode
        # switch. Explicit mode/engine matrices already ran in the main pass.
        jobs += (' debug-0 debug-1 atomic_batteries script_bounds dump_restore aof_frame'
                 f' snapshot-{engine} aof-{engine}')
    binary = ARMS[table_arm or 'post']
    if table_arm:
        label, jobs = 'tables-'+table_arm+'-final', 'snapfix2_tables'
    env = dict(GATE_ONLY_JOBS=jobs, REDIS74_ROOT='/home/user/Projects/redis',
               GATE_NET_IO=engine, GATE_DIFFER_NET_IO=engine, GATE_PROOF_NO_RATES='1')
    if extra or auth:
        env['GATE_TXN_FUSED'] = '1' if fused else '0'
    cmd = ['taskset', '-c', '0-15', 'tests/gate.sh', 'iteration',
           '--server-cores', '0-7', '--load-cores', '8-15', '--server-smt', '',
           '--load-smt', '', '--ports', '20100-20199']
    if table_arm:
        cmd += ['--candidate-binary', binary]
    _, log = run('proof/'+label, cmd, binary, 14400, env)
    m = re.search(r'artifacts: (\S+)', log.read_text())
    if m:
        subprocess.run(['python3', 'tools/snapfix_record.py', m[1], '--name', label,
                        '--command', shlex.join(['env', *[k+'='+v for k,v in env.items()], *cmd]),
                        '--binary', binary, '--log', str(log),
                        '--output-root', str(OUT/'proof')], check=True)
        prune_gate_run(m[1], OUT/'proof'/label)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['gate-uring', 'gate-epoll', 'differ-uring', 'differ-epoll',
                                    'isolation', 'minimal', 'ingredients', 'rss', 'diagnostic',
                                    'long', 'neighbours', 'pad', 'extra', 'auth'])
    a = p.parse_args()
    os.chdir(ROOT)
    os.sched_setaffinity(0, range(16))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if a.phase.startswith(('gate-', 'differ-')):
        gate(a.phase.split('-')[1], a.phase.startswith('differ'))
    elif a.phase in ['extra', 'auth']:
        for engine in ['uring', 'epoll']:
            for fused in [False, True]:
                gate(engine, extra=a.phase == 'extra', auth=a.phase == 'auth', fused=fused)
    elif a.phase == 'pad':
        for arm, binary in [('post-layout', 'build/snapfix2/POST-layout'),
                            ('pad-a', 'build/snapfix2/PAD-A')]:
            ARMS[arm] = binary
            # The layout twin must pass; BASE-behaviour PAD-A must retain the
            # doubling failure. The individual command receipts retain both.
            matrix('snapfix', 'bgsave-loop', 'pad/'+arm, arm,
                   ['--atomics', '1', '--no-oracle'])
        for arm in ['pre', 'base', 'post']:
            gate('uring', table_arm=arm)
        matrix('snapfix2_rss', 'large-rss', 'rss/large-final',
               extra=['--dataset', '1000000', '--stall', '60'])
    elif a.phase == 'isolation':
        for arm in ARMS:
            for label, extra in [('no-save', ['--flushall-bgsave', '0']),
                                 ('no-save-no-flush', ['--flushall-bgsave', '0', '--flushall-flush', '0']),
                                 ('full', [])]:
                matrix('snapfix_neighbours', 'flushall', f'isolation/{arm}-{label}-final', arm, extra)
    elif a.phase == 'minimal':
        for arm in ARMS:
            matrix('snapfix2_flush', 'flush-pair', f'isolation/{arm}-minimal-final', arm)
            matrix('snapfix2_flush', 'flush-only', f'isolation/{arm}-flush-only', arm)
    elif a.phase == 'ingredients':
        for arm in ARMS:
            for mix in ['scripts', 'execs']:
                matrix('snapfix_neighbours', 'flushall', f'isolation/{arm}-{mix}-only', arm,
                       ['--flushall-bgsave', '0', '--flushall-mix', mix])
    elif a.phase == 'rss':
        matrix('snapfix2_rss', 'large-rss', 'rss/large', extra=['--dataset', '1000000', '--stall', '60'])
    elif a.phase == 'neighbours':
        for case in ['shutdown-save', 'sigterm', 'bgsave-flip', 'aofrw-exec', 'aofrw-script']:
            matrix('snapfix_neighbours', case, 'neighbours/'+case)
        for arm in ARMS:
            matrix('snapfix2_flush', 'flush-script', f'isolation/{arm}-script-minimal', arm)
    else:
        for mode in ['1s', '2s']:
            for engine in ['uring', 'epoll']:
                if a.phase == 'diagnostic':
                    label = f'diagnostic/{mode}-{engine}'
                    cmd = ['taskset', '-c', '8-15', 'python3', 'tests/at412_diagnostics.py',
                           '--defect', 'SNAP-STORM-1', '--binary', ARMS['post'], '--oracle', ORACLE,
                           '--cores', '0-7', '--port', '20100', '--atomic', '1', '--mode', mode,
                           '--engine', engine, '--attempts', '5', '--seconds', '30',
                           '--mix', 'scripts,writers', '--pre-control', '--output', str(OUT/label)]
                    run(label, cmd, ARMS['post'], 260)
                else:
                    for seconds in [6, 30, 60]:
                        label = f'long/{mode}-{engine}-{seconds}'
                        cmd = ['taskset', '-c', '8-15', 'python3', 'tools/snapfix_long_storm.py',
                               '--binary', ARMS['post'], '--oracle', ORACLE, '--cores', '0-7',
                               '--port', '20100', '--mode', mode, '--engine', engine,
                               '--atomic', '1', '--seconds', str(seconds), '--stall', '30',
                               '--output', str(OUT/label)]
                        run(label, cmd, ARMS['post'], seconds+150)
                        timeline = json.loads((OUT/label/'timeline.json').read_text())
                        rss = [r['used_memory_rss'] for r in timeline['timeline']
                               if r.get('used_memory_rss', 0) > 0]
                        assert len(rss) >= 2, ('storm RSS sampler never armed', label)
                        check = dict(samples=len(rss), baseline=rss[1], peak=max(rss),
                                     limit=3*rss[1]+(64 << 20))
                        check['pass'] = bool(timeline.get('pass')) and check['peak'] <= check['limit']
                        (OUT/label/'rss-check.json').write_text(json.dumps(check, indent=2)+'\n')
                        assert check['pass'], ('storm RSS grew or storm failed', label, check)


if __name__ == '__main__':
    main()
