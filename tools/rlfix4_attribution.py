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
extra = read(DOC / 'boundaries/wave8-extra-bodies.json')
emissions = []
for span, records in [('anchor-wave7', chain), ('wave7-pre', extra)]:
    previous = {}
    for record in records:
        title = subprocess.check_output(['git', 'show', '-s', '--format=%s', record['commit']], cwd=ROOT, text=True).strip()
        current = {}
        for unit in record['units']:
            for body in unit['bodies']:
                current[unit['unit'], body['name']] = body
        for key in sorted(current.keys() | previous.keys()):
            before, after = previous.get(key), current.get(key)
            if (before or {}).get('digest') == (after or {}).get('digest'):
                continue
            emissions.append(dict(span=span, commit=record['commit'], lane_or_integration=title,
                unit=key[0], name=key[1], before=before, after=after))
        previous = current
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
        and change['after'] in endpoints
        and ancestor(r['commit'], endpoints[change['after']])
        and not ancestor(r['commit'], endpoints[change['before']])]
    if change['before'] == 'pre':
        change['compiler_events'] = [dict(commit='18f0ceb8b', lane_or_integration='rlfix4 final registry guard and budget',
            earlier_commits=['11ae8a977', 'df5c790d2'])]
save(DOC / 'body-attribution.json', changes)

# These are totals by source origin, not a fictitious one-to-one instruction
# edit mapping. Prologue/assembly/no-DWARF instructions remain visible.
origins = {}
for arm in ('anchor', 'wave6', 'wave7', 'preparse'):
    for ns in ('normal', 'db0'):
        with gzip.open(DOC / f'source-sites/{arm}-{ns}.json.gz', 'rt') as f:
            record = json.load(f)
        for filename, sites in record['cases'].items():
            trace = read(DOC / 'instructions' / filename)
            assert trace['binary_sha256'] == record['binary_sha256']
            bins = collections.Counter()
            for pc, count in sites.items():
                frames = record['origins'].get(hex(int(pc, 16)), [])
                frame = next((x for x in frames if x.get('source_commit')), {})
                key = frame.get('source_commit', '<assembly/compiler>'), frame.get('path', '<no source>'), frame.get('function', '<no source>')
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
        deltas.append(dict(before=before, after=after, namespace=ns, case=case,
            delta=sum(x['delta'] for x in changes), source_origin_deltas=changes))
save(DOC / 'source-origin-deltas.json', deltas)
print(len(emissions), 'compile body transitions;', len(deltas), 'exact source-origin ledgers')
