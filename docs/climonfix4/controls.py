#!/usr/bin/env python3
"""Named Tcl controls through gate.sh's partial-job interface; no benchmarks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'build/climonfix4'
DOC = ROOT / 'docs/climonfix4'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def mutant():
    dest = BUILD / 'count-mutant'
    dest.mkdir(exist_ok=True)
    source = dest / 'source'
    shutil.copytree(ROOT / 'src', source / 'src', dirs_exist_ok=True)
    path = source / 'src/cmd/climon.cc'
    before = path.read_text()
    assert before.count('srv_->blocking_client_parked();') == 1
    text = before.replace('srv_->blocking_client_parked();', '/* planted missing pause count */')
    text = text.replace('srv_->blocking_client_unparked();', '/* paired count removal */')
    path.write_text(text)
    recipe = subprocess.check_output(['make', '-n', '-W', 'build/src/main.o', 'all'], cwd=ROOT, text=True)
    link = shlex.split(next(s for s in recipe.splitlines() if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
    commands = []
    for namespace in ('normal', 'db0'):
        obj = dest / (namespace + '.o')
        cmd = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread', '-DTOMO_JEMALLOC', '-I' + str(ROOT)]
        if namespace == 'db0':
            cmd += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        cmd += ['-c', str(path), '-o', str(obj)]
        commands.append(cmd)
        with (dest / (namespace + '-build.log')).open('w') as log:
            subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        original = 'build/' + ('db0/' if namespace == 'db0' else '') + 'src/cmd/climon.o'
        assert original in link
        link[link.index(original)] = str(obj)
    binary = dest / 'tomokv'
    link[link.index('-o') + 1] = str(binary)
    with (dest / 'link.log').open('w') as log:
        subprocess.run(link, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    save(DOC / 'count-mutant.json', dict(root='PAUSE-BLOCKED-COUNT',
         change='Remove pause count increments and paired decrements; retain all other POST behavior',
         source_sha256=sha(path), source_before_sha256=hashlib.sha256(before.encode()).hexdigest(),
         binary=str(binary), binary_sha256=sha(binary), compile=commands, link=link))
    shutil.rmtree(source)


def run(roots, arms):
    witnesses = json.loads((DOC / 'tcl-controls/witnesses.json').read_text())
    results = []
    output = BUILD / 'tcl-controls'
    output.mkdir(exist_ok=True)
    for root in roots or witnesses:
        unit, name = witnesses[root]
        for arm in arms:
            binary = BUILD / ('tomokv-POST' if arm == 'POST' else 'tomokv-PRE')
            if arm == 'negative' and root == 'PAUSE-BLOCKED-COUNT':
                binary = BUILD / 'count-mutant/tomokv'
            logfile = output / (root + '-' + arm + '.log')
            cmd = ['bash', 'tests/gate.sh', 'quick', '--server-cores', '16-23', '--load-cores', '24-31',
                   '--server-smt', '', '--load-smt', '', '--ports', '20220-20229',
                   '--candidate-binary', str(binary)]
            env = dict(os.environ, REDIS74_ROOT='/home/user/Projects/redis', GATE_ONLY_JOBS='redis_tcl',
                       GATE_TCL_MANIFEST=str(DOC / 'tcl-controls' / (root + '.json')))
            with logfile.open('w') as log:
                rc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
            match = re.search(r'artifacts: (.+)', logfile.read_text())
            assert match, logfile
            run_dir = Path(match[1])
            row = dict(root=root, arm=arm, binary=str(binary), sha256=sha(binary),
                       command=cmd, manifest=env['GATE_TCL_MANIFEST'], rc=rc, run=str(run_dir), modes={})
            for mode in ('2s', '1s'):
                path = run_dir / 'jobs/redis_tcl' / ('redis-tcl-' + mode) / unit / 'result.json'
                result = json.loads(path.read_text())
                events = [e for e in result['events'] if e['test'] == name + ' in tests/' + unit + '.tcl']
                statuses = [e['status'] for e in events]
                assert 'testing' in statuses, (root, arm, mode, 'witness did not start')
                if arm == 'POST':
                    assert rc == 0 and statuses.count('ok') == 1 and 'err' not in statuses, (root, mode, result)
                else:
                    assert rc != 0 and 'ok' not in statuses and ('err' in statuses or result['error']), (root, mode, result)
                row['modes'][mode] = dict(result=str(path), statuses=statuses, error=result['error'])
            results.append(row)
            save(DOC / 'tcl-control-results.json', results)
            print(root, arm, 'verified in both modes', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--build-mutant', action='store_true')
    p.add_argument('--root', action='append')
    p.add_argument('--arms', default='POST,negative')
    args = p.parse_args()
    if args.build_mutant:
        mutant()
    else:
        run(args.root, args.arms.split(','))
