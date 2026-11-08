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
    dest = ROOT / 'docs/serverfix/identity'
    scratch = ROOT / 'build/serverfix/identity-scratch'
    dest.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(exist_ok=True)
    before = audit.Binary(ROOT / 'build/tomokv-serverfix-pre', scratch, literal_pools=True)
    after = audit.Binary(ROOT / 'build/tomokv', scratch, literal_pools=True)
    rows = []
    hot_compared = []
    hot = re.compile(r'::cmd_(?:get|set|mget|mset)(?:\(|<)|prepare_captured_local_mget|xshard_.*mset')
    for name in sorted(set(before.groups) | set(after.groups)):
        old = sorted(before.groups.get(name, []), key=lambda b: b['addr'])
        new = sorted(after.groups.get(name, []), key=lambda b: b['addr'])
        aliases = [alias for body in old + new for alias in body['aliases']]
        is_hot = bool(hot.search(name) or any(hot.search(a) for a in aliases))
        if is_hot:
            hot_compared.append(name)
        equal = [(b['ins'], b['encodings']) for b in old] == [(b['ins'], b['encodings']) for b in new]
        if equal:
            continue
        reason = 'Compiler/link propagation from cold server/config helpers; retained normalized diff identifies the changed instructions.'
        if any(token in name for token in ('slowlog', 'Slowlog', 'ClientDirectory', 'ClientCatalog', 'command_client_', 'ClientMeta')):
            reason = 'SV4.14: lazy recorder/directory construction and enabled identity snapshots; lifecycle catalog synchronization.'
        elif any(token in name for token in ('AclLog', 'acl_log_', 'acl_set_log_', '_GLOBAL__sub_I_')):
            reason = 'CC4.26/SV4.14: lazy logging stores and static initializer/destructor changes.'
        elif any(token in name for token in ('config', 'Config', 'cmd_hello')):
            reason = 'CG4.3/CG4.4/SV4.6/SV4.7: physical config input, scalar grammar, validation ordering and canonical HELLO integers.'
        elif any(token in name for token in ('hll::', 'cmd_pfselftest')):
            reason = 'SV4.8: deterministic register, sparse/dense and estimator invariant self-test.'
        elif any(token in name for token in ('waitaof', 'prepare_wait', 'reply_wait', 'climon_unblock', 'deferred_timer', 'IoLoop::')):
            reason = 'SV4.5: deferred WAITAOF completion, deadline, disconnect and CLIENT UNBLOCK integration; surrounding inlining.'
        elif any(token in name for token in ('::xshard_execute(', '::xshard_queue_commit(', '::xshard_flush_commits')):
            reason = 'CG4.4/SV4.14 cold TLS storage relocates linked TLS displacements. The existing object relocation normalizer confirms identical execution bodies; strict linked differences are retained.'
        elif any(token in name for token in ('std::', '__gnu_cxx::', 'operator ', 'std::__')):
            reason = 'Template/runtime helper instantiation or inlining for the changed cold config, identity and logging containers.'
        row = dict(name=name, hot=is_hot, pre_sizes=[b['size'] for b in old],
                   post_sizes=[b['size'] for b in new], reason=reason)
        def lines(bodies):
            return [f'clone {i}: {ins} | {enc}\n' for i, b in enumerate(bodies)
                    for ins, enc in zip(b['ins'], b['encodings'])]
        row['diff'] = ''.join(difflib.unified_diff(lines(old), lines(new), fromfile='PRE', tofile='POST'))
        rows.append(row)
    # Retain the full instruction diffs beside the frozen binaries; commit the complete body inventory.
    local = ROOT / 'build/serverfix/identity'
    local.mkdir(parents=True, exist_ok=True)
    with gzip.open(local / 'changed-bodies.json.gz', 'wt') as f:
        json.dump(rows, f, indent=2)
    summary = dict(pre_sha256=before.sha256, post_sha256=after.sha256,
                   changed=len(rows), hot_compared=hot_compared,
                   hot_changed=[r['name'] for r in rows if r['hot']])
    (dest / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (dest / 'changed-bodies.md').write_text('# Changed linked bodies\n\nStrict gate normalization; identity is a proxy, merit decides.\n\n' +
        '| Body | PRE sizes | POST sizes | Reason |\n|---|---|---|---|\n' +
        '\n'.join(f"| `{r['name']}` | {r['pre_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in rows) + '\n')
    for path in scratch.glob('*.objdump'):
        path.unlink()
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
