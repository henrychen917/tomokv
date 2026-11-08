#!/usr/bin/env python3
"""PRE/POST command-scope instruction table for lane cfgfix2. Reads the census JSON only."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/cfgfix2/instructions'


def load(label):
    data = json.loads((DOC / label / 'counts.json').read_text())
    rows = {(r['namespace'], r['command'], r['mode'], r['batch'], r['atomic']): r['total'] for r in data['rows']}
    return data['server_sha256'], rows


pre_sha, pre = load('PRE')
post_sha, post = load('POST')
assert set(pre) == set(post), 'census cells differ'
lines = ['# Command-scope instruction census', '',
         f'PRE `{pre_sha}`; POST `{post_sha}`.', '',
         'Serverless complete production command scope; excludes libc/kernel time and explicitly '
         'records clock/library calls. This is instruction accounting, not a cycles, IPC, latency '
         'or throughput result.', '',
         '| Namespace | Command | Mode | Batch | Atomic | PRE | POST | Delta |',
         '|---|---|---|---|---|---:|---:|---:|']
added = 0
for key in sorted(pre):
    delta = post[key] - pre[key]
    added += delta > 0
    lines.append('| ' + ' | '.join(map(str, key)) + f' | {pre[key]} | {post[key]} | {delta} |')
lines += ['', f'Cells with added instructions: {added} of {len(pre)}.']
(DOC / 'table.md').write_text('\n'.join(lines) + '\n')
print(json.dumps(dict(cells=len(pre), added=added,
                      identical=sum(pre[k] == post[k] for k in pre),
                      removed=sum(post[k] < pre[k] for k in pre))))
