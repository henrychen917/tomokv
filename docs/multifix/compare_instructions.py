#!/usr/bin/env python3
"""Require a matched, complete PRE/POST command-scope comparison."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/multifix/instructions'
FIELDS=('namespace','command','mode','batch','atomic','threshold')
def index(name):
    rows=json.loads((OUT/f'results-{name}.json').read_text())
    out={tuple(r[k] for k in FIELDS):r for r in rows}
    assert len(out)==len(rows)==72,(name,len(rows),len(out))
    return out
pre,post=index('pre'),index('final')
assert pre.keys()==post.keys()
rows=[]
for key,a in pre.items():
    b=post[key]
    rows.append(dict(zip(FIELDS,key),pre=a['total'],post=b['total'],delta=b['total']-a['total'],
                     pre_clock_calls=a['clock_calls'],post_clock_calls=b['clock_calls'],
                     pre_probe_sha256=json.loads((OUT/('pre-'+a['namespace']+'-build.json')).read_text())['sha256'],post_probe_sha256=b['binary_sha256']))
summary=[]
for command in ('GET','SET','INCR','MGET','MSET'):
    for ns in ('normal','db0'):
        matches=[r for r in rows if r['command']==command and r['namespace']==ns]
        summary.append(dict(command=command,namespace=ns,cases=len(matches),
                            min_delta=min(r['delta'] for r in matches),max_delta=max(r['delta'] for r in matches)))
report=dict(scope='Linked production exec_batch_prefetched through named tomo/tomo_db0 routines; excludes fixture, network parse, read-local lane and out-of-scope library callees.',
            modes=['1s','2s'],batch_sizes=[1,32],read_local=0,
            atomic='1, plus 0 for MSET',slowlog_threshold='-1/10000 for single-key commands; -1 for MGET/MSET',
            cases=len(rows),all_zero_added_instructions=all(r['delta']<=0 for r in rows),
            all_clock_calls_unchanged=all(r['pre_clock_calls']==r['post_clock_calls'] for r in rows),
            summary=summary,rows=rows)
(OUT/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
raise SystemExit(0 if report['all_zero_added_instructions'] and report['all_clock_calls_unchanged'] else 1)
