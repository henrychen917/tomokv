#!/usr/bin/env python3
"""Signed whole-scope and per-function counts; never infer a throughput result."""
import csv, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/wave11'; INS=DOC/'instructions'
KEY=('namespace','command','mode','batch','atomic')


def load(label, kind):
    record=json.loads((INS/label/kind).read_text())
    return record,{tuple(r[k] for k in KEY):r for r in record['rows']}


def main():
    comparisons=[
        ('headline-command','pre','final-post','all-complete-counts.json'),
        ('scriptfix3-command','scriptfix3','final-post','scripts-complete-counts.json'),
        ('scriptfix3-dispatch','scriptfix3-dispatch-v2','final-dispatch','scripts-complete-counts.json'),
        ('headline-session','pre-session','final-session','session-complete-counts.json'),
        ('headline-flip','pre-control','final-control','control-complete-counts.json'),
        ('scriptfix3-lua-collected','scriptfix3-gc','slot-inline-gc','scripts-lua-counts.json'),
    ]
    scopes=[]; functions=[]; summaries=[]
    for name,pre,post,kind in comparisons:
        before,a=load(pre,kind)
        after,b=load(post,'all-complete-counts.json' if post=='final-post' else kind)
        rows=[]
        for key in sorted(a):
            x,y=a[key],b[key]
            row=dict(comparison=name,**dict(zip(KEY,key)),before=x['total'],after=y['total'],delta=y['total']-x['total'])
            if name=='headline-flip':
                lane=json.loads((ROOT/'docs/flipfix5/counts'/f'control-post-{key[0]}-{key[1]}.json').read_text())
                row['isolated_lane']=lane['total'];row['integration_delta']=y['total']-lane['total']
                row['attribution']='cx-flipfix5 586b2304c; DEBUG witness bec4a1e20' if row['delta'] else 'unchanged idle path'
                assert row['integration_delta']==0,row
            for fn in sorted(set(x['functions'])|set(y['functions'])):
                n,m=x['functions'].get(fn,0),y['functions'].get(fn,0)
                if n!=m:functions.append(dict(comparison=name,**dict(zip(KEY,key)),function=fn,before=n,after=m,delta=m-n))
            rows.append(row)
        if name!='headline-flip':assert max(r['delta'] for r in rows)<=0,(name,[r for r in rows if r['delta']>0])
        if name=='headline-command':
            for row in rows:
                if row['command'] in ('GET','SET','INCR','MGET','MSET','READLOCAL-GET'):assert row['delta']==0,row
        summary=dict(name=name,cells=len(rows),minimum_delta=min(r['delta'] for r in rows),maximum_delta=max(r['delta'] for r in rows),
                     positive_cells=sum(r['delta']>0 for r in rows),before_server_sha256=before['server_sha256'],after_probe_server_sha256=after['server_sha256'])
        scopes+=rows;summaries.append(summary)
    # Unarmed classification/monitor methods must not execute, independent of
    # any savings in other functions that could hide a new notification cost.
    forbidden=('script_metadata_write(', 'command_pause_write(', 'multi_pause_write(',
               'notify_monitor_script(', 'script_monitor_context(', 'climon_monitor_script_format(')
    observed=[]; warm_work=[]
    for label,kind in [('final-post','all-complete-counts.json'),('final-dispatch','scripts-complete-counts.json'),('final-session','session-complete-counts.json')]:
        _,rows=load(label,kind)
        for key,row in rows.items():
            observed += [dict(arm=label,case=key,function=f,count=n) for f,n in row['functions'].items() if n and any(s in f for s in forbidden)]
            if row['command'].startswith(('EVAL','FCALL')):
                warm_work += [dict(arm=label,case=key,function=f,count=n) for f,n in row['functions'].items()
                              if n and any(s in f for s in ('sha1_hex(', 'eval_header(', 'validate_source(', 'compile_eval('))]
    assert not observed,observed
    assert not warm_work,warm_work
    for name,rows in [('instruction-cells',scopes),('instruction-functions',functions)]:
        fields=list(dict.fromkeys(k for row in rows for k in row))
        with (DOC/(name+'.csv')).open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    result=dict(summaries=summaries,unarmed_helper_entries=observed,warm_hash_parse_compile_entries=warm_work,
        note='Complete native walks all executable callbacks but counts selected production namespace and its C++ instantiations. Lua-collected also counts VM internals, with full collection before the warm call and GC enabled during it. External libraries and fixture glue are excluded; clocks fixed; REP counted once. EXEC-cross with one INCR necessarily touches one shard; its two/four-child cases cross owners.',
        positive_attribution='All positive whole-scope cells are active FLIP stages and exactly equal cx-flipfix5 POST. No positive integration residue; idle FLIP unchanged.')
    (DOC/'instruction-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    for row in summaries:print(row['name'],row['cells'],row['minimum_delta'],row['maximum_delta'])
    print('unarmed PAUSE/MONITOR helper entries:',len(observed))


if __name__=='__main__':main()
