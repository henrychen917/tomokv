#!/usr/bin/env python3
"""Run the final frozen-arm proof; differential jobs own the lane CPUs serially."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/storefix5'
assert os.sched_getaffinity(0) <= set(range(16, 24))
os.environ['LC_ALL'] = 'C'
receipt = {'waiting_for': 'production-units-release.json', 'stages': []}
OUTPUT = DOC / 'final-proof.json'


def save():
    temporary = OUTPUT.with_suffix('.tmp')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(OUTPUT)


def cleanup():
    output = DOC / 'data-cleanup.json'
    rows = json.loads(output.read_text())
    for done in (ROOT / 'build').glob('gate-run.*/jobs/*/done'):
        for path in done.parent.rglob('*'):
            if path.is_file() and path.suffix in ('.rdb', '.tomo', '.aof', '.manifest'):
                rows.append({'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size})
                path.unlink()
    output.write_text(json.dumps(rows, indent=2) + '\n')


def start(label, argv, extra=None, expected=(0,)):
    row = dict(log=label + '.log', argv=argv, environment=extra or {},
               expected=list(expected), started=time.time())
    receipt['stages'].append(row)
    save()
    log = (DOC / row['log']).open('w')
    process = subprocess.Popen(argv, cwd=ROOT, env=dict(os.environ, **(extra or {})),
                               stdout=log, stderr=subprocess.STDOUT)
    return row, process, log


def finish(job):
    row, process, log = job
    row.update(exit=process.wait(), finished=time.time())
    log.close()
    save()
    cleanup()
    print(row['log'], row['exit'], flush=True)
    return row


def run(label, argv, extra=None, expected=(0,)):
    row = finish(start(label, argv, extra, expected))
    assert row['exit'] in expected, row
    return row


def gate(label, jobs, ports, extra=None, expected=(0,)):
    env = dict(GATE_ONLY_JOBS=jobs, GATE_PROOF_NO_RATES='1',
               REDIS74_ROOT='/home/user/Projects/redis', **(extra or {}))
    return start(label, ['tests/gate.sh', 'iteration', '--server-cores', '16-23',
        '--load-cores', '16-23', '--load-smt', '', '--ports', ports,
        '--shared-correctness-cpus', '--candidate-binary', 'build/storefix5/POST'], env, expected)


def sections(path):
    blob = path.read_bytes()
    offset = struct.unpack_from('<Q', blob, 40)[0]
    width, count, names_index = struct.unpack_from('<HHH', blob, 58)
    headers = [struct.unpack_from('<IIQQQQIIQQ', blob, offset + i * width) for i in range(count)]
    names_header = headers[names_index]
    names = blob[names_header[4]:names_header[4] + names_header[5]]
    result = {}
    for header in headers:
        name = names[header[0]:].split(b'\0', 1)[0].decode()
        if name in ('.text', '.rlfence'):
            data = blob[header[4]:header[4] + header[5]]
            result[name] = dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    return dict(sha256=hashlib.sha256(blob).hexdigest(), sections=result)


save()
while True:
    try:
        builds = json.loads((DOC / 'production-units-release.json').read_text())
    except json.JSONDecodeError:
        time.sleep(2)
        continue
    assert all(r['exit'] == 0 for r in builds['builds'] + builds['freshness']), builds
    if len(builds['builds']) == 4 and len(builds['freshness']) == 59:
        break
    time.sleep(2)
receipt['waiting_for'] = None
identity = dict(POST=sections(ROOT / 'build/storefix5/POST'), fresh=sections(ROOT / 'build/tomokv'))
identity['code_equal'] = identity['POST']['sections'] == identity['fresh']['sections']
(DOC / 'release-code-identity.json').write_text(json.dumps(identity, indent=2) + '\n')
assert identity['code_equal'], identity
save()

run('append-final', ['python3', 'tools/storefix5_append.py', 'post-retirement', '--source', '.',
                    '--objects', 'build/storefix5/arms/retirement168000'])
for directory in ('curves-release', 'memory/release'):
    src = DOC / directory
    dest = src.with_name(src.name + '-before-retirement')
    if not dest.exists():
        shutil.copytree(src, dest)
for mode in ('1s', '2s'):
    for arm, binary in [('pre', 'build/storefix5/PRE'), ('post', 'build/storefix5/POST')]:
        output = DOC / 'curves-release' / f'{arm}-{mode}.json'
        run(f'curve-final-{arm}-{mode}', ['python3', 'tools/storefix5_checks.py', '--binary', binary,
            '--mode', mode, '--port', '21600', '--cases', 'randomkey_footprint,append',
            '--output', str(output)], expected=(1,) if arm == 'pre' else (0,))
run('curve-final-redis', ['python3', 'tools/storefix5_checks.py', '--binary',
    '/home/user/Projects/redis/src/redis-server', '--redis', '--port', '21600',
    '--cases', 'randomkey_footprint,append', '--output', str(DOC / 'curves-release/redis-2s.json')])
run('memory-final', ['python3', 'tools/storefix5_memory.py', 'release',
                    '--binary', 'build/storefix5/POST', '--port', '21630'])
for mode in ('1s', '2s'):
    output = DOC / f'pad-final-{mode}.json'
    run(f'pad-final-{mode}', ['python3', 'tools/storefix5_checks.py', '--binary', 'build/storefix5/PAD-A',
        '--mode', mode, '--port', '21600', '--cases', 'randomkey,idle', '--output', str(output)],
        expected=(1,))
    cases = json.loads(output.read_text())['cases']
    assert set(cases) == {'randomkey', 'idle'} and all(not r['passed'] for r in cases.values()), cases
run('gates-test-final', ['python3', 'tests/gates_test.py'], {'GATE_TEST_PORT': '21699'})
run('rlfix3-info-build-final', ['make', '-j8', 'build/rlfix3-info-unit', 'build/rlfix3-info-db0-unit',
    'CXXFLAGS=-std=c++20 -O2 -g -gz=zlib -Wall -Wextra -march=native -pthread'])
finish(gate('gate-quiet-final', 'asan_batteries zc splitlocal_units',
            '21610-21612'))

live = ('storefix5 maxmemrace datafix1_geo datafix1_spop datafix1_lists datafix1_locale '
        'datafix1_bitfield datafix1_randscan datafix1_hexpire redis_tcl datafix2_notouch '
        'datafix2_encoding datafix2_subkeys datafix2_watch datafix2_idle feature-split-0 '
        'feature-split-1 feature-armed-0 feature-armed-1 snapshot-epoll snapshot-uring '
        'aof-epoll aof-uring readonly atomic_batteries release_batteries ' +
        ' '.join(f'evict-{section}-{mode}-{atomic}' for section in ('lfu', 'lruclock')
                 for mode in ('split', 'armed') for atomic in (0, 1)))
native = ('storage_units atomic_units aof_frame aoforder readonly fused-0 fused-1 '
          'txn_group_fused txn_group_split rlfix3_info ' +
          ' '.join(f'multidb-{mode}-{rl}-{at}' for mode in ('1s', '2s') for rl in (0, 1) for at in (0, 1)) +
          ' ' + ' '.join('at412-' + name for name in
              ('T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8', 'T9', 'T10', 'T11a', 'T11b',
               'T12', 'T13', 'T14', 'T15', 'T16', 'owner')))
live_job = gate('gate-live-final', live, '21640-21642',
                {'GATE_TCL_MANIFEST': str(ROOT / 'build/storefix5/tcl-required.json')})
finish(live_job)
native_job = gate('gate-native-final', native, '21690-21692',
    {'GATE_RLFIX3_INFO_UNIT': str(ROOT / 'build/rlfix3-info-unit'),
     'GATE_RLFIX3_INFO_DB0_UNIT': str(ROOT / 'build/rlfix3-info-db0-unit')})
finish(native_job)

pairing = []
for name in ('txnorder-wake-unit', 'txnorder-episodes', 'txnorder-episodes-debug',
             'txnorder-watch-unit', 'txnorder-watch-db0-unit'):
    source = ROOT / 'build' / name
    destination = (ROOT / 'build/storefix5/POST').resolve().parent / name
    assert source.is_file() and os.access(source, os.X_OK), source
    if not destination.exists():
        destination.symlink_to(source)
    assert destination.resolve() == source
    pairing.append(dict(unit=name, source=str(source), paired=str(destination),
                        sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
(DOC / 'txnorder-unit-pairing.json').write_text(json.dumps(dict(units=pairing), indent=2) + '\n')

extra = ('rldbg rlcache bplus rlfix3_zc atomfix5_watch atomfix5_accounting snapfix_shutdown '
         'snapfix_bgsave_script snapfix_bgsave_exec snapfix2_tables persistfix2_lastsave '
         'persistfix2_shutdown persistfix2_commands persistfix2_errors persistfmt persistfmt_aof_error '
         'dump_restore notify_aof rootcompat-stringlimit config_unit core_units wait_units '
         'flushfix2 flushfix2_units flushfix3 flushfix3_units aclkeys_wake list_namespace dbdefault '
         'atomic_floor execfair exec1s txnorder_fifo txnorder_fifo_live txnorder_chain txnorder_index '
         'txnorder_wound txnorder_wake txnorder2 txnorder-fused-0 txnorder-fused-1 txnorder-split-0 '
         'txnorder-split-1 script_bounds scriptfix scriptfix2 lualibs serverfix_waitaof rootcore-waitaof '
         'infofix_compat-loadaof persistfix_units')
extra_job = gate('gate-extra-final', extra, '21620-21622', expected=(1,))
finish(extra_job)
fused_job = gate('gate-fused-final', 'atomic_batteries release_batteries snapshot-epoll snapshot-uring '
                 'aof-epoll aof-uring', '21650-21652', {'GATE_TXN_FUSED': '1'})
finish(fused_job)
finish(gate('gate-tcl-unfiltered-final', 'redis_tcl', '21620-21622',
    {'GATE_TCL_ONLY_FILES': 'unit/keyspace,unit/maxmemory,unit/type/string'}, expected=(1,)))
for engine, ports in [('uring', '21660-21662'), ('epoll', '21670-21672')]:
    finish(gate(f'gate-differ-{engine}-final', 'differ-split differ-armed', ports,
                {'GATE_DIFFER_NET_IO': engine}))
receipt['complete'] = True
save()
raise SystemExit(any(r['exit'] not in r['expected'] for r in receipt['stages']))
