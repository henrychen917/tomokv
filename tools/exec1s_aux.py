#!/usr/bin/env python3
"""Bounded allocation and linked IO scopes, no network or rate measurements."""
import argparse,concurrent.futures,hashlib,json,os,shutil,subprocess
from pathlib import Path
import exec1s_scope as scope
from exec1s_pad import recipe
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def allocations():
    records={}
    for arm,source in [('PRE',ROOT/'build/exec1s/pre-source'),('POST',ROOT)]:
        objects=source/'build';link=recipe(source,objects)
        for ns in ['normal','db0']:
            flags=['g++','-std=c++20','-O2','-g','-march=native','-pthread','-DTOMO_JEMALLOC','-I'+str(source)]
            if ns=='db0':flags+=['-DTOMO_SINGLE_DATABASE=1','-Dtomo=tomo_db0']
            selected=[]
            for x in link:
                if not x.endswith('.o') or x.endswith('/src/main.o') or x.endswith('/src/core/version.o'):continue
                db0='/db0/' in x
                if ns=='normal' and db0:continue
                if x.endswith('/src/cmd/xshard.o') and db0==(ns=='db0'):continue
                selected.append(x)
            binary=ROOT/'build/exec1s'/(arm+'-allocation-'+ns)
            if binary.exists():
                archived=binary.with_name(binary.name+'-'+sha(binary)[:12])
                if not archived.exists():shutil.copy2(binary,archived)
            cmd=flags+[str(ROOT/'tests/exec1s_alloc_scope.cc')]+selected+['-o',str(binary),'-ljemalloc','-luring','-pthread','-lssl','-lcrypto','-lm']
            with (ROOT/'build/exec1s-evidence'/(arm+'-allocation-'+ns+'-build.log')).open('w') as f:
                subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
            rows=[]
            for mode,shards in [('2s','16'),('1s','64')]:
                output=subprocess.check_output(['taskset','-c','80-87',str(binary),mode,shards],text=True)
                rows.append(json.loads(next(line for line in output.splitlines() if line.startswith('{'))))
            row=dict(arm=arm,namespace=ns,command=cmd,sha256=sha(binary),cpu_affinity="80-87",results=rows,
                     production_binary=str(objects/'tomokv'),production_sha256=sha(objects/'tomokv'))
            scope.save(ROOT/'docs/exec1s'/(arm+'-allocation-'+ns+'.json'),row);records[arm,ns]=rows
    comparisons=[]
    for ns in ['normal','db0']:
        pre=records['PRE',ns][1]['prepare_total_bytes'];post=records['POST',ns][1]['prepare_total_bytes'];other=records['POST',ns][0]['prepare_total_bytes']
        comparisons.append(dict(namespace=ns,PRE_1s_64=pre,POST_1s_64=post,POST_2s_16=other,
            geometry_ratio=post/other,geometry_pass=post<=1.2*other,pre_ratio=post/pre,quarter_pass=post<=.25*pre))
    scope.save(ROOT/'docs/exec1s/allocation-comparison.json',comparisons)
    print('allocation',comparisons,flush=True)
def io(build,count):
    scope.FIXTURE=ROOT/'tests/exec1s_io_scope.cc'
    scope.ARMS['IO-PRE']=scope.ARMS['PRE'];scope.ARMS['IO-POST']=(ROOT,ROOT/'build')
    if build:
        for arm in ['IO-PRE','IO-POST']:
            for ns in ['normal','db0']:scope.build(arm,ns)
    if count:
        cases=[(arm,ns,'EXEC',mode,1,1,-1) for arm in ['IO-PRE','IO-POST'] for ns in ['normal','db0'] for mode in ['1s','2s']]
        with concurrent.futures.ThreadPoolExecutor(8) as pool:rows=list(pool.map(scope.trace,cases))
        comparisons=[]
        for r in rows:
            if r['arm']!='IO-POST':continue
            old=next(x for x in rows if x['arm']=='IO-PRE' and x['namespace']==r['namespace'] and x['mode']==r['mode'])
            comparisons.append(dict(namespace=r['namespace'],mode=r['mode'],pre=old['total'],post=r['total'],delta=r['total']-old['total']))
        scope.save(ROOT/'docs/exec1s/io-counts.json',dict(scope='multi_dispatch_entry through preparation/dispatch; queueing is outside',cases=comparisons))
def main():
    assert os.sched_getaffinity(0)<=set(range(80,96))
    p=argparse.ArgumentParser();p.add_argument('--allocations',action='store_true');p.add_argument('--io-build',action='store_true');p.add_argument('--io-count',action='store_true');a=p.parse_args()
    if a.allocations:allocations()
    if a.io_build or a.io_count:io(a.io_build,a.io_count)
if __name__=='__main__':main()
