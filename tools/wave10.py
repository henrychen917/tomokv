#!/usr/bin/env python3
"""Wave10 compile-only artifacts and bounded correctness orchestration.

Every child inherits CPUs 64-95. No performance job or full iteration is run.
Historical lane evidence is read-only; new receipts live under docs/wave10.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/wave10'
DOC = ROOT / 'docs/wave10'
PRE = BUILD / 'pre-source'
HEADLINE = '393d6ceb129d8c99dffd70959d6a19267c525fe0'
sys.path.insert(0, str(ROOT / 'docs/wave9'))
sys.path.insert(0, str(ROOT / 'tools'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(command, log, **kwargs):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as stream:
        return subprocess.run(command, cwd=ROOT, stdout=stream,
                              stderr=subprocess.STDOUT, check=True, **kwargs)


def references():
    import identity
    identity.OUT = BUILD / 'identity'
    identity.REFS = {
        'headline': '/home/user/Projects/bench-bins/tomokv-headline-393d6ceb1',
        'snapfix2': '/home/user/Projects/bins/snapfix2-post-dd169c2f',
        'blockfix3': '/home/user/Projects/bins/blockfix3-post-e18acab2',
        'scriptfix2': '/home/user/Projects/bins/scriptfix2-post-cb5dbeae',
        'exec1sd': '/home/user/Projects/bins/exec1sd-post-4111f5c6',
        'pubtrackfix': '/home/user/Projects/bins/pubtrackfix-post-faef9b90',
        'infofix': '/home/user/Projects/bins/infofix-post-28faa60c',
        'rlfix4': '/home/user/Projects/bins/rlfix4-post-5a903fd8',
    }
    for lane in ('snapfix2', 'scriptfix2', 'rlfix4'):
        identity.REFS['baseline_' + lane] = '/home/user/Projects/bench-bins/tomokv-headline-a214652ec'
    return identity


def build_pre():
    if not PRE.exists():
        PRE.mkdir(parents=True)
        with subprocess.Popen(['git', 'archive', HEADLINE, 'src', 'third_party',
                               'Makefile', 'tools', 'tests'], cwd=ROOT,
                              stdout=subprocess.PIPE) as process:
            with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                archive.extractall(PRE, filter='data')
            assert process.wait() == 0
        (PRE / 'SOURCE-COMMIT').write_text(HEADLINE + '\n')
    assert (PRE / 'SOURCE-COMMIT').read_text().strip() == HEADLINE
    run(['make', '-C', str(PRE), '-j32', 'all'], BUILD / 'pre-build.log')
    subprocess.run(['make', '-C', str(PRE), '-q', 'all'], check=True)
    save(DOC / 'pre-build.json', dict(commit=HEADLINE, binary=str(PRE / 'build/tomokv'),
                                    sha256=sha(PRE / 'build/tomokv')))


def scopes(arm, label):
    os.environ['EXEC1S_CPUS'] = '64-95'
    import exec1s_scope as scope
    import rlfix4_native as native
    from rlfix4_scope import assembly_ranges
    scope.OUT = DOC / 'instructions' / label
    scope.BUILD = BUILD / 'scopes'
    scope.OUT.mkdir(parents=True, exist_ok=True)
    scope.BUILD.mkdir(parents=True, exist_ok=True)
    source = PRE if arm == 'pre' else ROOT
    scope.ARMS[label] = source, source / 'build'
    scope.FIXTURE = ROOT / 'tests/wave10_scope.cc'
    work = ROOT / 'build/rlfix4/commands'
    work.mkdir(parents=True, exist_ok=True)
    run(['g++', '-O2', '-g', '-std=c++20', 'tools/rlfix4_trace.cc',
         '-o', str(ROOT / 'build/rlfix4/trace')], BUILD / 'scope-tracer-build.log')
    prepared = {}
    for namespace in ('normal', 'db0'):
        scope.build(label, namespace)
        binary = scope.BUILD / (label + '-' + namespace) / 'probe'
        symbols = []
        for line in subprocess.check_output(['nm', '-S', '--defined-only', str(binary)], text=True).splitlines():
            fields = line.split()
            if len(fields) == 4 and fields[2] in ('t', 'T', 'w', 'W'):
                symbols.append([int(fields[0], 16), int(fields[0], 16) + int(fields[1], 16), fields[3]])
        names = subprocess.check_output(['c++filt'], input='\n'.join(r[2] for r in symbols), text=True).splitlines()
        prefix = 'tomo::' if namespace == 'normal' else 'tomo_db0::'
        ranges = [r + [name] for r, name in zip(symbols, names)
                  if prefix in name and 'CoreConcurrencyTest::' not in name]
        ranges += assembly_ranges(binary, prefix)
        prepared[namespace] = binary, ranges
    cases = [(label, ns, command, mode, batch, atomic, -1)
             for ns in ('normal', 'db0') for mode in ('1s', '2s')
             for command in ('GET', 'SET', 'INCR', 'MGET', 'MSET') for batch in (1, 32)
             for atomic in ((0, 1) if command == 'MSET' else (1,))]
    cases += [(label, ns, command, mode, batch, atomic, -1)
              for ns in ('normal', 'db0') for mode in ('1s', '2s')
              for command in ('EXEC-same', 'EXEC-cross') for batch in (1, 2, 4) for atomic in (0, 1)]
    cases += [(label, ns, command, mode, 1, atomic, -1)
              for ns in ('normal', 'db0') for mode in ('1s', '2s')
              for command in ('EVAL-single', 'EVAL-cross') for atomic in (0, 1)]
    cases += [(label, ns, 'READLOCAL-GET', '1s', batch, 1, -1)
              for ns in ('normal', 'db0') for batch in (1, 32)]
    def count(case):
        binary, ranges = prepared[case[1]]
        output = scope.OUT / ('-'.join(map(str, case)) + '.json')
        return native.trace(binary, ranges, case, output)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(count, cases))
    save(scope.OUT / 'counts.json', dict(arm=arm, label=label,
         production_sha256=sha(source / 'build/tomokv'), fixture_sha256=sha(scope.FIXTURE),
         tracer_sha256=sha(ROOT / 'build/rlfix4/trace'), rows=rows))


def main():
    assert os.sched_getaffinity(0) <= set(range(64, 96)), 'wave10 CPU boundary'
    BUILD.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('pre', 'identity', 'budget', 'scopes'))
    parser.add_argument('rest', nargs='*')
    args = parser.parse_args()
    if args.phase == 'pre':
        build_pre()
    elif args.phase == 'scopes':
        scopes(*args.rest)
    elif args.phase == 'identity':
        identity = references()
        # Resolve the actual long-double/SIMD literals and checked switch
        # tables also used to bind counted probes to their production bodies.
        # Keep a separate cache: compile-trial receipts used the older strict
        # normalizer and must remain reproducible.
        from wave10_normalize import install
        install(identity.audit)
        identity.OUT = BUILD / 'identity-resolved'
        for label in ('headline-final', 'post-final'):
            counted = DOC / 'instructions' / label / 'counts.json'
            if counted.exists():
                for row in json.loads(counted.read_text())['rows']:
                    identity.COUNTED_HOT.update(identity.audit.canonical(name)
                                               for name in row['functions'])
        sys.argv = ['identity', str(ROOT / 'build/tomokv'),
                    'docs/wave10/' + (args.rest[0] if args.rest else 'identity')]
        identity.main()
    elif args.phase == 'budget':
        identity = references()
        import budgets
        budgets.identity = identity
        budgets.PRE = PRE
        suffix = os.getenv('WAVE10_BUDGET_ROUND', '')
        budgets.OUT = BUILD / ('budgets' + suffix)
        budgets.DOC = DOC / ('budgets' + suffix)
        sys.argv = ['budgets', args.rest[0]]
        budgets.main()


if __name__ == '__main__':
    main()
