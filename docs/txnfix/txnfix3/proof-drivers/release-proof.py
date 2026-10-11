import pathlib, time
while not pathlib.Path('build/txnfix3/START-RELEASE-PROOF').exists(): time.sleep(.5)
import hashlib, json, os, pathlib, shutil, signal, subprocess, sys, time

sys.path.insert(0, 'tests/txnfix_audit')
import resp

root = pathlib.Path('docs/txnfix/txnfix3/release-proof').resolve()
root.mkdir(exist_ok=True)
data = pathlib.Path('build/txnfix3/release-proof-data').resolve()
data.mkdir(exist_ok=True)
binary = pathlib.Path('build/tomokv').resolve()
pre = pathlib.Path('build/txnfix2/pre/tomokv').resolve()
sha = hashlib.sha256(binary.read_bytes()).hexdigest()
rows = []

def check(name, cmd, server=None, timeout=180, env=None, arm='post'):
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    command = ['taskset', '-c', '121-127', *map(str, cmd)]
    started = time.monotonic()
    with (path / 'test.log').open('w') as out:
        child = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT,
                                 env=dict(os.environ, **(env or {})), start_new_session=True)
        try:
            rc = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try: child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
            rc = 124
    row = dict(name=name, command=command, exit_code=rc,
               seconds=time.monotonic()-started, arm=arm,
               sha256=sha if arm == 'post' else hashlib.sha256(pre.read_bytes()).hexdigest())
    if server: row['server'] = server.argv
    if env: row['env'] = env
    rows.append(row)
    (root / 'runs.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(name, rc, flush=True)
    return rc

def live(name, mode, atomic, databases, command, extra=(), timeout=180):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    resp._options.mode, resp._options.atomic, resp._options.databases = mode, str(atomic), databases
    server = resp.Server(22601, ['--enable-debug-command', 'yes', '--read-local',
                               '1' if mode == '1s' else '0', *extra],
                         binary=str(binary), log=str(folder / 'server.log'))
    try:
        return check(name, command, server, timeout=timeout)
    finally:
        code = server.stop()
        (folder / 'shutdown.json').write_text(json.dumps(dict(exit_code=code)) + '\n')

# Wait for this lane's already-running compile; do not race correctness deadlines
# with our own compiler jobs. No system-wide process or other lane is touched.
while not pathlib.Path('docs/txnfix/txnfix3/release-build/freshness.json').exists():
    time.sleep(.5)
print('build complete; starting serial focused correctness proof', flush=True)

for name, cmd in [
    ('gates-test', ['python3', 'tests/gates_test.py']),
    ('ledger', ['python3', 'tests/gate_ledger_fixture.py']),
    ('infofields', ['python3', 'tests/infofields_test.py']),
    ('shell-syntax', ['bash', '-n', 'tests/gate.sh']),
]:
    check(name, cmd, timeout=1800)

for mode in ('2s', '1s'):
    for atomic in (0, 1):
        for databases in (1, 16):
            label = f'txniso-{mode}-a{atomic}-db{databases}'
            live(label, mode, atomic, databases,
                 ['python3', 'tests/txniso.py', '127.0.0.1', '22601', '--mode', mode], timeout=180)
        live(f'nx-{mode}-a{atomic}', mode, atomic, 16,
             ['python3', 'tests/txn_nx.py', '127.0.0.1', '22601'], timeout=180)
        if atomic:
            live(f'nx-bare-{mode}', mode, atomic, 16,
                 ['python3', 'tests/txn_nx.py', '127.0.0.1', '22601', '--bare'], timeout=180)
        aof_dir = data / f'txniso-aof-{mode}-a{atomic}'
        aof_dir.mkdir(exist_ok=True)
        live(f'txniso-aof-{mode}-a{atomic}', mode, atomic, 16,
             ['python3', 'tests/txniso.py', '127.0.0.1', '22601', '--mode', mode, '--only', 'V4'],
             extra=['--appendonly', 'yes', '--appendfsync', 'no', '--dir', str(aof_dir)])
    live(f'movers-{mode}-a0', mode, 0, 16,
         ['python3', 'tests/txn_movers.py', '127.0.0.1', '22601'], timeout=240)
    live(f'G5-{mode}-a0', mode, 1, 16,
         ['python3', 'tests/txngroup.py', '127.0.0.1', '22601', '--mode', mode, '--only', 'G5'], timeout=180)
    for databases in (1, 16):
        live(f'txngroup-{mode}-db{databases}', mode, 1, databases,
             ['python3', 'tests/txngroup.py', '127.0.0.1', '22601', '--mode', mode], timeout=240)
    aof_dir = data / f'txngroup-aof-{mode}'
    aof_dir.mkdir(exist_ok=True)
    live(f'txngroup-aof-{mode}', mode, 1, 16,
         ['python3', 'tests/txngroup.py', '127.0.0.1', '22601', '--mode', mode, '--only', 'AOF'],
         extra=['--appendonly', 'yes', '--appendfsync', 'no', '--dir', str(aof_dir)])

for old in json.loads(pathlib.Path('docs/txnfix/differ-stage-a/runs.json').read_text()):
    geometry = old['geometry']
    out = data / ('differ-' + geometry)
    env = dict(old['env'], GATE_DIFFER_OUT=str(out))
    check('differ-' + geometry, old['command'][3:], timeout=420, env=env)
    dest = root / ('differ-' + geometry) / 'receipts'
    dest.mkdir(exist_ok=True)
    for path in out.rglob('*'):
        if path.is_file() and path.suffix in ('.json', '.log', '.txt', '.tsv', '.md'):
            target = dest / path.relative_to(out)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

for arm, target in [('pre', pre), ('post', binary)]:
    wrapper = data / (arm + '-armed-server')
    wrapper.write_text('#!/bin/bash\nexec ' + str(target) + ' --read-local 1 "$@"\n')
    wrapper.chmod(0o755)
    for old in json.loads(pathlib.Path('docs/txnfix/original-audits/runs.json').read_text()):
        cmd = old['command'][3:]
        name = pathlib.Path(cmd[1]).stem + '-' + old['mode'] + '-a' + old['atomic']
        folder = root / ('original-' + arm) / name
        folder.mkdir(parents=True, exist_ok=True)
        cmd[cmd.index('--output') + 1] = str(folder)
        cmd[cmd.index('--binary') + 1] = str(wrapper if old['mode'] == '1s' else target)
        check('original-' + arm + '/' + name, cmd, arm=arm, timeout=180)

for old in json.loads(pathlib.Path('docs/txnfix/txnfix2/stage-b-pre/runs.json').read_text()):
    cmd = old['command'][3:]
    folder = root / 'stage-b' / old['name']
    folder.mkdir(parents=True, exist_ok=True)
    cmd[cmd.index('--binary') + 1] = str(data / 'post-armed-server' if '-1s-' in old['name'] else binary)
    cmd[cmd.index('--output') + 1] = str(folder)
    check('stage-b/' + old['name'], cmd, timeout=240)

for mode in ('2s', '1s'):
    label = 't10_msetnx_hold-' + mode + '-a0'
    folder = root / 'stage-b' / label
    folder.mkdir(parents=True, exist_ok=True)
    check('stage-b/' + label, ['python3', 'tests/txnfix_audit/t10_msetnx_hold.py',
          '--binary', str(data / 'post-armed-server' if mode == '1s' else binary),
          '--port', '22601', '--cores', '112-119', '--mode', mode, '--atomic', '0',
          '--databases', '16', '--output', str(folder)], timeout=240)

for mode in ('2s', '1s'):
    for old in json.loads(pathlib.Path('docs/txnfix/regression-stage-a/runs.json').read_text())[:18]:
        cmd = old['command'][3:]
        name = pathlib.Path(cmd[1]).stem
        if name == 'atomic_plain': cmd += ['--atomic', '1']
        live(f'broad-{mode}/{name}', mode, 1, 16, cmd, timeout=240)
    live(f'broad-{mode}/atomic_plain-a0', mode, 0, 16,
         ['python3', 'tests/atomic_plain.py', '127.0.0.1', '22601', '--atomic', '0'])
    check('watchlive-' + mode, ['tests/watchlive_gate.sh', '22605', '112-119', '6',
                              str(pathlib.Path('build/txnfix3/watchlive-' + mode).resolve())], timeout=480)

for case in ('txn_group', 'txn_admission', 'txn_intents', 'txn_help'):
    check('unit-' + case, ['taskset', '-c', '112-127', 'build/atomic-survivors-unit', case], timeout=240)

assert hashlib.sha256(binary.read_bytes()).hexdigest() == sha
(root / 'COMPLETE.json').write_text(json.dumps(dict(sha256=sha, rows=len(rows),
    passed=sum(row['exit_code'] == 0 for row in rows)), indent=2) + '\n')
