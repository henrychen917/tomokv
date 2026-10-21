#!/usr/bin/env python3
"""Run lane correctness proofs only; never starts a throughput workload or gate iteration."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from compat2_support import save, server


def main():
    p = argparse.ArgumentParser()
    p.add_argument('part', choices=('rows', 'differ', 'tls', 'units', 'selftest', 'identity'))
    p.add_argument('--label', default='')
    a = p.parse_args()
    out = ROOT / 'docs/compat2' / (a.part + a.label)
    out.mkdir(parents=True, exist_ok=False)
    results = []

    def run(name, command, env=None, cores='73-79', timeout=None):
        argv = ['taskset', '-c', cores, *map(str, command)]
        with (out / (name + '.log')).open('w') as log:
            try:
                rc = subprocess.run(argv, cwd=ROOT, env={**os.environ, **(env or {})},
                                    stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
            except subprocess.TimeoutExpired:
                rc = 124
        results.append(dict(name=name, argv=argv, env=env, returncode=rc))
        save(out / 'results.json', results)
        print(name, rc, flush=True)
        return rc

    binary = ROOT / 'build/tomokv'
    pre = ROOT / 'build/compat2/pre-source/build/tomokv'
    oracle = '/home/user/Projects/redis74/src/redis-server'
    certs = ROOT / 'build/compat2/certs'
    if a.part == 'rows':
        for arm, image in (('pre', pre), ('post', binary)):
            for case in ('autharity', 'expire_notify', 'ktls_lifetime'):
                for mode in ('1s', '2s'):
                    for engine in ('epoll', 'uring'):
                        name = f'{arm}-{case}-{mode}-{engine}'
                        extra = (['--oracle', oracle, '--oracle-cores', '72'] if case == 'autharity'
                                 else ['--certs', certs] if case == 'ktls_lifetime' else [])
                        run(name, ['python3', f'tests/{case}.py', '--binary', image,
                            '--output', out / name, '--mode', mode, '--engine', engine,
                            '--cores', '64-71', '--port', '26800', *extra])
        run('post-ktls-window', ['build/ktls-lifetime-unit'], cores='64-71')
        run('pre-ktls-window', ['build/compat2/ktls-lifetime-pre'], cores='64-71')
    elif a.part == 'differ':
        for engine in ('uring', 'epoll'):
            wrapper = ROOT / 'build/compat2' / f'{engine}-server'
            wrapper.write_text(f'#!/bin/bash\nexec {binary} --net-io {engine} "$@"\n')
            wrapper.chmod(0o755)
            for geometry in ('split', 'armed-fused'):
                name = f'{engine}-{geometry}'
                run(name, ['bash', 'tests/differ_gate.sh', wrapper, '26810', '26811', '64-71', '6:2'],
                    env=dict(REDIS74_ROOT='/home/user/Projects/redis74', GATE_LOAD_CORES='73-79',
                        GATE_DIFFER_ORACLE_CORES='72', GATE_DIFFER_GEOMETRY=geometry,
                        GATE_DIFFER_OUT=str(out / name), GATE_DIFFER_HISTORY=str(out / 'history'),
                        GATE_RUN_ID='compat2-' + name))
    elif a.part == 'tls':
        for mode in ('1s', '2s'):
            for engine in ('epoll', 'uring'):
                for auth in ('yes', 'optional', 'default', 'fallback'):
                    name = f'{mode}-{engine}-{auth}'
                    modearg = auth if auth in ('yes', 'optional') else 'no'
                    extra = ['--tls-port', '26821', '--tls-cert-file', str(certs / 'server.crt'),
                        '--tls-key-file', str(certs / 'server.key'), '--tls-ca-cert-file',
                        str(certs / 'ca.crt'), '--tls-auth-clients', modearg]
                    if auth == 'fallback':
                        extra += ['--tls-protocols', 'TLSv1.2 TLSv1.3', '--tls-ciphers',
                                  'ECDHE-RSA-AES256-SHA384', '--tls-ciphersuites',
                                  'TLS_AES_256_GCM_SHA384', '--tls-prefer-server-ciphers', 'yes']
                    with server(binary, out / (name + '-server'), 26820, '64-71', mode, engine, extra):
                        options = ['--full', '--expect-ktls', 'no' if auth == 'fallback' else 'yes'] \
                            if auth in ('default', 'fallback') else []
                        run(name, ['python3', 'tests/tls.py', '127.0.0.1', '26821', certs,
                                   modearg, '--plain-port', '26820', *options])
                        if auth == 'optional':
                            for kind in ('tx', 'userspace'):
                                run(name + '-' + kind, ['build/ktls-keyupdate', '127.0.0.1', '26821', kind])
        run('keyupdate-unit', ['build/ktls-keyupdate-unit'])
    elif a.part == 'units':
        body = (ROOT / 'tests/gate.sh').read_text().split('job_production_units(){', 1)[1].split('\n}', 1)[0]
        targets = re.findall(r'build/[\w-]+', body.split('>"$TMPDIR/build.log"', 1)[0])
        assert targets and len(targets) == len(set(targets))
        save(out / 'targets.json', targets)
        run('production', ['make', '-k', '-j16', 'all', *targets], cores='64-79')
        for target in ['all', *targets]:
            run('fresh-' + target.replace('/', '-'), ['make', '-q', target], cores='64-79')
        run('mdbqsbr-live-arms', ['make', '-j16', 'mdbqsbr-live-arms'], cores='64-79')
        for name, flags in [('park', '-DTOMO_MDBQSBR_LIVE_PARK'),
                            ('no-wake', '-DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE')]:
            run('fresh-mdbqsbr-' + name, ['make', '-q', f'BUILD_ROOT=build/mdbqsbr2-{name}',
                'CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread ' + flags,
                'all'], cores='64-79')
    elif a.part == 'selftest':
        run('gates-test', ['python3', 'tests/gates_test.py'], env=dict(GATE_TEST_PORT='26899',
            REDIS74_ROOT='/home/user/Projects/redis74'), timeout=1800)
    else:
        before = pre.parent
        run('hot', ['python3', 'tools/lbstall_artifacts.py', 'compare', before, ROOT / 'build',
                    out / 'hot.json'], cores='64-79')
        run('bodies', ['python3', 'tools/ccfix_audit.py', before, ROOT / 'build', out / 'bodies'], cores='64-79')
        run('linked', ['python3', 'docs/deadswitch/linked_bytes.py', pre, binary,
                       out / 'linked.json'], cores='64-79')


if __name__ == '__main__':
    main()
