#!/usr/bin/env python3
"""Check the investigation's receipts without starting a server or workload."""
import gzip
import hashlib
import json
from pathlib import Path
import socket
import subprocess


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


subprocess.run(['git', 'diff', '--exit-code', 'bfc13903f', '--',
                'src', 'Makefile', 'tests'], check=True)
rows = json.loads(Path('docs/at15c/reproduction.json').read_text())
assert len(rows) == 6 and all(row['matrix_finished'] for row in rows)
assert all(row['suite_legs'] == 246 for row in rows)
assert [row['edgetime'] for row in rows] == ['FAIL', 'FAIL', 'FAIL', 'PASS', 'PASS', 'PASS']
assert [(row['operations']['1526']['delta_ms'], row['operations']['2910']['delta_ms'])
        for row in rows] == [(-5, -5), (-1, -2), (-6, -7), (0, 0), (0, 0), (-1, 0)]

manifest = json.loads(Path('docs/at15c/artifacts.json').read_text())
for item in manifest:
    path = Path(item['path'])
    assert path.stat().st_size == item['bytes'], path
    assert sha(path) == item['sha256'], path

harness = sha('tests/differ.py')
trace_count = reply_count = 0
for path in sorted(Path('docs/at15c/receipts').glob('*/edgetime-*.json.gz')):
    data = json.loads(gzip.decompress(path.read_bytes()))
    assert data['harness_sha256'] == harness, path
    operations = data['operations']
    assert len(operations) == 4426, path
    commands = [operations[index][0] for index in (1526, 2910)]
    assert commands == (['PEXPIRETIME'] * 2 if data.get('absolute_control', False)
                        else ['PTTL'] * 2), path
    for side in ('target', 'oracle'):
        replies = [event for event in data['events']
                   if event['kind'] == 'reply' and event['side'] == side and event['op'] is not None]
        assert [event['op'] for event in replies] == list(range(4426)), path
        sends = [event for event in data['events']
                 if event['kind'] == 'send' and event['side'] == side and event['batch'] is not None]
        assert [event['batch'] for event in sends] == list(range(0, 4426, 64)), path
        assert all(event['before'][0] <= event['after'][0] for event in replies + sends), path
        reply_count += len(replies)
    trace_count += 1

arms = {}
for line in Path('docs/at15c/final-SHA256SUMS').read_text().splitlines():
    digest, name = line.split()
    assert sha(name) == digest, name
    arms[name] = digest
assert sha('build/at15b-post') == arms['build/tomokv']

profile = json.loads(Path('docs/at15c/profile-windows/profile-compiler-post/summary.json').read_text())
window = next(row for row in profile['windows'] if row['op'] == 1526)
assert len(window['workers_off_cpu_at_send']) == 8
assert abs(window['all_workers_off_cpu_at_send_ms'] - 2.910048) < .000001
assert window['samples'] == 2 and sum(window['leaf_symbols'].values()) == 2

owned = set()
groups = set()
for path in Path('build/at15c').glob('*/pids.json'):
    owned.update(json.loads(path.read_text()).values())
for path in Path('build/at15c').glob('*/compiler-control.json'):
    groups.update(row['pid'] for row in json.loads(path.read_text())['commands'])
assert not any(Path(f'/proc/{pid}').exists() for pid in owned), 'owned server still alive'
processes = subprocess.check_output(['ps', '-eo', 'pid=,pgid='], text=True)
assert not any(int(line.split()[1]) in groups for line in processes.splitlines()), 'compiler group alive'
for port in (17899, 17900):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', port))

receipt = dict(full_replays=len(rows), complete_suite_legs=sum(row['suite_legs'] for row in rows),
               verified_artifacts=len(manifest), verified_traces=trace_count,
               timestamped_replies=reply_count, unchanged_harness_sha256=harness,
               production_makefile_tests_unchanged_since='bfc13903f', arms=arms,
               stopped_server_pids=sorted(owned), stopped_compiler_groups=sorted(groups),
               ports_free=[17899, 17900], compiler_window_all_workers_off_cpu_ms=2.910048)
Path('docs/at15c/verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
