#!/usr/bin/env python3
"""Bounded warm-call instruction census using linked production objects, no rates.

The namespace domain reproduces wave10. The lua domain additionally enters all
vendored VM functions, so redis.call callbacks are not hidden by skipping pcall.
Each case asserts its exact reply and runs one warm-up and one counted call.
"""
import argparse, bisect, concurrent.futures, gzip, hashlib, json, os, re, shlex, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build/scriptfix3'
DOC=ROOT/'docs/scriptfix3/instructions'
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n')
def symbols(binary):
    rows=[]
    for line in subprocess.check_output(['nm','-S','--defined-only',str(binary)],text=True).splitlines():
        f=line.split()
        if len(f)==4 and f[2] in ('t','T','w','W'): rows.append([int(f[0],16),int(f[0],16)+int(f[1],16),f[3]])
    names=subprocess.check_output(['c++filt'],input='\n'.join(r[2] for r in rows),text=True).splitlines()
    return [r+[name] for r,name in zip(rows,names)]
def build(label,source,objects,namespace):
    dest=BUILD/'scopes'/(label+'-'+namespace);dest.mkdir(parents=True,exist_ok=True)
    recipe=subprocess.check_output(['make','-C',str(source),'BUILD_ROOT='+str(objects),'-n','-W',str(objects/'src/main.o'),'all'],text=True)
    link=shlex.split(next(l for l in recipe.splitlines() if ' -o '+str(objects/'tomokv')+' ' in l))
    flags=['g++','-std=c++20','-O2','-g','-march=native','-pthread','-DTOMO_JEMALLOC','-I'+str(source)]
    if namespace=='db0':flags+=['-DTOMO_SINGLE_DATABASE=1','-Dtomo=tomo_db0']
    compile=flags+['-c',str(ROOT/'tests/scriptfix3_scope.cc'),'-o',str(dest/'probe.o')]
    rename=['objcopy','--redefine-sym','main=scriptfix3_original_main',str(objects/'db0/src/main.o'),str(dest/'original-main.o')]
    link=[str(dest/'original-main.o') if a==str(objects/'db0/src/main.o') else a for a in link]
    link+=[str(dest/'probe.o')];link[link.index('-o')+1]=str(dest/'probe')
    with (dest/'build.log').open('w') as log:
        for cmd in (compile,rename,link):subprocess.run(cmd,cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
    save(DOC/label/(namespace+'-build.json'),dict(compile=compile,rename=rename,link=link,probe_sha256=sha(dest/'probe'),server_sha256=sha(objects/'tomokv'),fixture_sha256=sha(ROOT/'tests/scriptfix3_scope.cc')))
    return dest/'probe'
def prepare(binary,objects,namespace,domain):
    syms=symbols(binary);prefix='tomo::' if namespace=='normal' else 'tomo_db0::'
    # Lua-inclusive walks every function in the executable, including fixture
    # callback wrappers. Otherwise drain_tasks(test_lambda) hides entire later
    # scatter phases. Fixture instructions remain uncounted, as do shared libs.
    ranges=[]
    for r in syms:
        fixture='CoreConcurrencyTest::' in r[3] or r[2] in ('main','_Z11scope_beginv','_Z9scope_endv')
        if domain=='lua':ranges.append(r+[not fixture])
        elif prefix in r[3] and not fixture:ranges.append(r+[True])
    for line in subprocess.check_output(['readelf','-SW',str(binary)],text=True).splitlines():
        m=re.search(r'\]\s+\.rlfence\s+PROGBITS\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)',line)
        if m:
            start,size=(int(x,16) for x in m.groups());ranges.append([start,start+size,'.rlfence',prefix+'[asm .rlfence]',True])
    ranges.sort();rf=binary.parent/(domain+'.ranges')
    rf.write_text(''.join(f'{r[0]:x} {r[1]:x} {int(r[4])}\n' for r in ranges))
    named={r[2]:r[0] for r in syms}
    dump=subprocess.check_output(['objdump','-d','-j','.plt','-j','.plt.sec','-j','.plt.got',str(binary)],text=True)
    m=re.search(r'([0-9a-f]+) <clock_gettime@plt>:',dump)
    return ranges,[str(BUILD/'trace'),str(binary),str(rf),f'{named["_Z11scope_beginv"]:x}',f'{named["_Z9scope_endv"]:x}',m[1] if m else '0'],sha(binary)
def trace(prepared,label,namespace,domain,command,mode,batch,atomic):
    ranges,argv,digest=prepared
    target=DOC/label/domain/('-'.join(map(str,(namespace,command,mode,batch,atomic)))+'.json')
    if target.exists():
        old=json.loads(target.read_text())
        if old['probe_sha256']==digest and old.get('tracer_sha256')==sha(BUILD/'trace'):return old
    run=subprocess.run(argv+[command,mode,str(batch),str(atomic),'-1'],text=True,capture_output=True,timeout=600)
    if run.returncode:raise RuntimeError(str(target)+' '+run.stderr+run.stdout[-1000:])
    record=json.loads(next(l[6:] for l in run.stdout.splitlines() if l.startswith('TRACE=')))
    starts=[r[0] for r in ranges];functions={}
    for pc,n in record['sites'].items():
        at=int(pc,16);i=bisect.bisect_right(starts,at)-1;assert i>=0 and at<ranges[i][1]
        name=ranges[i][3];functions[name]=functions.get(name,0)+n
    row=dict(arm=label,namespace=namespace,domain=domain,command=command,mode=mode,batch=batch,atomic=atomic,
        probe_sha256=digest,tracer_sha256=sha(BUILD/'trace'),total=sum(functions.values()),functions=functions,clock_calls=record['clock_calls'],excluded_calls=record['excluded_calls'])
    save(target,row)
    with gzip.GzipFile(filename=str(target)+'.sites.gz',mode='wb',mtime=0) as f:f.write(json.dumps(record).encode())
    target.with_suffix('.log').write_text(' '.join(argv+[command,mode,str(batch),str(atomic),'-1'])+'\n'+run.stderr+'\n'.join(l for l in run.stdout.splitlines() if not l.startswith('TRACE='))+'\nCOUNT '+str(row['total'])+'\n')
    print(label,domain,namespace,command,mode,atomic,row['total'],flush=True)
    return row
def main():
    assert os.sched_getaffinity(0)<=set(range(32,48))
    os.environ['LC_ALL']='C'
    p=argparse.ArgumentParser();p.add_argument('label');p.add_argument('--source',type=Path,default=ROOT);p.add_argument('--objects',type=Path,default=ROOT/'build');p.add_argument('--domain',choices=('namespace','lua','both'),default='both');p.add_argument('--only',default='');p.add_argument('--no-build',action='store_true');a=p.parse_args()
    a.source=a.source.resolve();a.objects=a.objects.resolve()
    BUILD.mkdir(exist_ok=True);subprocess.run(['g++','-std=c++20','-O2','-g','tools/scriptfix3_trace.cc','-o',str(BUILD/'trace')],check=True)
    commands=[v+'-'+place+header for v in ('EVAL','EVALSHA','FCALL') for place in ('single','cross') for header in ('','-header')]
    commands+=['GET','SET','INCR','MGET','MSET']
    if a.only:commands=a.only.split(',')
    rows=[]
    for ns in ('normal','db0'):
        binary=BUILD/'scopes'/(a.label+'-'+ns)/'probe' if a.no_build else build(a.label,a.source,a.objects,ns)
        for domain in (('namespace','lua') if a.domain=='both' else (a.domain,)):
            prepared=prepare(binary,a.objects,ns,domain)
            cases=[(c,m,b,at) for c in commands for m in ('1s','2s') for b in ((1,32) if c in ('GET','SET','INCR','MGET','MSET') else (1,)) for at in ((0,1) if c not in ('GET','SET','INCR','MGET') else (1,))]
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                rows+=list(pool.map(lambda case:trace(prepared,a.label,ns,domain,*case),cases))
    save(DOC/a.label/'counts.json',dict(server_sha256=sha(a.objects/'tomokv'),tracer_sha256=sha(BUILD/'trace'),rows=rows))
if __name__=='__main__':main()
