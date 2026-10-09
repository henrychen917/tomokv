#!/usr/bin/env python3
"""Account for every PRE/POST object body and type layout without running a server."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from ccfix_audit import audit
from aclkeys3_budget import ALLOWED

ROOT = Path(__file__).resolve().parents[1]


def path_reason(name):
    for token, reason in (
        ('blocking_task_done', 'Final active-task departure publishes MoveRequested and notifies; includes its new outlined tail'),
        ('blocking_request_move', 'Count the requesting publisher and enter MovePending before dropping its task reference'),
        ('blocking_dispatch_selected', 'Selected XREAD/list-move request uses the new publisher protocol'),
        ('BlockingRegistry::service', 'A ready registered XREAD/list move uses the new publisher protocol'),
        ('blocking_scatter_retire', 'Recheck retained blocking ACL permissions on scatter retirement'),
        ('blocking_resume_move_impl', 'Reject MovePending and record armed DEBUG stage 3 at the actual IO entry'),
        ('blocking_debug_xread_hold', 'New noinline XREAD registration/final-task DEBUG latch predicate'),
        ('blocking_execute', 'Hold actual XREAD registration/final-task stages and use the final-task publisher'),
        ('cmd_debug', 'Dispatch the new cold DEBUG subcommand while preserving existing error text'),
        ('debug_xread_registration_', 'New DEBUG stage parser; two static atomic words, no waiter allocation'),
        ('blocking_fail_registration_oom', 'Registration OOM tail outlined after the blocked-path change'),
    ):
        if token in name:
            return reason + ('; exception landing pad follows that body' if '[clone .cold]' in name else '')
    raise AssertionError('unexplained admitted body: ' + name)


def layouts(binary):
    # The older layout tool also patches Elf.canonical on import. Keep that
    # independent from ccfix's stronger target-aware canonicalizer.
    code = ('import json,sys; from pathlib import Path; from psfix_artifacts import layouts; '
            'print(json.dumps(layouts(Path(sys.argv[1]))))')
    return json.loads(subprocess.check_output(
        [sys.executable, '-c', code, str(binary.resolve())], cwd=ROOT / 'tools', text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for relative in sorted({path.relative_to(root) for root in (args.pre, args.post)
                            for stem in ('src', 'db0/src') for path in (root / stem).rglob('*.o')}):
        pair = [audit.Elf(root / relative) if (root / relative).exists() else None
                for root in (args.pre, args.post)]
        tables = [elf.functions() if elf else {} for elf in pair]
        symbols = sorted(tables[0].keys() | tables[1].keys())
        names = subprocess.check_output(['c++filt'], input='\n'.join(symbols) + '\n',
                                        text=True).splitlines()
        for symbol, name in zip(symbols, names):
            bodies = [elf.canonical(table[symbol]) if elf and symbol in table else None
                      for elf, table in zip(pair, tables)]
            equal = bodies[0] is not None and bodies[0] == bodies[1]
            if relative.name in ('acl.o', 'aclkeys.o'):
                reason = 'Inherited ACL key-extraction change; this lane does not modify this TU'
            elif ALLOWED.search(name):
                reason = path_reason(name)
            elif relative.name == 'blocking_debug.o':
                reason = 'Compiler helper emitted by the new isolated DEBUG TU; check linker selection'
            elif equal:
                reason = 'Identical opcodes and resolved targets'
            else:
                reason = 'UNRESOLVED outside-path code-generation drift'
            rows.append(dict(object=str(relative), symbol=symbol, name=name, equal=equal,
                             pre_size=tables[0].get(symbol, {}).get('size', 0),
                             post_size=tables[1].get(symbol, {}).get('size', 0),
                             pre_canonical_sha256=hashlib.sha256(repr(bodies[0]).encode()).hexdigest()
                                if bodies[0] else None,
                             post_canonical_sha256=hashlib.sha256(repr(bodies[1]).encode()).hexdigest()
                                if bodies[1] else None,
                             reason=reason))
        print(relative, len(symbols), flush=True)
    before, after = layouts(args.pre / 'tomokv'), layouts(args.post / 'tomokv')
    changed = [row for row in rows if not row['equal']]
    unresolved = [row for row in changed if row['reason'].startswith('UNRESOLVED')]
    hot = [row for row in rows if audit.HOT.search(row['name']) or
           re.search(r'ExLoopT<.*>::run\(', row['name'])]
    handlers = [row for row in rows if re.search(r'::cmd_\w+(?:<|\()', row['name']) and
                '::cmd_debug' not in row['name']]
    arms = {}
    for arm, root in (('PRE', args.pre), ('POST', args.post)):
        elf = audit.Elf(root / 'tomokv')
        arms[arm] = dict(sha256=hashlib.sha256(elf.data).hexdigest(),
                         text_bytes=elf.sections[elf.names.index('.text')][5])
    report = dict(total=len(rows), equal=sum(row['equal'] for row in rows), changed=len(changed),
                  hot=len(hot), hot_equal=sum(row['equal'] for row in hot),
                  ordinary_handlers=len(handlers), ordinary_handlers_equal=sum(row['equal'] for row in handlers),
                  unresolved=unresolved, layouts_equal=before == after, arms=arms)
    with gzip.open(args.output / 'bodies.json.gz', 'wt') as output:
        json.dump(rows, output, indent=2)
    (args.output / 'changed-bodies.json').write_text(json.dumps(changed, indent=2) + '\n')
    (args.output / 'layouts.json').write_text(json.dumps(dict(PRE=before, POST=after), indent=2) + '\n')
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    text = ['# aclkeys3 emitted body changes', '',
            'Relocation fields are resolved by identity; opcodes, member offsets and call targets remain checked.', '',
            '| Object | Body | PRE bytes | POST bytes | Reason |', '|---|---|---:|---:|---|']
    for row in changed:
        text.append('| `%s` | `%s` | %d | %d | %s |' %
                    (row['object'], row['name'].replace('|', '\\|'), row['pre_size'], row['post_size'], row['reason']))
    (args.output / 'changed-bodies.md').write_text('\n'.join(text) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    assert before == after, 'layout changed'
    assert all(row['equal'] for row in hot), 'ordinary hot body changed'
    assert all(row['equal'] for row in handlers), 'ordinary command handler changed'
    assert not unresolved, 'outside-path emitted body changed; report is not a pass'


if __name__ == '__main__':
    main()
