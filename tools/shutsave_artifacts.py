#!/usr/bin/env python3
"""Build/run serverless shutdown controls against frozen PRE and POST objects."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('build/shutsave'))
    parser.add_argument('--cores', default='112-119')
    parser.add_argument('--keys', type=int, default=131072)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    logs = args.root / 'controls'
    logs.mkdir(parents=True, exist_ok=True)
    source_object = args.root / 'POST/tests/shutsave_unit.o'
    pre_sha = sha(args.root / 'PRE/tomokv')
    # Obtain the production object order without building/recompiling the PRE tree.
    objects = subprocess.check_output([
        'make', '--no-print-directory', '-s', 'BUILD_ROOT=' + str(args.root / 'PRE'),
        '--eval=shutsave-list:;@echo $(SHUTDOWN_UNIT_OBJ)', 'shutsave-list'], text=True).split()
    command = ['g++', '-pthread', str(source_object), *objects, '-o',
               str(args.root / 'PRE/shutsave-unit'), '-ljemalloc', '-luring', '-lssl', '-lcrypto',
               '-lm', '-Wl,--wrap=clock_gettime']
    subprocess.run(command, check=True)
    assert sha(args.root / 'PRE/tomokv') == pre_sha, 'frozen PRE was changed'
    rows = []

    def run(arm, selection, fatal=None):
        name = arm + '-' + '-'.join(map(str, selection))
        command = ['taskset', '-c', args.cores, str(args.root / arm / 'shutsave-unit'),
                   *map(str, selection)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=120)
        (logs / (name + '.log')).write_text(result.stdout)
        passed = ((result.returncode == -6 and fatal in result.stdout) if fatal else
                  (result.returncode == 0 and 'PASS' in result.stdout))
        rows.append(dict(name=name, command=command, returncode=result.returncode,
                         expected_fatal=fatal, passed=passed))
        (logs / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(name + ': ' + ('PASS' if passed else 'FAIL'), flush=True)
        assert passed, result.stdout

    for selection in ('join', 'rewrite', 'retire', 'boundary'):
        run('POST', [selection])
    for selection, fatal in (
            ('hang', 'fatal: database worker shutdown timeout elapsed_ms=11000'),
            ('hung-worker', 'fatal: database worker shutdown timeout elapsed_ms=3000'),
            ('retire-hang', 'fatal: database retire acknowledgement timeout elapsed_ms=11000')):
        run('POST', [selection], fatal)
    run('PRE', ['join'], 'fatal: database worker shutdown timeout elapsed_ms=3000')
    run('PRE', ['rewrite'], 'fatal: database worker shutdown timeout elapsed_ms=3000')
    run('PRE', ['retire'], 'fatal: database retire acknowledgement timeout elapsed_ms=3000')
    run('PRE', ['save', '2s', 'sigterm', args.keys], 'fatal: database worker shutdown timeout')
    for mode in ('2s', '1s'):
        for action in ('sigterm', 'nosave', 'shutdown'):
            for save in ('save', 'bgsave'):
                run('POST', [save, mode, action, args.keys])
            run('POST', ['save', mode, action, args.keys, 4, 'uring'])
        for phase in (1, 2, 3):
            run('POST', ['save', mode, 'nosave', 32, phase])
    print('shutsave serverless controls: %d/%d PASS; value_bytes=%d' %
          (len(rows), len(rows), args.keys * 4096))


if __name__ == '__main__':
    main()
