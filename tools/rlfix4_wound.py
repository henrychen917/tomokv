#!/usr/bin/env python3
"""Reproduce registered AT4-WOUND-1 against unchanged PRE and POST source.

This is a deterministic correctness diagnostic, not a merit measurement. It
copies the registered fixture verbatim, uses each revision's production objects,
and retains a nonzero defect exit rather than turning it into a gate pass.
"""
import concurrent.futures, hashlib, json, os, shlex, shutil, subprocess, tarfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/rlfix4'
WORK = ROOT / 'build/rlfix4/wound'
os.sched_setaffinity(0, set(range(32, 48)))
WORK.mkdir(parents=True, exist_ok=True)
deadline = time.monotonic() + 3600
while not (DOC / 'jobs/final2-txnnx-post-4.json').exists():
    if time.monotonic() >= deadline:
        raise SystemExit('live controls did not complete')
    time.sleep(10)
pre = WORK / 'pre-source'
pre.mkdir(exist_ok=True)
if not (pre / 'build/tomokv').exists():
    archive = pre / 'source.tar'
    with archive.open('wb') as f:
        subprocess.run(['git', 'archive', 'a214652ec'], cwd=ROOT, stdout=f, check=True)
    with tarfile.open(archive) as f:
        f.extractall(pre, filter='data')
    archive.unlink()
shutil.copy2(ROOT / 'tests/rlfix4_wound_window.cc', pre / 'tests/rlfix4_wound_window.cc')
if subprocess.run(['make', '-q', 'all'], cwd=pre).returncode:
    with (DOC / 'wound-pre-build.log').open('a') as out:
        subprocess.run(['make', '-j16', 'all'], cwd=pre, stdout=out, stderr=subprocess.STDOUT, check=True)

def fixture(case):
    arm, namespace = case
    source = pre if arm == 'pre' else ROOT
    target = WORK / f'{arm}-{namespace}'
    recipe = subprocess.check_output(['make', '-n', '-B', 'build/atomic-survivors-unit'], cwd=source, text=True)
    # Join make's continued command, then reuse its exact compiler/link inputs.
    recipe = recipe.replace('\\\n', ' ')
    command = next(shlex.split(line) for line in recipe.splitlines()
                   if 'tests/atomic_survivors_unit.cc' in line and ' -o build/atomic-survivors-unit ' in line)
    command[command.index('tests/atomic_survivors_unit.cc')] = 'tests/rlfix4_wound_window.cc'
    command[command.index('-o') + 1] = str(target)
    if namespace == 'db0':
        command.insert(1, '-DTOMO_SINGLE_DATABASE=1')
        command.insert(2, '-Dtomo=tomo_db0')
        # Match the existing DB0 xshard-unit link policy: the fixture supplies
        # DB0 xshard; normal xshard and scripting are also needed because the
        # shared Lua runtime is defined only in normal scripting.o.
        objects = [x for x in command if x.startswith('build/src/') and x.endswith('.o')]
        first = command.index(objects[0])
        command[first:first] = [x.replace('build/src/', 'build/db0/src/') for x in objects]
        command.insert(command.index('-o'), 'build/src/cmd/xshard.o')
    log = DOC / f'wound-{arm}-{namespace}-build.log'
    if log.exists():
        prior = log.with_name(log.stem + '.first-attempt.log')
        if not prior.exists():
            log.rename(prior)
    with log.open('w') as out:
        subprocess.run(command, cwd=source, stdout=out, stderr=subprocess.STDOUT, check=True)
    results = []
    for mode in ('1s', '2s'):
        run = subprocess.run([str(target), mode], cwd=source, capture_output=True, text=True)
        results.append(dict(mode=mode, exit=run.returncode, output=run.stdout + run.stderr))
    result = dict(arm=arm, namespace=namespace, command=command, source=str(source),
                sha256=hashlib.sha256(target.read_bytes()).hexdigest(), results=results)
    (DOC / f'wound-{arm}-{namespace}.json').write_text(json.dumps(result, indent=2) + '\n')
    return result

with concurrent.futures.ThreadPoolExecutor(4) as pool:
    results = list(pool.map(fixture, [(a, n) for a in ('pre', 'post') for n in ('normal', 'db0')]))
(DOC / 'wound-diagnostic.json').write_text(json.dumps(results, indent=2) + '\n')
for r in results:
    for run in r['results']:
        print(r['arm'], r['namespace'], run['mode'], 'exit', run['exit'], run['output'].strip(), flush=True)
# Do not mask the defect status. It is an expected reproduction, not a pass.
raise SystemExit(1 if any(run['exit'] for r in results for run in r['results']) else 0)
