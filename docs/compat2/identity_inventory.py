#!/usr/bin/env python3
"""Add new-object bodies and an explicit reason for every PRE/POST byte difference."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf


def reason(row):
    name, obj = row['name'], row['object']
    if obj.endswith('/cmd/autharity.o'):
        return ('C1 new object', 'New cold arity/AUTH helper translation unit; associated emitted support bodies.')
    if 'command_reply_container_outer_arity(' in name:
        return ('C1 direct', 'Carry authentication state into the existing outer-arity error path; old signature is replaced.')
    if any(x in name for x in ('acl_dispatch_entry(', 'acl_command_entry(', 'acl_reply_denied(',
                               'auth_dispatch_entry(', '::cmd_command(', '::cmd_dbsize(', '::cmd_script(')):
        return ('C1 direct', 'Validate Redis advertised arity before AUTH; preserve child-command names and EXEC error prefixes.')
    if name.startswith('_GLOBAL__sub_I_') and obj.endswith('/cmd/t_server.o'):
        return ('C1 direct', 'Initialize QUIT with Redis-compatible variadic arity instead of the old maximum of one.')
    if 'parse_and_dispatch<' in name:
        return ('C1 direct', 'Pass the existing requirepass/authenticated state on the taken cold outer-arity branch.')
    if '::FlatStore::find_notify(' in name or '::notify_read_resolves_versions()' in name:
        return ('C2 direct', 'Suppress physical-candidate expiry only when find uses the live-version resolver.')
    if '::IoLoop::release_tls(' in name:
        return ('C3 direct', 'Emit a shared noinline TLS release body used at socket release and the idempotent reap fallback.')
    if '::IoLoop::close_client(' in name:
        return ('C3 direct', 'Release TLS sidecar/gauges after socket release and all existing quiescence fences.')
    if '::IoLoop::reap_dead(' in name:
        return ('C3 caller', 'Existing TLS release call now targets the noinline shared helper; deferred Client lifetime is unchanged.')
    sources = []
    if obj.endswith(('/cmd/acl.o', '/cmd/climon.o', '/cmd/xshard.o', '/core/genthread.o',
                     '/core/reorder.o', '/core/rl2s.o', '/main.o')):
        sources.append('io_loop.h (C1/C3)')
    if obj.endswith(('/cmd/acl.o', '/cmd/commands.o', '/cmd/t_server.o', '/cmd/scripting.o')):
        sources.append('the C1 cold command helpers')
    sources.append('flatstore.h (C2)')
    return ('compiler propagation', 'Source body unedited; recompiled with changes in ' +
            ', '.join(sources) + '. Inlining, emission and instruction differences are retained; '
            'the individual compiler decision was not isolated and requires the merit run.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    a = p.parse_args()
    before, after = ROOT / 'build/compat2/pre-source/build', ROOT / 'build'
    rows = json.loads((a.directory / 'bodies/changed-bodies.json').read_text())
    added = []
    for base in ('src', 'db0/src'):
        for path in sorted((after / base).rglob('*.o')):
            relative = path.relative_to(after)
            if (before / relative).exists():
                continue
            functions = Elf(path).functions()
            names = sorted(functions)
            labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n',
                                              text=True).splitlines()
            for symbol, name in zip(names, labels):
                added.append(dict(object=str(relative), symbol=symbol, name=name, equal=False,
                                  raw_equal=False, pre_size=0, post_size=functions[symbol]['size']))
    rows += added
    assert len({(r['object'], r['symbol']) for r in rows}) == len(rows)
    for row in rows:
        row['category'], row['reason'] = reason(row)
    rows.sort(key=lambda r: (r['object'], r['name'], r['symbol']))
    (a.directory / 'body-reasons.json').write_text(json.dumps(rows, indent=2) + '\n')
    summary = dict(changed_or_added=len(rows), new_object_bodies=len(added),
                   categories=dict(Counter(r['category'] for r in rows)))
    (a.directory / 'body-reasons-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    lines = ['# compat2 emitted-body differences', '',
             'Every changed or newly emitted body is listed, including both namespaces and new objects.',
             'Object-level duplicates are intentional. Identity differences are proxies; merit remains pending.', '',
             '| Object | Body | PRE bytes | POST bytes | Reason |',
             '|---|---|---:|---:|---|']
    for r in rows:
        name = r['name'].replace('|', '&#124;').replace('<', '&lt;').replace('>', '&gt;')
        lines.append(f"| {r['object']} | {name} | {r['pre_size']} | {r['post_size']} | {r['reason']} |")
    (a.directory / 'body-reasons.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
