#!/usr/bin/env python3
"""Re-run the round-5 auditors' own tests for CD5.3/CD5.4/CD5.5/CD5.6/TM5.1 on one binary.

The scripts are copied unchanged from /home/user/Projects/round5-read/tests/{cmd-data,testmap}
into build/txnfix4/auditor/, with only the lane's placement substituted: ports 232NN -> 214NN
(testmap 2380N -> 2148N), server CPUs 61-68 (1s --place ifid@61..68), clients on 69-73, and the
binary under test from TXNFIX4_TARGET. Receipts (the scripts' own JSONL) and a summary of each
script's own summary lines go to docs/txnfix4/auditor-reruns/<label>/.
Usage: txnfix4_auditors.py --binary B --label L [--tests-root DIR] [--only ID,...]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('/home/user/Projects/round5-read/tests')
WORK = ROOT / 'build/txnfix4/auditor'
OUT = ROOT / 'docs/txnfix4/auditor-reruns'
CMD_DATA = ['audit.py', 'ls_common.py', 'ls-maxmem.py', 'ls-maxmem2.py', 'ls-watch.py',
            'ls-watch2.py', 'zs-audit.py', 'zs-mpop-watch.py', 'zs-crash-repro.py',
            'hash-snapwin.py']
# Z-T6: the auditor's 19 scenario receipts (runs/zs-crash-<scenario>-<mode>-a<atomic>-rl0[-aofN]).
Z_T6 = [('lmpop-watch-then-tracking', '1s', 1, 0), ('mpop-nowatch-tracking', '1s', 1, 0),
        ('mpop-watch-disconnect', '1s', 1, 0), ('mpop-watch-noexec-tracking', '1s', 1, 0),
        ('mpop-watch-plainread-other-conn', '1s', 1, 0), ('mpop-watch-then-plain', '1s', 1, 0),
        ('mpop-watch-then-tracking', '1s', 0, 0), ('mpop-watch-then-tracking', '1s', 1, 0),
        ('mpop-watch-then-tracking', '1s', 1, 1), ('mpop-watch-then-tracking', '2s', 0, 0),
        ('mpop-watch-then-tracking', '2s', 1, 0), ('mpop-watch-tracking-noflush', '1s', 1, 0),
        ('mpop-watch-tracking-otherkey', '1s', 1, 0), ('mpop-watch-tracking-resp2', '1s', 1, 0),
        ('mpop-watch-tracking-resp2', '1s', 1, 1), ('mpop-watch-twice', '1s', 1, 0),
        ('notify-mpop', '1s', 1, 0), ('tracking-only', '1s', 1, 0),
        ('watch-zadd-tracking', '1s', 1, 0)]


def retarget(text, name):
    text = re.sub(r'\b232(\d\d)\b', r'214\1', text)
    text = re.sub(r'range\((80|96|104), ?(88|104|112)\)', 'range(61, 69)', text)
    if name == 'audit.py':
        text = text.replace("TARGET='/home/user/Projects/bench-bins/tomokv-headline-105c5818cc'",
                            "TARGET=os.environ['TXNFIX4_TARGET']")
        text = text.replace("CORES='80-111'", "CORES=os.environ.get('TXNFIX4_CORES','61-68')")
    if name == 'live_audit.py':
        text = text.replace("ROOT=Path('/home/user/Projects/cx-r5-testmap')",
                            "ROOT=Path(os.environ['TXNFIX4_TESTS_ROOT'])")
        text = text.replace("BIN=Path('/home/user/Projects/bench-bins/tomokv-headline-105c5818cc')",
                            "BIN=Path(os.environ['TXNFIX4_TARGET'])")
        text = text.replace("SERVER_CPUS='80-87'; CLIENT_CPUS='88-95'",
                            "SERVER_CPUS='61-68'; CLIENT_CPUS='69-73'")
        text = re.sub(r'\b2380(\d)\b', r'2148\1', text)
        text = text.replace('set(range(80,112))', 'set(range(61,74))')
        text = text.replace('pin audit clients inside 80-111', 'pin audit clients inside 61-73')
    return text


def stage():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    for name in CMD_DATA:
        (WORK / name).write_text(retarget((SOURCE / 'cmd-data' / name).read_text(), name))
    (WORK / 'live_audit.py').write_text(
        retarget((SOURCE / 'testmap/live_audit.py').read_text(), 'live_audit.py'))
    for name in CMD_DATA + ['live_audit.py']:
        text = (WORK / name).read_text()
        assert not re.search(r'\b23[2-8]\d\d\b', text), name
        assert 'bench-bins/tomokv-headline' not in text, name


def plan():
    rows = []
    for mode in ('2s', '1s'):
        for atomic in (0, 1):
            rows.append(('L-T3', f'{mode}-a{atomic}',
                         ['ls-maxmem.py', '--mode', mode, '--atomic', str(atomic)]))
    for policy in ('noeviction', 'volatile-lru', 'allkeys-lru'):
        rows.append(('L-T3b', policy, ['ls-maxmem2.py', '--policy', policy]))
    for mode, atomic, local in (('1s', 0, 0), ('1s', 1, 0), ('2s', 0, 0), ('2s', 1, 0),
                                ('2s', 1, 1)):
        rows.append(('L-T4', f'{mode}-a{atomic}-rl{local}',
                     ['ls-watch.py', '--mode', mode, '--atomic', str(atomic), '--local',
                      str(local)]))
    for mode in ('2s', '1s'):
        for atomic in (1, 0):
            rows.append(('L-T5', f'{mode}-a{atomic}',
                         ['ls-watch2.py', '--mode', mode, '--atomic', str(atomic)]))
    for mode, atomic, local in (('1s', 0, 0), ('1s', 1, 0), ('2s', 1, 1)):
        rows.append(('Z-T5', f'{mode}-a{atomic}-rl{local}',
                     ['zs-mpop-watch.py', '--mode', mode, '--atomic', str(atomic), '--local',
                      str(local)]))
    for scenario, mode, atomic, aof in Z_T6:
        rows.append(('Z-T6', f'{scenario}-{mode}-a{atomic}-aof{aof}',
                     ['zs-crash-repro.py', '--mode', mode, '--atomic', str(atomic),
                      '--scenario', scenario, '--aof', str(aof)]))
    for mode in ('1s', '2s'):
        for run in (1, 2, 3):
            rows.append(('G-X1', f'{mode}-run{run}',
                         ['zs-crash-repro.py', '--mode', mode, '--atomic', '1', '--scenario',
                          'mpop-watch-then-tracking']))
    rows += [('H-T6', '1s', ['hash-snapwin.py', '--mode', '1s']),
             ('H-T6', '2s', ['hash-snapwin.py', '--mode', '2s']),
             ('H-T6', '1s-a1-192', ['hash-snapwin.py', '--mode', '1s', '--atomic', '1',
                                    '--bigmb', '192'])]
    rows.append(('T1', 'execfix', ['live_audit.py', 'T1']))
    return rows


def summaries(path):
    found = []
    for line in path.read_text(errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and ('summary' in row or 'test' in row):
            found.append(row)
    return found


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--tests-root', type=Path, default=ROOT,
                   help='tree whose tests/execfix.py T1 imports (PRE tree for the control)')
    p.add_argument('--only', default='')
    a = p.parse_args()
    stage()
    out = OUT / a.label
    out.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, a.only.split(',')))
    env = dict(os.environ, LC_ALL='C', PYTHONDONTWRITEBYTECODE='1',
               TXNFIX4_TARGET=str(a.binary.resolve()), TXNFIX4_CORES='61-68',
               TXNFIX4_TESTS_ROOT=str(a.tests_root.resolve()))
    record = dict(label=a.label, binary=str(a.binary.resolve()),
                  binary_sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest(),
                  tests_root=str(a.tests_root.resolve()), rows=[])
    for test, variant, argv in plan():
        if only and test not in only:
            continue
        name = f'{test}-{variant}'
        receipt = out / f'{name}.jsonl'
        command = ['taskset', '-c', '69-73', 'python3', argv[0], *argv[1:]]
        if test == 'T1':
            command += ['--output', str(out / 'T1')]
        started = time.monotonic()
        with receipt.open('w') as log:
            try:
                done = subprocess.run(command, cwd=WORK, env=env, stdout=log,
                                      stderr=subprocess.STDOUT, timeout=1800)
                code = done.returncode
            except subprocess.TimeoutExpired:
                code = 'timeout'
        row = dict(test=test, variant=variant, command=command, exit=code,
                   seconds=round(time.monotonic() - started, 1), summaries=summaries(receipt))
        if test == 'T1' and (out / 'T1/T1.json').exists():
            t1 = json.loads((out / 'T1/T1.json').read_text())
            row['summaries'] = [dict(test='T1', error=t1.get('error'),
                                     returncode=t1.get('result', {}).get('returncode'),
                                     same_owner_pair=t1.get('result', {}).get('before'))]
        record['rows'].append(row)
        print(json.dumps({k: row[k] for k in ('test', 'variant', 'exit', 'seconds',
                                              'summaries')}, default=str)[:600], flush=True)
        (out / 'summary.json').write_text(json.dumps(record, indent=2, default=str) + '\n')


if __name__ == '__main__':
    main()
