import hashlib, json, os, pathlib, shutil, signal, subprocess, sys, time

sys.path.insert(0, 'tests/txnfix_audit')
import resp

root = pathlib.Path('docs/txnfix/txnfix3/certified-barrier-control/proof').resolve()
root.mkdir(parents=True, exist_ok=True)
data = pathlib.Path('build/txnfix3/certified-control-data').resolve()
data.mkdir(exist_ok=True)
binary = pathlib.Path('build/txnfix3/certified-barrier-off/tomokv').resolve()
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


for mode in ('2s', '1s'):
    for test in ('multirace', 'multires'):
        live(test + '-' + mode, mode, 1, 16,
             ['python3', 'tests/' + test + '.py', '127.0.0.1', '22601'], timeout=180)

(root/'COMPLETE.json').write_text(json.dumps(rows,indent=2)+'\n')
