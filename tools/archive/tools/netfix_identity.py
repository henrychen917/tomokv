#!/usr/bin/env python3
"""Strict linked-body identity against PRE, using the gate's unchanged normalizer."""
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import reorder_noop as audit


def main():
    dest = ROOT / 'docs/netfix/identity'
    scratch = ROOT / 'build/netfix-identity'
    dest.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(exist_ok=True)
    before = audit.Binary(ROOT / 'build/tomokv-pre-netfix', scratch, literal_pools=True)
    after = audit.Binary(ROOT / 'build/tomokv', scratch, literal_pools=True)
    rows = []
    hot = re.compile(r'::cmd_(?:get|set|mget|mset)(?:\(|<)|prepare_captured_local_mget|xshard_.*mset')
    for name in sorted(set(before.groups) | set(after.groups)):
        old = sorted(before.groups.get(name, []), key=lambda b: b['addr'])
        new = sorted(after.groups.get(name, []), key=lambda b: b['addr'])
        equal = [(b['ins'], b['encodings']) for b in old] == [(b['ins'], b['encodings']) for b in new]
        if equal:
            continue
        reason = 'Compiler/link propagation from added cold network maintenance; inspect the retained strict diff.'
        if any(token in name for token in ('resp_parse_tail', 'resp_resume')):
            reason = 'NT4.8 follow-up: cold resumed bulk-header fast decoder bounded below uint64 overflow (LONG_MAX limits).'
        elif 'command_proto_max_bulk_len' in name:
            reason = 'NT4.8 follow-up: string growth (APPEND/SETRANGE/SETBIT/BITFIELD) keeps the 32-bit representable bound.'
        elif any(token in name for token in ('IdleBuffers', 'client_buffer_cron', 'client_cron_pass')):
            reason = 'NT4.19: cold buffer peak sampling, reclamation and original-recv cancellation fence.'
        elif 'IoLoop' in name:
            reason = 'Network owner integration: query-limit accounting, cancellation error edge, cold cron, or removal of request-time buffer sheds.'
        elif 'Tls' in name or 'default_cipher_order' in name:
            reason = 'NT4.7: complete OpenSSL default cipher set and Redis default session cache.'
        elif any(token in name for token in ('config', 'Config', 'cmd_info', 'query_limit', 'LateUnix')):
            reason = 'Cold Redis compatibility: network CONFIG grammar/errors, INFO counter/reset, Unix path replacement, or inherited constructor/destructor.'
        aliases = [alias for body in old + new for alias in body['aliases']]
        row = dict(name=name, hot=bool(hot.search(name) or any(hot.search(a) for a in aliases)), pre_sizes=[b['size'] for b in old],
                   post_sizes=[b['size'] for b in new], reason=reason)
        def lines(bodies):
            return [f'clone {i}: {ins} | {enc}\n' for i, b in enumerate(bodies)
                    for ins, enc in zip(b['ins'], b['encodings'])]
        row['diff'] = ''.join(difflib.unified_diff(lines(old), lines(new), fromfile='PRE', tofile='POST'))
        rows.append(row)
    # The complete strict diffs exceed the 1 MB commit rule: retained locally (build/ is ignored).
    local = ROOT / 'build/netfix-receipts'
    local.mkdir(parents=True, exist_ok=True)
    with gzip.open(local / 'changed-bodies.json.gz', 'wt') as f:
        json.dump(rows, f, indent=2)
    summary = dict(pre_sha256=before.sha256, post_sha256=after.sha256,
                   changed=len(rows), hot_changed=[r['name'] for r in rows if r['hot']])
    (dest / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (dest / 'changed-bodies.md').write_text('# Changed linked bodies\n\nStrict gate normalization; identity is a proxy, merit decides.\n\n' +
        '| Body | PRE sizes | POST sizes | Reason |\n|---|---|---|---|\n' +
        '\n'.join(f"| `{r['name']}` | {r['pre_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in rows) + '\n')
    for path in scratch.glob('*.objdump'):
        path.unlink()
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
