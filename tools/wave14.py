#!/usr/bin/env python3
"""Wave14 selected gate jobs, source inventories, and linked identity receipts."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/wave14'
DOC = ROOT / 'docs/wave14'
PRE = BUILD / 'pre-source'
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests'), str(ROOT / 'docs/wave9')]

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')

def references():
    import identity
    identity.OUT = BUILD / 'identity-cache'
    identity.REFS = {'headline': '/home/user/Projects/bench-bins/tomokv-headline-105c5818cc'}
    for lane, digest in [('rootcore', 'd8cdb1df'), ('blockfix4', 'cb7a70bb'),
                         ('rootcompat', 'f3511f86'), ('clientcompat', '346d035c'),
                         ('execfifo3', '6f9af8cd')]:
        identity.REFS[lane] = f'/home/user/Projects/bins/{lane}-post-{digest}'
        base = 'e32b04a44' if lane == 'execfifo3' else '7d2f8a205'
        identity.REFS['baseline_' + lane] = f'/home/user/Projects/bench-bins/tomokv-headline-{base}'
    from wave12_normalize import install
    install(identity.audit)
    return identity

def integration_reasons(directory, binary):
    """Name integration edits separately from unchanged identity verdicts."""
    ready = DOC / 'r7-final-ready.json'
    if not ready.exists() or sha(binary) != json.loads(ready.read_text())['sha256']:
        return
    r7 = {r['name'] for r in json.loads(
        (DOC/'r7-final-release-differences.json').read_text())['changed']}
    path = directory / 'changed-bodies.json'
    rows = json.loads(path.read_text())
    annotations = []
    for row in rows:
        reason = None
        if '::SnapshotManager::start(' in row['name']:
            reason = ('Integration 2d32493948: capture FUNCTION libraries after AOF '
                      'increment rotation; includes the corresponding cold error paths.')
        elif row['name'] in r7:
            reason = ('Integration a0e4d122e8: regenerate the R7 owner with clientcompat\'s '
                      'ExDrain-only freeze; its inline/caller propagation changes this envelope.')
        if reason:
            row.setdefault('lane_comparison_reason', row['reason'])
            row['reason'] = reason + ' Lane comparison: ' + row['lane_comparison_reason']
            annotations.append(dict(name=row['name'], reason=reason))
    assert len(annotations) == 10
    save(path, rows)
    save(directory/'integration-annotations.json', annotations)
    lines = ['# Linked body differences', '',
        'Strict gate instruction/address normalization; local clone multiplicity retained. Identity is a proxy.', '',
        '| Function | Headline sizes | Merged sizes | Reason |', '|---|---|---|---|']
    for row in rows:
        lines.append('| `'+row['name'].replace('|', '\\|')+'` | '+str(row['headline_sizes'])+
            ' | '+str(row['post_sizes'])+' | '+row['reason'].replace('|', '\\|')+' |')
    (directory/'changed-bodies.md').write_text('\n'.join(lines)+'\n')

def inventory():
    from gate_ledger_fixture import source_labels
    gate = (ROOT / 'tests/gate.sh').read_text()
    first = gate.index('\nstart_workers\n')
    quick = gate.index('\nif [ "$TIER" = quick ];', first)
    end = gate.index('\n# Every worker has reaped', quick)
    labels = source_labels(gate)
    qlabels = source_labels(gate[:quick] + gate[end:])
    original = subprocess.check_output(['git', 'show', '105c5818cc:tests/gate.sh'], text=True)
    before = source_labels(original)
    fixture = ROOT / 'tests/fixtures/nullrefresh-ledger-labels.json'
    data = json.loads(fixture.read_text())
    result = dict(quick=len(qlabels), full=len(labels),
        quick_exit_line=gate[:quick].count('\n') + 1,
        additions=list((Counter(labels) - Counter(before)).elements()),
        removals=list((Counter(before) - Counter(labels)).elements()),
        collectors=[dict(line=i, declaration=line.strip())
                    for i, line in enumerate(gate.splitlines(), 1)
                    if line.startswith('collect_job ') or 'collect_job "' in line],
        missing_fixture=list((Counter(labels)-Counter(data['labels'])).elements()),
        extra_fixture=list((Counter(data['labels'])-Counter(labels)).elements()),
        gate_sha256=sha(ROOT / 'tests/gate.sh'))
    save(DOC / 'row-inventory.json', result)
    print(json.dumps(result, indent=2))

def jobs(a):
    import blockfix2_receipts as receipts
    out = DOC / 'jobs'
    out.mkdir(parents=True, exist_ok=True)
    assert not (out / (a.tag + '.json')).exists(), 'never overwrite an attempt'
    names = a.jobs or Path(a.jobs_file).read_text().strip()
    assert names and not {'flip_saturated', 'atomic_floor'} & set(names.split())
    binary = a.binary.resolve()
    env = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
        GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis/src/redis-server',
        GATE_PROOF_NO_RATES='1', GATE_NET_IO=a.engine, GATE_PROOF_NET_IO=a.engine,
        GATE_DIFFER_NET_IO=a.engine, GATE_ONLY_JOBS=names,
        GATE_LEDGER=str(out / a.tag), CXX='g++ -gz=zlib', CC='cc -gz=zlib')
    if a.fused:
        env['GATE_TXN_FUSED'] = '1'
    command = ['taskset', '-c', '0-31', 'tests/gate.sh', 'full',
        '--server-cores', a.server_cores, '--load-cores', a.load_cores,
        '--server-smt', '', '--load-smt', '', '--ports', a.ports,
        '--candidate-binary', str(binary)]
    digest = sha(binary)
    save(out / (a.tag + '-started.json'), dict(command=command, binary_sha256=digest,
        env={k:v for k,v in env.items() if k.startswith(('GATE_', 'WAVE14_', 'BLOCKFIX4_')) or
             k in ('LC_ALL', 'REDIS74_ROOT', 'CXX', 'CC')}))
    with (out / (a.tag + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    matches = re.findall(r'^  artifacts: (.+)$', (out / (a.tag + '.log')).read_text(), re.M)
    assert len(matches) == 1, matches
    run = Path(matches[0]).resolve()
    assert run.parent == ROOT / 'build' and run.name.startswith('gate-run.')
    old = receipts.selected
    receipts.selected = lambda p, root: old(p, root) or p.suffix == '.jsonl'
    record = receipts.collect(a.tag, run, out)
    record.update(command=command, binary_sha256=digest, exit_code=result.returncode,
                  run_directory=str(run), engine=a.engine, fused=a.fused)
    assert sha(binary) == digest, 'candidate changed during proof'
    save(out / (a.tag + '.json'), record)
    failures = sum(job['failed'] for job in record['jobs'])
    print(a.tag, result.returncode, sum(job['passed'] for job in record['jobs']), failures, flush=True)
    return bool(result.returncode or failures)

def landing_selftest(a):
    """Exercise final landing counts in a disposable committed-source copy."""
    import blockfix2_receipts as receipts
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    source = BUILD / a.tag
    source.mkdir(exist_ok=False)
    archive = subprocess.Popen(['git', 'archive', revision], stdout=subprocess.PIPE)
    subprocess.run(['tar', '-x', '-C', str(source)], stdin=archive.stdout, check=True)
    archive.stdout.close()
    assert archive.wait() == 0
    gate = source / 'tests/gate.sh'
    before = sha(gate)
    text = gate.read_text()
    for name, old, new in [('EXPECT_QUICK', 1046, 1090), ('EXPECT_FULL', 1063, 1107)]:
        text, count = re.subn(r'(?m)^'+name+'='+str(old)+r'\b', name+'='+str(new), text)
        assert count == 1
    gate.write_text(text)
    env = dict(os.environ, LC_ALL='C', GATE_ONLY_JOBS='abba_selftest',
        GATE_PROOF_NO_RATES='1', GATE_LEDGER=str(source/'ledger'),
        REDIS74_ROOT='/home/user/Projects/redis', CXX='g++ -gz=zlib', CC='cc -gz=zlib')
    command = ['taskset', '-c', '0-31', 'tests/gate.sh', 'full',
        '--server-cores', '16-23', '--load-cores', '0-7', '--server-smt', '',
        '--load-smt', '', '--ports', '20093-20095', '--candidate-binary', str(a.binary.resolve())]
    logfile = source / 'selftest.log'
    with logfile.open('w') as log:
        result = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
    paths = re.findall(r'^  artifacts: (.+)$', logfile.read_text(), re.M)
    assert len(paths) == 1, 'gate did not create a job receipt'
    record = receipts.collect(a.tag, Path(paths[0]), DOC/'jobs')
    record.update(revision=revision, command=command, exit_code=result.returncode,
        binary_sha256=sha(a.binary), gate_before_sha256=before,
        gate_after_sha256=sha(gate), checked_in_gate_sha256=sha(ROOT/'tests/gate.sh'),
        expected_quick=1090, expected_full=1107)
    save(DOC/'jobs'/(a.tag+'.json'), record)
    assert sha(ROOT/'tests/gate.sh') == before, 'checked-in EXPECT source changed'
    assert sha(Path(record['archive'])) == record['archive_sha256']
    if result.returncode == 0:
        shutil.rmtree(source)
    print(a.tag, result.returncode, flush=True)
    return result.returncode

def main():
    assert os.sched_getaffinity(0) <= set(range(32)), 'wave14 CPU boundary'
    os.environ['LC_ALL'] = 'C'
    BUILD.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='phase', required=True)
    sub.add_parser('inventory')
    ip = sub.add_parser('identity')
    ip.add_argument('--binary', type=Path, default=ROOT/'build/tomokv')
    ip.add_argument('--tag', default='identity')
    jp = sub.add_parser('jobs')
    jp.add_argument('--tag', required=True)
    jp.add_argument('--engine', choices=('uring','epoll'), default='uring')
    jp.add_argument('--jobs', default='')
    jp.add_argument('--jobs-file')
    jp.add_argument('--binary', type=Path, default=ROOT/'build/tomokv')
    jp.add_argument('--fused', action='store_true')
    jp.add_argument('--server-cores', default='0-23')
    jp.add_argument('--load-cores', default='24-31')
    jp.add_argument('--ports', default='20000-20089')
    lp = sub.add_parser('landing-selftest')
    lp.add_argument('--tag', required=True)
    lp.add_argument('--binary', type=Path, default=BUILD/'post-r7/tomokv')
    a = p.parse_args()
    if a.phase == 'inventory': inventory()
    elif a.phase == 'identity':
        identity = references()
        sys.argv = ['identity', str(a.binary), str(DOC/a.tag)]
        identity.main()
        integration_reasons(DOC/a.tag, a.binary)
    elif a.phase == 'jobs': raise SystemExit(jobs(a))
    elif a.phase == 'landing-selftest': raise SystemExit(landing_selftest(a))

if __name__ == '__main__': main()
