#!/usr/bin/env python3
"""Require exact known deadlines from the separately labelled absolute controls."""
import json
from pathlib import Path

rows = []
for arm in ('post', 'pre'):
    for path in sorted(Path('build/at15c/absolute-control-' + arm).glob('edgetime-*.json')):
        data = json.loads(path.read_text())
        assert data['absolute_control']
        ops = data['operations']
        assert ops[1492][0] == 'EXPIREAT' and ops[2766][0:3:2] == ['GETEX', 'PXAT']
        replies = {(e['side'], e['op']): bytes.fromhex(e['reply'])
                   for e in data['events'] if e['kind'] == 'reply'}
        for op, expected in ((1526, int(ops[1492][2])*1000), (2910, int(ops[2766][3]))):
            assert ops[op][0] == 'PEXPIRETIME'
            a, b = replies['target', op], replies['oracle', op]
            assert a == b == b':%d\r\n' % expected, (path, op, a, b, expected)
            rows.append(dict(file=str(path), arm=arm, op=op, exact_deadline_ms=expected))
assert len(rows) == 12, len(rows)
Path('docs/at15c/absolute-controls.json').write_text(json.dumps(rows, indent=2) + '\n')
print('PASS: all 12 query pairs equal their exact known absolute deadlines')
