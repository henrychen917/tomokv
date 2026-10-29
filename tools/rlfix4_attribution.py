#!/usr/bin/env python3
"""Join executed-body changes, source origins and integration compile receipts.

Source attribution and compiler causality are deliberately separate columns:
DWARF/git blame cannot explain an inlining decision in a different translation
unit. The compile history records each body rewrite, including budget changes.
"""
import collections, gzip, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/rlfix4'
read = lambda p: json.loads(p.read_text())
save = lambda p, x: p.write_text(json.dumps(x, indent=2) + '\n')
chain = read(DOC / 'boundaries/historical-chain.json')
assert len(chain) == len(read(DOC / 'integration-chain.json')) + 1, 'compile chain incomplete'
merged = {}
for filename in ('wave8-merges.json', 'results.json', 'wave8-extra-bodies.json'):
    for record in read(DOC / 'boundaries' / filename):
        units = merged.setdefault(record['commit'], {})
        for unit in record['units']:
            old = units.get(unit['unit'])
            if old:
                assert old['sha256'] == unit['sha256'], (record['commit'], unit['unit'])
                bodies = {b['name']: b for b in old['bodies']}
                bodies.update({b['name']: b for b in unit['bodies']})
                unit = dict(unit, bodies=list(bodies.values()))
            units[unit['unit']] = unit
order = subprocess.check_output(['git', 'rev-list', '--reverse', '--topo-order', '3700b51d7^..a214652ec'], cwd=ROOT, text=True).splitlines()
assert set(merged) <= set(order)
extra = [dict(commit=commit, units=list(merged[commit].values())) for commit in order if commit in merged]
# The early wave-8 snapshots predate the expanded symbol selector. Compare the
# common selection only: an unrecorded helper is not evidence it was absent.
wave8_common = ('parse_and_dispatch<false, 32u, false>', 'drain_local_reads_bounded_impl<false>',
    'prepare_local_read(', 'hash_key(', 'siphash12', 'cmd_name()', 'local_read_lane_has_room', 'notify_sender(')
emissions = []
for span, records in [('anchor-wave7', chain), ('wave7-pre', extra)]:
    previous = {}
    seen_units = set()
    for record in records:
        title = subprocess.check_output(['git', 'show', '-s', '--format=%s', record['commit']], cwd=ROOT, text=True).strip()
        selected_units = {unit['unit'] for unit in record['units']}
        current = {key: value for key, value in previous.items() if key[0] not in selected_units}
        for unit in record['units']:
            for body in unit['bodies']:
                if span == 'wave7-pre' and not any(token in body['name'] for token in wave8_common):
                    continue
                current[unit['unit'], body['name']] = body
        for key in sorted(current.keys() | previous.keys()):
            before, after = previous.get(key), current.get(key)
            if (before or {}).get('digest') == (after or {}).get('digest'):
                continue
            emissions.append(dict(span=span, commit=record['commit'], lane_or_integration=title,
                unit=key[0], name=key[1], first_unit_observation=key[0] not in seen_units,
                before=before, after=after))
        previous = current
        seen_units.update(selected_units)
save(DOC / 'body-emission-history.json', emissions)

# Map every entered GET body change to all observed emissions of that same
# function in the relevant interval. Keep missing explicit-instantiation units
# explicit; the source change and linked-body digest remain independently known.
changes = read(DOC / 'visited-body-transitions.json')
endpoints = dict(anchor='991d48f65', wave6='05a5e01a9', wave7='3700b51d7', pre='a214652ec')
ancestry = {}
def ancestor(commit, endpoint):
    key = commit, endpoint
    if key not in ancestry:
        ancestry[key] = subprocess.call(['git', 'merge-base', '--is-ancestor', commit, endpoint], cwd=ROOT) == 0
    return ancestry[key]
for change in changes:
    span = 'wave7-pre' if change['before'] == 'wave7' else 'anchor-wave7'
    change['compiler_events'] = [dict(commit=r['commit'], lane_or_integration=r['lane_or_integration'],
        unit=r['unit'], before_digest=(r['before'] or {}).get('digest'), after_digest=(r['after'] or {}).get('digest'))
        for r in emissions if r['span'] == span and r['name'] == change['name']
        and not r['first_unit_observation']
        and change['after'] in endpoints
        and ancestor(r['commit'], endpoints[change['after']])
        and not ancestor(r['commit'], endpoints[change['before']])]
    if change['before'] == 'pre':
        change['compiler_events'] = [dict(commit='18f0ceb8b', lane_or_integration='rlfix4 final registry guard and budget',
            earlier_commits=['11ae8a977', 'df5c790d2'])]
    name = change['name']
    change['source_events'] = []
    if 'resp_parse_t<' in name:
        change['source_events'] = [dict(commit='873b71047', integration='39a4bd9b2', lane='respresume',
            effect='resumable RESP signature/callee replacement; complete-frame parser cost falls')]
    elif 'multi_session_watch_size' in name:
        if change['before'] == 'anchor':
            change['source_events'] = [dict(commit='a400d1f23', lane='txnorder',
                effect='MultiSession last_attempts moves cold field offsets; entered null path unchanged')]
        else:
            change['source_events'] = [dict(commit='d64accaca', integration='033be1114', lane='atomfix5',
                effect='logical WATCH traversal changes cold body; entered null path unchanged')]
    elif 'prepare_local_read' in name and change['before'] == 'anchor':
        change['source_events'] = [dict(commit='3676d3cae', integration='d1f5fe0bc', lane='rlfix', effect='required GET-miss path'),
            dict(commit='5cd136502', integration='4c692daf4', lane='clockcut', effect='required exact TTL boundary')]
    elif 'drain_local_reads_bounded_impl' in name and change['before'] == 'anchor':
        change['source_events'] = [dict(commit='c97c118a2', integration='08d964975', lane='trackfix', effect='required tracking certificate')]
    elif 'query_buffer_exceeded' in name:
        change['source_events'] = [dict(commit='24c828243', lane='netfix', effect='query-limit accounting')]
    elif 'flip_dispatch_paused' in name:
        change['source_events'] = [dict(commit='323bbd770', lane='wave5 integration', effect='noinline per-pass pause helper')]
    if not change['before_digests'] and change['before'] != 'pre':
        change['entered_set_note'] = 'newly entered helper; an entered-set change does not imply a new helper implementation'
        if 'touch_worker' in name:
            change['caller_event'] = dict(commit='f49beb99e' if change['before'] == 'anchor' else '81a7ec066',
                lane='iofix integration' if change['before'] == 'anchor' else 'latencyfix integration')
        elif 'Op::cmd_name' in name or 'unique_ptr' in name:
            change['caller_event'] = dict(commit='81a7ec066', lane='latencyfix integration')
    assert change['compiler_events'] or change['source_events'] or change.get('caller_event'), change
save(DOC / 'body-attribution.json', changes)

# These are totals by source origin, not a fictitious one-to-one instruction
# edit mapping. Prologue/assembly/no-DWARF instructions remain visible.
origins = {}
for arm in ('anchor', 'wave6', 'wave7', 'pre', 'preparse'):
    for ns in ('normal', 'db0'):
        with gzip.open(DOC / f'source-sites/{arm}-{ns}.json.gz', 'rt') as f:
            record = json.load(f)
        for filename, sites in record['cases'].items():
            trace = read(DOC / 'instructions' / filename)
            assert trace['binary_sha256'] == record['binary_sha256']
            bins = collections.Counter()
            for pc, count in sites.items():
                frames = record['origins'].get(hex(int(pc, 16)), [])
                frame = next((x for x in frames if x.get('source_commit')), frames[0] if frames else {})
                key = frame.get('source_commit') or '<toolchain/assembly>', frame.get('path', '<no source>'), frame.get('function', '<no source>')
                bins[key] += count
            assert sum(bins.values()) == trace['total'], filename
            suffix = filename[len(arm + '-' + ns + '-'):-5]
            origins['pre' if arm == 'preparse' else arm, ns, suffix] = bins
deltas = []
for before, after in [('anchor', 'wave6'), ('wave6', 'wave7'), ('wave7', 'pre')]:
    for arm, ns, case in sorted(origins):
        if arm != before:
            continue
        a, b = origins[before, ns, case], origins[after, ns, case]
        changes = [dict(source_commit=k[0], path=k[1], function=k[2], before=a[k], after=b[k], delta=b[k]-a[k])
            for k in sorted(a.keys() | b.keys()) if a[k] != b[k]]
        for item in changes:
            if item['source_commit'] == '<toolchain/assembly>':
                # Five anonymous ROB retirement instructions do not change.
                # The sole changed non-repository origin is the normal mixed
                # R7 destructor: six inline instructions become fifteen in its
                # outlined helper. Its extra call appears at this integration.
                assert before == 'wave7' and after == 'pre' and ns == 'normal'
                assert case == 'GET-1s-32-1--1-r7mix' and item['path'].endswith('/bits/unique_ptr.h'), item
                item['compiler_integration'] = '81a7ec066'
                item['lane'] = 'latencyfix integration'
        deltas.append(dict(before=before, after=after, namespace=ns, case=case,
            delta=sum(x['delta'] for x in changes), source_origin_deltas=changes))
save(DOC / 'source-origin-deltas.json', deltas)
print(len(emissions), 'compile body transitions;', len(deltas), 'exact source-origin ledgers')
