#!/usr/bin/env python3
"""Compare every finite command scope and retain each changed production symbol."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/climonfix5'
COUNTS = DOC / 'scopes'

def main():
    totals, sites, inputs = [], [], []
    for kind, expected in [('session', 176), ('hot', 52), ('parse', 40)]:
        posts = sorted(COUNTS.glob(kind + '-post-*.json'))
        assert len(posts) == expected, (kind, len(posts))
        for file in posts:
            arms = {arm: json.loads(file.with_name(file.name.replace('-post-', '-' + arm + '-')).read_text())
                    for arm in ('pre', 'c4', 'post')}
            a = arms['post']
            for arm, row in arms.items():
                build = json.loads((COUNTS / f'{arm}-{a["namespace"]}-{kind}-build.json').read_text())
                assert row['probe_sha256'] == build['sha256'], (file.name, arm, 'stale count')
                assert row['arm'] == arm and row['scope'] == kind
                for field in ('namespace', 'command', 'mode', 'batch', 'atomic'):
                    assert row[field] == a[field], (file.name, arm, field)
                assert sum(row['functions'].values()) == row['total'], (file.name, arm, 'symbol sum')
                arm_file = file.with_name(file.name.replace('-post-', '-' + arm + '-'))
                inputs.append(dict(file=str(arm_file.relative_to(ROOT)),
                                   sha256=hashlib.sha256(arm_file.read_bytes()).hexdigest()))
            identity = dict(scope=kind, namespace=a['namespace'], command=a['command'], mode=a['mode'],
                            batch=a['batch'], atomic=a['atomic'])
            comparable = 'header' not in a['command']
            record = dict(**identity, comparable_to_pre=comparable,
                          **{arm.upper(): arms[arm]['total'] for arm in arms})
            record.update(C4_minus_PRE=record['C4']-record['PRE'],
                          POST_minus_PRE=record['POST']-record['PRE'],
                          POST_minus_C4=record['POST']-record['C4'])
            totals.append(record)
            names = set().union(*(set(row['functions']) for row in arms.values()))
            for name in sorted(names):
                counts = {arm: arms[arm]['functions'].get(name, 0) for arm in arms}
                if len(set(counts.values())) == 1: continue
                sites.append(dict(**identity, symbol=name, PRE=counts['pre'], C4=counts['c4'], POST=counts['post'],
                                  C4_minus_PRE=counts['c4']-counts['pre'],
                                  POST_minus_PRE=counts['post']-counts['pre'],
                                  POST_minus_C4=counts['post']-counts['c4']))
    for name, rows in [('instruction-totals', totals), ('instruction-sites', sites)]:
        with (DOC/(name+'.csv')).open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    same = [r for r in totals if r['scope']=='session' and r['comparable_to_pre']]
    headers = [r for r in totals if r['scope']=='session' and not r['comparable_to_pre']]
    hot = [r for r in totals if r['scope']!='session']
    result = dict(total_triplets=len(totals),session_triplets=176,hot_triplets=92,
                  same_semantics_triplets=len(same),header_triplets=len(headers),
                  positive_session_deltas=[r for r in same if r['POST_minus_PRE']>0],
                  changed_hot_deltas=[r for r in hot if r['POST_minus_PRE']!=0 or r['C4_minus_PRE']!=0],
                  changed_hot_symbols=[r for r in sites if r['scope']!='session'],
                  header_POST_C4_range=[min(r['POST_minus_C4'] for r in headers),max(r['POST_minus_C4'] for r in headers)],
                  absent_unarmed_sites={},inputs=inputs)
    for arm in ('pre','c4','post'):
        observed={}
        for file in COUNTS.glob(f'session-{arm}-*.json'):
            row=json.loads(file.read_text())
            for symbol,count in row['functions'].items():
                if any(name in symbol for name in ('multi_pause_writes(', 'command_pause_write(')):
                    observed[symbol]=observed.get(symbol,0)+count
        result['absent_unarmed_sites'][arm]=observed
    result['pass'] = (not result['positive_session_deltas'] and not result['changed_hot_deltas']
                      and not result['changed_hot_symbols']
                      and not any(result['absent_unarmed_sites'].values()))
    assert len(inputs) == 804
    (DOC/'instruction-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='inputs'},indent=2))
    raise SystemExit(0 if result['pass'] else 1)

if __name__=='__main__':main()
