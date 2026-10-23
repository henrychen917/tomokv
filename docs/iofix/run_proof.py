#!/usr/bin/env python3
"""Serialize gate-owned correctness jobs on the iofix lane allocation."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/iofix'
STANDARD = 'differ-split-0 differ-split-1 differ-armed-0 differ-armed-1 differ-equivalence'
# name, jobs, arm, engine, extra mode, force explicit engine, expected gate exit
GROUPS = [
    ('final-directed', 'iofix-deferred iofix-hz iofix-sleep iofix-signal wb_rule_units wbland_units splitlocal_units netcmd_units config_unit boot_grammar auth atomic_units reorder_sync', 'post', '', '', False, 0),
    ('final-uring', STANDARD + ' wb_policy debug-0 debug-1 climonfix flip_unit flipfix_units flip flipctl flip_saturated persistfix_units snapshot-uring snapshot-epoll aof-uring aof-epoll notify reorder_engagement reorder_identity', 'post', 'uring', '', False, 0),
    ('final-native-checks', 'aof-uring reorder_identity', 'post', 'uring', '', False, 0),
    ('final-epoll', STANDARD + ' wb_policy debug-0 debug-1 auth flipctl flip_saturated notify', 'post', 'epoll', '', False, 0),
    ('final-forced-epoll', 'climonfix flip', 'post', 'epoll', '', True, 0),
    ('final-fused-uring', 'auth snapshot-uring snapshot-epoll notify', 'post', 'uring', '1s', False, 0),
    ('final-fused-epoll', 'auth notify', 'post', 'epoll', '1s', False, 0),
    ('pad-a-witnesses', 'iofix-deferred iofix-hz iofix-sleep iofix-signal', 'pad-a', '', '', False, 1),
    ('pad-a-wb-deferred', 'iofix-deferred', 'pad-a-wb', '', '', False, 1),
    ('pre-late-wake', 'netcmd_units', 'pre', '', '', False, 1),
    ('pre-existing-epoll', 'wb_policy auth notify', 'pre', 'epoll', '', False, 1),
    ('pre-notify-uring', 'notify', 'pre', 'uring', '', False, 0),
    ('pre-fused-uring', 'auth notify', 'pre', 'uring', '1s', False, 1),
    ('pre-fused-epoll', 'auth notify', 'pre', 'epoll', '1s', False, 1),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(group):
    name, jobs, arm, engine, mode, force, expected = group
    binary = ROOT / ('build/tomokv' if arm == 'post' else 'build/tomokv-' + arm)
    cwd = ROOT / 'build/iofix/pre-source' if arm == 'pre' else ROOT
    env = dict(os.environ)
    for key in ('IOFIX_ENGINE', 'IOFIX_MODE', 'IOFIX_FORCE_ENGINE'):
        env.pop(key, None)
    env.update(GATE_ONLY_JOBS=jobs, IOFIX_BINARY=str(binary),
               REDIS74_ROOT='/home/user/Projects/redis',
               GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
               IOFIX_LAUNCH_LOG=str(OUT / (name + '-launches.jsonl')))
    if engine: env['IOFIX_ENGINE'] = engine
    if mode: env['IOFIX_MODE'] = mode
    if force: env['IOFIX_FORCE_ENGINE'] = '1'
    candidate = binary if name == 'final-native-checks' else OUT / 'gate_candidate.py'
    command = ['tests/gate.sh', 'full', '--server-cores', '80-87',
               '--load-cores', '88-95', '--ports', '19800-19899',
               '--candidate-binary', str(candidate)]
    before = digest(binary)
    logfile = OUT / (name + '.log')
    assert not logfile.exists(), 'retain old evidence; choose a new group name before rerunning'
    print('START', name, before, flush=True)
    with logfile.open('w') as log:
        rc = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    assert before == digest(binary), 'candidate changed during the proof'
    match = re.search(r'^  artifacts: (.+)$', logfile.read_text(), re.M)
    receipt = dict(name=name, command=command, cwd=str(cwd), binary=str(binary),
                   sha256=before, jobs=jobs.split(), engine=engine, mode=mode,
                   force_engine=force, expected_exit=expected, actual_exit=rc,
                   run=match[1] if match else None)
    (OUT / (name + '-receipt.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    if match:
        subprocess.run([sys.executable, str(OUT / 'retain_proof.py'), match[1],
                        str(OUT / 'proof' / name), '--binary', str(binary), '--archive',
                        '--note', name + ': gate-owned jobs; exact command/environment in group receipt'], check=True)
    print('DONE', name, 'exit', rc, flush=True)
    assert rc == expected, (name, rc, expected)


if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(80, 96)), 'use taskset -c 80-95'
    selected = sys.argv[1:]
    assert selected and set(selected) <= {g[0] for g in GROUPS}, 'name explicit proof groups'
    for group in GROUPS:
        if group[0] in selected:
            run(group)
