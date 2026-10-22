#!/usr/bin/env python3
"""Annotate the full byte inventory and check linked GET/SET/MGET/MSET bodies."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re

from ccfix_audit import audit


def input_sections(path):
    result = {}
    pending = None
    for line in path.read_text().splitlines():
        section = re.match(r'^ (\.text\S*)\s*(.*)$', line)
        if section:
            pending = section[1]
            line = section[2]
        match = re.match(r'\s*(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+build/(\S+\.o)\s*$', line)
        if pending and match:
            address, size = int(match[1], 16), int(match[2], 16)
            if address and size:
                key = match[3], pending
                assert key not in result, ('ambiguous input section', key)
                result[key] = address, size
            pending = None
        elif not section and line.strip() and not line.lstrip().startswith('0x'):
            pending = None
    assert result, 'no linked input text sections'
    return result


class Image:
    def __init__(self, root, binary, mapping):
        self.root, self.binary = root, audit.Elf(binary)
        self.sections = input_sections(mapping)
        self.symbols = {(s['name'], s['value'], s['size']) for s in self.binary.symbols
                        if s['info'] & 15 == 2 and s['size']}
        self.objects = {}

    def object(self, relative):
        if relative not in self.objects:
            self.objects[relative] = audit.Elf(self.root / relative)
        return self.objects[relative]

    def linked(self, relative, name):
        obj = self.object(relative)
        symbol = obj.functions().get(name)
        if not symbol:
            return False
        span = self.sections.get((relative, obj.names[symbol['sec']]))
        if not span:
            return False
        assert symbol['value'] + symbol['size'] <= span[1], (relative, name)
        return (name, span[0] + symbol['value'], symbol['size']) in self.symbols


MAIN = re.compile(
    r'::cmd_(?:get|set)(?:<|\()|::cmd_xshard_only(?:_\w+)?(?:<|\()|'
    r'::prepare_local_read\(|::prepare_captured_local_mget\(|'
    r'::local_mget_final_reason\(|::read_local_command_is_precise_mset\(|'
    r'::arm_current_local_mget_fence\(|::ExLoopT<.*>::execute<|'
    r'::xshard_(?:prepare|execute|complete(?:_impl|_iofused)?|plain_prepare|plain_finish|'
    r'aof_emit(?:_local)?|retire|queue_commit|flush_commits|is_local)(?:<|\()|'
    r'::(?:assemble_final|classify_keys|build_groups|allocate_state|finish_phase[12])\(')


def reason(row):
    name = row['name']
    if 'flush_ready' in name or 'WbRulePhase2' in name:
        return 'WB4.1: only bounded deferral advancement reports work; saturated entries can park.'
    if any(word in name for word in ('debug_sleep', 'DebugSleepCoordinator')):
        return 'IO4.10: Redis duration parsing, global worker rendezvous, completion ticket or signal interruption.'
    if 'run_loop' in name:
        return 'IO4.9/10/17: hz cron and bounded park deadline, global pause boundary, immediate pending-signal save.'
    if re.search(r'ExLoopT<.*>::run\(', name):
        return 'IO4.10: worker membership and the global pause check at executor pass entry.'
    if 'parse_and_dispatch' in name:
        return 'IO4.10: direct DEBUG SLEEP uses a global ticket; parser templates and nested lambdas are re-emitted.'
    if any(word in name for word in ('on_cqe', 'epoll_pass', 'rearm_shutdown_poll', 'signal_shutdown_wake')):
        return 'IO4.17: elected IO drains late request wakes, restores terminal wakes and rearms the one-shot signal poll.'
    if any(word in name for word in ('on_signal(', 'shutdown_from_cron', 'signal_doorbell', 'finish_shutdown')):
        return 'IO4.17: separate request and latched terminal wakes; restore concurrent terminal edges and interrupt global sleep.'
    if any(word in name for word in ('client_cron_pass', 'idle_timeout_ms', 'ClientHz')):
        return 'IO4.9: effective Redis hz controls cron cadence, client share and idle wait deadline.'
    if any(word in name for word in ('deferred_timer', 'close_client')):
        return 'IO4.10: DEBUG sleep completion uses a global ticket and is excluded from blocked-client accounting.'
    if any(word in name for word in ('multi_execute_task', 'execute_cross_command', 'finish_command', 'prepare_commands')):
        return 'IO4.10: EXEC sleep retains its microsecond duration, starts at the owner join and waits on a global ticket.'
    if any(word in name for word in ('cmd_config', 'cmd_info', 'normalize_config', 'collect_config_updates',
                                     'init_config', 'parse_cli', 'Config::', 'ConfigValue')):
        return 'IO4.9: hz/dynamic-hz grammar, validation, initialization, CONFIG persistence or INFO reporting.'
    if 'Server::Server(' in name or 'Server::~Server(' in name or name.endswith('::main(int, char**)'):
        return 'IO4.9/10: initialize/destroy the appended server cron policy and global sleep coordinator.'
    if not row['pre_size'] or not row['post_size']:
        return 'Compiler emission changed after the included IO/admin definitions and unit budgets changed; added/removed copy is inventoried.'
    return ('No source edit to this body: changed included IO/admin definitions and unit inlining altered its emitted code or resolved callees. '
            'This is recorded compiler drift, not an identity pass or a performance claim.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=Path('docs/iofix/identity-final'))
    parser.add_argument('--pre-root', type=Path, default=Path('build/iofix/PRE'))
    parser.add_argument('--post-root', type=Path, default=Path('build'))
    args = parser.parse_args()
    images = [Image(args.pre_root, 'build/tomokv-pre', Path('build/iofix/pre-link.map')),
              Image(args.post_root, 'build/tomokv', Path('build/iofix/post-link.map'))]
    rows = json.load(gzip.open(args.inventory / 'bodies.json.gz', 'rt'))
    origins = [{}, {}]
    changed = []
    for row in rows:
        selected = bool(MAIN.search(row['name']))
        linked = [im.linked(row['object'], row['symbol']) for im in images]
        if selected:
            for i, live in enumerate(linked):
                if live:
                    previous = origins[i].setdefault(row['symbol'], row)
                    assert previous['object'] == row['object'], ('ambiguous main body', row)
        if not row['equal']:
            changed.append(dict(row, linked_pre=linked[0], linked_post=linked[1], reason=reason(row)))
    main_rows = []
    for name in sorted(origins[0].keys() | origins[1].keys()):
        old, new = [origin.get(name) for origin in origins]
        canonical = []
        for image, row in zip(images, (old, new)):
            obj = image.object(row['object']) if row else None
            canonical.append(obj.canonical(obj.functions()[name]) if obj else None)
        main_rows.append(dict(symbol=name, name=(old or new)['name'],
                              pre_object=old['object'] if old else None,
                              post_object=new['object'] if new else None,
                              pre_size=old['pre_size'] if old else 0,
                              post_size=new['post_size'] if new else 0,
                              equal=bool(old and new and canonical[0] == canonical[1])))
    output = args.inventory
    (output / 'changed-bodies-with-reasons.json').write_text(json.dumps(changed, indent=2) + '\n')
    (output / 'linked-main-bodies.json').write_text(json.dumps(main_rows, indent=2) + '\n')
    summary = dict(changed_emitted_bodies=len(changed),
                   changed_linked_pre=sum(r['linked_pre'] for r in changed),
                   changed_linked_post=sum(r['linked_post'] for r in changed),
                   main_linked_bodies=len(main_rows), main_equal=sum(r['equal'] for r in main_rows),
                   reasons=dict(Counter(r['reason'] for r in changed)),
                   binaries={p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                             for p in ('build/tomokv-pre', 'build/tomokv')})
    (output / 'annotated-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'reasons'}, indent=2))
    assert main_rows and all(r['equal'] for r in main_rows), 'linked main-command body drift remains listed'


if __name__ == '__main__':
    main()
