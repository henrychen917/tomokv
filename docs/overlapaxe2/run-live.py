#!/usr/bin/env python3
"""Requested merge proofs only: owned short boots, no gate or benchmark."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from _gate_process import info, server

OUTPUT = ROOT / 'build/overlapaxe2/live'
BINARY = ROOT / 'build/tomokv'
PORT = 18489
assert set(os.sched_getaffinity(0)) <= set(range(112, 128))
OUTPUT.mkdir(parents=True, exist_ok=False)
rows = []
for databases in (1, 16):
    for mode in ('1s', '2s'):
        for read_local in (0, 1):
            for atomic in ((0, 1) if databases == 16 else (1,)):
                label = f'db{databases}-{mode}-rl{read_local}-a{atomic}'
                directory = OUTPUT / label
                args = ['--databases', databases, '--shards', 16,
                        '--thread-mode', mode, '--read-local', read_local,
                        '--reorder', 0, '--atomic', atomic, '--net-io', 'uring',
                        '--key-lb', 1, '--client-lb', 1, '--flip-auto', 0]
                if mode == '2s':
                    args += ['--ratio', '6:2']
                row = dict(label=label, databases=databases, mode=mode,
                           read_local=read_local, atomic=atomic, tests=[])
                with server(BINARY, '112-119', PORT, directory, args) as (conn, process):
                    fields = info(conn, 'SERVER')
                    assert fields['process_id'] == str(process.pid)
                    for key, value in [('thread_mode', mode), ('shards', 16),
                                       ('read_local', read_local), ('atomic', atomic),
                                       ('reorder', 0)]:
                        assert fields[key] == str(value), (key, fields.get(key), value)
                    assert conn.must('CONFIG', 'GET', 'databases') == [b'databases', str(databases).encode()]
                    if mode == '2s':
                        assert fields['io_threads'] == '6' and fields['ex_threads'] == '2'
                    else:
                        assert fields['fused_threads'] == '8'
                    if read_local:
                        assert int(fields['read_local_active_threads']) > 0
                    assert all(key not in fields for key in
                               ('overlap', 'overlap_enabled', 'overlap_schedule',
                                'overlap_passes', 'overlap_interleaved_passes'))
                    assert conn.must('PING') == b'PONG'
                    assert conn.must('SET', 'overlapaxe2:a', 'first') == b'OK'
                    assert conn.must('GET', 'overlapaxe2:a') == b'first'
                    assert conn.must('MSET', 'overlapaxe2:a', 'second',
                                     'overlapaxe2:b', 'third') == b'OK'
                    assert conn.must('MGET', 'overlapaxe2:a', 'overlapaxe2:b') == [b'second', b'third']
                    row['tests'].append('PING, SET/GET, MSET/MGET')
                    scripts = []
                    if databases == 16:
                        scripts.append(('aclkeys_wake_state.py', []))
                    if mode == '2s' and read_local == 0:
                        scripts.append(('knobs.py', ['uring', str(atomic)]))
                    for script, extra in scripts:
                        argv = [sys.executable, str(ROOT / 'tests' / script),
                                '127.0.0.1', str(PORT), *extra]
                        result = subprocess.run(argv, cwd=ROOT, text=True,
                                                capture_output=True, timeout=90)
                        (directory / (script + '.log')).write_text(result.stdout + result.stderr)
                        assert result.returncode == 0, (label, script, result.stdout, result.stderr)
                        row['tests'].append(script)
                    row['pid'] = process.pid
                    (directory / 'info.json').write_text(json.dumps(fields, indent=2) + '\n')
                row['exit'] = json.loads((directory / 'exit.json').read_text())
                assert row['exit']['returncode'] == 0 and not row['exit']['forced_kill']
                listeners = subprocess.check_output(['ss', '-H', '-ltnp', f'sport = :{PORT}'], text=True)
                assert not listeners.strip(), listeners
                row['port_closed'] = True
                rows.append(row)
                (OUTPUT / 'results.json').write_text(json.dumps(dict(
                    binary=str(BINARY), sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),
                    driver_cpus='112-127', server_cpus='112-119', shards=16,
                    split_ratio='6:2', rows=rows), indent=2) + '\n')
                print('PASS', label, ', '.join(row['tests']), 'clean shutdown; port closed', flush=True)
