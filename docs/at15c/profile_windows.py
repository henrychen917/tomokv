#!/usr/bin/env python3
"""Extract mono-clock POST profile stacks and switches at the two query windows."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(sys.argv[1])
out = Path('docs/at15c/profile-windows') / root.name
out.mkdir(parents=True, exist_ok=True)
pid = json.loads((root / 'pids.json').read_text())['target']
results = json.loads((root / 'results.json').read_text())
tids = {int(tid) for result in results for tid in result['target_affinity']}
command = json.loads((root / 'perf-command.json').read_text())
assert command[command.index('--clockid') + 1] == 'mono'
windows = []
for path in sorted(root.glob('edgetime-*.json')):
    data = json.loads(path.read_text())
    for op in (1526, 2910):
        batch = op // 64 * 64
        send = next(e for e in data['events']
                    if e['kind'] == 'send' and e['side'] == 'target' and e['batch'] == batch)
        reply = next(e for e in data['events']
                     if e['kind'] == 'reply' and e['side'] == 'target' and e['op'] == op)
        windows.append(dict(name=path.stem + '-' + str(op), op=op,
                            start=send['before'][0], end=reply['after'][0],
                            samples=0, leaf_symbols=Counter(), switches=[], text=[]))

header = re.compile(r'^\s*(.*?)\s+(\d+)(?:/(\d+))?\s+\[(\d+)\]\s+(\d+)\.(\d+):\s*(.*)')
switches = defaultdict(list)
samples = Counter()
selected = []
sample_block = []
sample_windows = []


def flush():
    if not sample_block:
        return
    for window in sample_windows:
        window['text'].extend(sample_block)
        window['samples'] += 1
        if len(sample_block) > 1:
            window['leaf_symbols'][sample_block[1].strip()] += 1


perf_command = ['perf', 'script', '-i', str(root / 'perf.data'), '--ns', '--show-switch-events',
                '-F', 'comm,pid,tid,cpu,time,event,ip,sym,dso']
with (out / 'perf-script.err').open('w') as error:
    proc = subprocess.Popen(perf_command, stdout=subprocess.PIPE, stderr=error, text=True)
    for line in proc.stdout:
        match = header.match(line)
        if not match:
            if sample_block:
                sample_block.append(line)
            continue
        flush()
        sample_block, sample_windows = [], []
        comm, procid, tid, cpu, sec, fraction, event = match.groups()
        tid = int(tid or procid)
        ns = int(sec) * 10**9 + int(fraction.ljust(9, '0'))
        if 'cycles:u' in event:
            samples[comm] += 1
            if int(procid) == pid or tid in tids:
                sample_windows = [w for w in windows if w['start'] <= ns <= w['end']]
                if sample_windows:
                    sample_block = [line]
        elif 'PERF_RECORD_SWITCH' in event and tid in tids:
            direction = 'OUT' if re.search(r'\bOUT\b', event) else 'IN'
            row = dict(tid=tid, ns=ns, cpu=int(cpu), direction=direction,
                       preempt='preempt' in event)
            switches[tid].append(row)
            for window in windows:
                if window['start'] <= ns <= window['end']:
                    window['switches'].append(row)
                    window['text'].append(line)
    flush()
    assert proc.wait() == 0

for window in windows:
    (out / (window['name'] + '.log')).write_text(''.join(window.pop('text')))
    offcpu = []
    for tid, events in switches.items():
        last_out = None
        for event in events:
            if event['direction'] == 'OUT':
                last_out = event
            elif last_out:
                start = max(window['start'], last_out['ns'])
                end = min(window['end'], event['ns'])
                if end > start:
                    offcpu.append(dict(tid=tid, start=start, end=end,
                                       ms=(end-start)/1e6, preempt=last_out['preempt']))
                last_out = None
    window['offcpu'] = sorted(offcpu, key=lambda row: row['ms'], reverse=True)
    window['duration_ms'] = (window['end']-window['start'])/1e6
    print(window['name'], f"{window['duration_ms']:.3f} ms", 'samples', window['samples'],
          'longest off-CPU', window['offcpu'][:3])
assert any(window['samples'] or window['switches'] for window in windows), 'no aligned profile evidence'
summary = dict(pid=pid, tids=sorted(tids), sample_counts=samples, windows=windows,
               perf_command=command, extraction_command=perf_command)
(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print('ALL SAMPLE COUNTS', dict(samples))
