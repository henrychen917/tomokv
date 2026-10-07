#!/usr/bin/env python3
"""Summarize read completion, send skew, and PTTL-implied server time cuts."""
import json
from pathlib import Path
import sys

rows = []
for filename in sys.argv[1:]:
    data = json.loads(Path(filename).read_text())
    ops = data['operations']
    replies = {(r['side'], r['op']): r for r in data['events']
               if r['kind'] == 'reply' and r['op'] is not None}
    sends = {(r['side'], r['batch']): r for r in data['events'] if r['kind'] == 'send'}
    future_ms = next(int(op[3]) for op in ops if op[0] == 'GETEX' and len(op) > 3
                     and op[2] == 'PXAT' and int(op[3]) > 1)
    row = dict(file=filename, future_ms=future_ms, positive_pttl=[], targets=[])
    for index, op in enumerate(ops):
        if op[0] != 'PTTL':
            continue
        a = int(bytes.fromhex(replies['target', index]['reply'])[1:-2])
        b = int(bytes.fromhex(replies['oracle', index]['reply'])[1:-2])
        if a > 0 or b > 0:
            row['positive_pttl'].append(dict(op=index, target=a, oracle=b, delta_ms=a-b))
    print('\nTRACE', filename, 'positive PTTL:', row['positive_pttl'])
    for index in (1526, 2910):
        batch = index // 64 * 64
        a, b = replies['target', index], replies['oracle', index]
        av = int(bytes.fromhex(a['reply'])[1:-2])
        bv = int(bytes.fromhex(b['reply'])[1:-2])
        # Seed-7's successful EXPIREAT 1492 and GETEX PXAT 2766 establish these.
        deadline = future_ms // 1000 * 1000 if index == 1526 else future_ms
        window = dict(op=index, batch=batch, deadline_ms=deadline, target=av, oracle=bv,
                      delta_ms=av-bv, target_cut_ms=deadline-av, oracle_cut_ms=deadline-bv)
        for side in ('target', 'oracle'):
            send = sends[side, batch]
            reply = replies[side, index]
            window[side + '_send_ns'] = send['before'][0]
            window[side + '_reply_ns'] = reply['after'][0]
            window[side + '_batch_to_reply_ms'] = (reply['after'][0]-send['before'][0])/1e6
            window[side + '_send_wall_ms'] = send['before'][1]/1e6
            window[side + '_reply_wall_ms'] = reply['after'][1]/1e6
            window[side + '_cut_after_send_ms'] = window[side + '_cut_ms']-send['before'][1]/1e6
        window['oracle_send_after_target_us'] = (
            sends['oracle', batch]['before'][0]-sends['target', batch]['before'][0])/1e3
        window['reads'] = []
        for op_index in range(batch, index+2):
            item = dict(op=op_index, command=ops[op_index])
            for side in ('target', 'oracle'):
                event = replies[side, op_index]
                item[side + '_read_ms'] = (event['after'][0]-event['before'][0])/1e6
                item[side + '_since_send_ms'] = (event['after'][0]-sends[side, batch]['before'][0])/1e6
            window['reads'].append(item)
        row['targets'].append(window)
        print('WINDOW', json.dumps({k: v for k, v in window.items() if k != 'reads'}))
        print('LARGEST CLIENT READ WAITS', sorted(window['reads'],
              key=lambda v: v['target_read_ms'], reverse=True)[:5])
    rows.append(row)
Path('docs/at15c/trace-summary.json').write_text(json.dumps(rows, indent=2) + '\n')
