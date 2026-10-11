"""Witness reduction. No elapsed-time lower bound is treated as an overlap.

Trace identities are process-local, and are discarded at every fresh boot.
All mandatory fields are checked. Unsupported/missed windows remain zero.
"""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Event:
    kind: str
    id: int = 0
    a: int = 0
    b: int = 0
    c: int = 0
    d: int = 0
    ns: int = 0
    ms: int = 0


def trace(path, pid):
    with Path(path).open() as stream:
        header = stream.readline().split()
        if len(header) != 3 or header[:2] != ['LOTTERY1', str(pid)]:
            raise ValueError('missing/wrong-process lottery trace header')
        int(header[2])
        count = 0
        for line in stream:
            fields = line.split()
            if fields[0] == 'END':
                if fields != ['END', str(count), '1'] or stream.read():
                    raise ValueError('overflow, I/O error, or trailing trace data')
                return
            if len(fields) != 9 or int(fields[0]) != count + 1:
                raise ValueError('missing/reordered/malformed trace record')
            count += 1
            numbers = list(map(int, fields[2:]))
            if any(n < 0 for n in numbers):
                raise ValueError('negative trace word')
            yield Event(fields[1], *numbers)
        raise ValueError('missing trace footer')


def reduce_events(events):
    counts = Counter()
    config_ex, config_io, checks = {}, {}, []
    groups, installed, decisions, reads, moves = {}, {}, {}, {}, {}
    apply = {}
    timers, partial, tls_ids, ssl, tls_inputs = {}, {}, {}, {}, set()
    tracking_pending, tracking_checks = set(), []
    tracking_emitted = 0
    work, flips = set(), {}
    section = None
    sections = Counter()
    last_ns = -1
    for e in events:
        if e.ns < last_ns:
            raise ValueError('trace clock regressed')
        last_ns = e.ns
        k = e.kind
        if k == 'config_ex':
            config_ex[e.id] = e.a
        elif k == 'config_io':
            config_io[e.id] = e.a
        elif k == 'config_check':
            # No foreign reads of the owners' plain cached fields. Each apply
            # record was written by that owner after its own assignment.
            owners = set(config_ex) | set(config_io)
            checks.append(len(owners) == e.b and all(
                value == e.a for value in [*config_ex.values(), *config_io.values()]))
        elif k == 'write_new':
            groups.pop(e.id, None)
            installed.pop(e.id, None)
        elif k == 'exec_key':
            groups.setdefault(e.id, dict(keys=set(), conn=e.b))['keys'].add(e.a)
        elif k == 'exec_installed':
            if e.a > 1 and e.b > 0:
                installed[e.id] = e.c
        elif k == 'foreign_undecided':
            if (e.id in installed and e.id in groups and e.a in groups[e.id]['keys']
                    and e.c != e.d and e.d == installed[e.id]):
                counts['W16'] += 1
        elif k == 'exec_decision':
            installed.pop(e.id, None)
            if e.id in groups:
                decisions[e.a] = groups.pop(e.id)
            apply.pop(e.id, None)
        elif k == 'commit':
            for ticket in range(e.a, e.a + e.b):
                group = decisions.pop(ticket, None)
                if not group:
                    continue
                for r in reads.values():
                    # First fragment finished, some other fragment has not yet
                    # begun, and the writer touches that reader's first keys.
                    if (r['done'] and len(r['begun']) < r['n'] and
                            group['conn'] != r['conn'] and
                            group['keys'] & r['finished_keys']):
                        r['commits'].append((set(r['begun']), group['keys']))
        elif k == 'read_new':
            reads[e.id] = dict(n=e.a, cut=e.b, conn=e.c, begun=set(), done=set(),
                              keys={}, finished_keys=set(), commits=[])
        elif k == 'read_begin' and e.id in reads:
            reads[e.id]['begun'].add(e.a)
        elif k == 'read_key' and e.id in reads:
            r = reads[e.id]
            r['keys'].setdefault(e.b, set()).add(e.a)
            if r['cut'] != (1 << 64) - 1 and any(
                    e.b not in before and e.a in keys for before, keys in r['commits']):
                counts['W2.fanout'] += 1
        elif k == 'read_end' and e.id in reads:
            r = reads[e.id]
            r['done'].add(e.a)
            r['finished_keys'].update(r['keys'].get(e.a, ()))
        elif k == 'read_drop':
            reads.pop(e.id, None)
        elif k == 'flush':
            if any(r['done'] and len(r['done']) < r['n'] and
                   r['cut'] != (1 << 64) - 1 for r in reads.values()):
                counts['W2.pin_flush'] += 1
        elif k == 'ryow_defer':
            counts['W2.ryow'] += 1
        elif k.startswith('expiry_section_'):
            section = k
        elif k == 'expiry_lookup' and e.a < e.b <= e.ms:
            if section:
                sections[section] += 1
        elif k == 'move_selected':
            moves[e.id] = dict(key=e.a, selected_left=e.b, pushed=set())
        elif k == 'push_end':
            for move in moves.values():
                if move['key'] == e.id:
                    move['pushed'].add(e.a)
        elif k == 'move_remove':
            move = moves.pop(e.id, None)
            if move:
                for edge in move['pushed']:
                    counts['W6.left' if edge else 'W6.right'] += 1
        elif k == 'block_timeout' and e.c >= e.b > 0:
            counts['W5.timeout'] += 1
        elif k == 'idle_close' and e.c - e.b > e.a > 0:
            counts['W5.idle'] += 1
        elif k == 'obuf_close' and e.b == 0 and e.c and e.d > e.c:
            counts['W5.soft'] += 1
        elif k == 'cron_exempt' and e.c - e.b > e.a > 0:
            counts['W5.exempt'] += 1
        elif k == 'timer_start' and e.a == 1:
            timers[e.id] = (e.b, e.c)
        elif k == 'ping':
            if any(client != e.id and owner == e.a and e.ns // 1000000 < deadline
                   for client, (owner, deadline) in timers.items()):
                counts['W7.progress'] += 1
        elif k == 'timer_cancel':
            timer = timers.pop(e.id, None)
            if timer and e.a == 1 and e.ns // 1000000 < timer[1]:
                counts['W7.cancel'] += 1
        elif k == 'parser_partial' and e.c > 0:
            partial[e.id] = dict(tls=e.b, ns=e.ns, samples=0)
        elif k == 'parser_complete':
            partial.pop(e.id, None)
        elif k == 'lbsignals':
            for p in partial.values():
                p['samples'] += 1
                if p['samples'] >= 2:
                    counts['W10'] += 1
        elif k == 'apply_group':
            apply[e.id] = (e.a, set())
        elif k == 'apply_key' and e.id in apply:
            apply[e.id][1].add(e.a)
        elif k == 'snapshot_drain' and e.a > 0:
            if any(0 < len(keys) < total for total, keys in apply.values()):
                counts['W9'] += 1
        elif k == 'work_begin':
            work.add(e.id)
        elif k == 'work_end':
            work.discard(e.id)
            if not work:
                for flip in flips:
                    flips[flip] = False
        elif k == 'flip_begin':
            flips[e.id] = bool(work)
        elif k == 'flip_end' and flips.pop(e.id, False):
            counts['W11'] += 1
        elif k == 'tls_identity':
            tls_ids[e.id] = e.a
        elif k == 'tls_input':
            tls_inputs.add(e.id)
        elif k == 'ssl_handshake':
            ssl[e.id] = dict(partial_handshake=e.a > 0 and e.b == 0 and e.c == 1,
                             record=False, bytes=e.a)
        elif k == 'ssl_read':
            s = ssl.setdefault(e.id, {})
            if e.a > s.get('bytes', e.a) and not e.b:
                s['record'] = True
            s['bytes'] = e.a
        elif k == 'tls_retire':
            s = ssl.pop(tls_ids.pop(e.id, None), {})
            counts['W12.handshake'] += bool(s.get('partial_handshake'))
            counts['W12.record'] += bool(s.get('record'))
            counts['W12.parser'] += bool(partial.pop(e.id, {}).get('tls'))
        elif k == 'tracking_post':
            tracking_pending.add((e.id, e.a))
        elif k == 'tracking_end':
            tracking_pending.discard((e.id, e.a))
        elif k == 'tracking_emit':
            tracking_emitted += 1
        elif k == 'tracking_compare_begin':
            tracking_checks.append(not tracking_pending)
        elif k in ('tracking_compare_zero', 'tracking_compare_data'):
            tracking_checks.append(not tracking_pending)
            if k == 'tracking_compare_zero' and tracking_emitted:
                raise ValueError('negative tracking drain missed emitted invalidation(s)')
            tracking_emitted = 0
        elif k == 'save_admitted':
            counts['W14'] += 1
        elif k == 'stream_clock':
            # Exact owner's cached cut, not IO TIME +/- an arbitrary tolerance.
            if e.c == max(e.a, e.b):
                counts['W15'] += 1
            else:
                raise ValueError('auto stream ID disagrees with its owner clock')
    counts['W1'] = int(bool(checks) and all(checks))
    counts['W13'] = int(bool(tracking_checks) and all(tracking_checks) and not tracking_pending)
    counts['W4'] = int(all(sections[f'expiry_section_{s}'] for s in ('fanout', 'exec', 'script')))
    return counts


def observed(row, events, log, before, after):
    counts = reduce_events(events)
    if row['family'] == 's6':
        counts['W3'] = int(bool(re.search(r'A4 draws=20000 distinct=200 missing=0 unexpected=0 nulls=0', log)))
    if row['id'] == '122':
        counts['W10.idle'] = int('mechanism=fired' in log)
    if row['family'] == 'snapshot capture/reload':
        for data in (before, after):
            if 'snapshot_preimages' not in data:
                raise ValueError('missing existing snapshot_preimages witness')
        delta = int(after['snapshot_preimages']) - int(before['snapshot_preimages'])
        if delta < 0:
            raise ValueError('snapshot counter regressed')
        counts['W8'] = delta
    return {key: counts[key] for key in row['requires']}
