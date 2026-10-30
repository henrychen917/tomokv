#!/usr/bin/env python3
"""Seven single-root substitutions, compiled with production flags and scored by gate.sh."""
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave11'
BUILD = ROOT / 'build/wave11/regressions'
CONTROL = ROOT / 'docs/climonfix4/tcl-controls'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path, data): path.write_text(json.dumps(data, indent=2)+'\n')

def main():
    os.sched_setaffinity(0,set(range(64,96)))
    spec=importlib.util.spec_from_file_location('c4_controls',ROOT/'docs/climonfix4/root_mutants.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    changes=dict(module.CHANGES)
    changes['MONITOR-SCRIPT-CMDS']=('scripting.cc',
        'notify_monitor_script(*context.shard, *context.parent, nested, context.monitor_multi_order);',
        '(void)context.monitor_multi_order; // planted: omit nested MONITOR delivery')
    changes={'PAUSE-BLOCKED-COUNT':('climon.cc','srv_->blocking_client_parked();','/* planted: omit pause count */'), **changes}
    targets=sys.argv[1:] or ['CLIENT-LIST-CMD-NAME']
    binary=ROOT/'build/wave11/tomokv-POST'
    post_sha=sha(binary)
    subprocess.run(['make','-q','all'],cwd=ROOT,check=True)
    assert post_sha==sha(ROOT/'build/tomokv')
    recipe=subprocess.check_output(['make','-n','-W','build/src/main.o','all'],cwd=ROOT,text=True)
    template=shlex.split(next(s for s in recipe.splitlines() if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
    witnesses=json.loads((CONTROL/'witnesses.json').read_text())
    record_path=DOC/'isolated-regressions.json'
    results=json.loads(record_path.read_text()) if record_path.exists() else []
    BUILD.mkdir(parents=True,exist_ok=True)
    for root in targets:
        if any(r['root']==root and r['post_sha256']==post_sha and r['verified'] for r in results):continue
        unit,before,after=changes[root]
        dest=BUILD/root;dest.mkdir(exist_ok=True)
        source=dest/'source'
        shutil.copytree(ROOT/'src',source/'src',dirs_exist_ok=True)
        shutil.copytree(ROOT/'third_party',source/'third_party',dirs_exist_ok=True)
        path=source/'src/cmd'/unit;original=path.read_text()
        assert original.count(before)==1,(root,before)
        changed=original.replace(before,after)
        if root=='PAUSE-BLOCKED-COUNT':
            changed=changed.replace('srv_->blocking_client_unparked();','/* paired count removal */')
        path.write_text(changed)
        row=dict(root=root,post_sha256=post_sha,source='src/cmd/'+unit,before=before,after=after,
                 source_before_sha256=hashlib.sha256(original.encode()).hexdigest(),source_after_sha256=sha(path),compile=[])
        link=list(template);commands=[]
        for ns in ('normal','db0'):
            old='build/'+('db0/' if ns=='db0' else '')+'src/cmd/'+unit.removesuffix('.cc')+'.o'
            recipe=subprocess.check_output(['make','-n','-W','src/cmd/'+unit,old],cwd=ROOT,text=True)
            command=shlex.split(next(s for s in recipe.splitlines() if s.startswith('g++ ') and ' -o '+old in s))
            obj=dest/(ns+'.o');command[command.index('src/cmd/'+unit)]=str(path)
            command[command.index('-o')+1]=str(obj)
            link[link.index(old)]=str(obj);commands.append((command,dest/(ns+'.log')))
            row['compile'].append(command)
        def compile_one(item):
            command,log=item
            with log.open('w') as stream:subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(compile_one,commands))
        mutant=dest/'tomokv';link[link.index('-o')+1]=str(mutant)
        with (dest/'link.log').open('w') as stream:subprocess.run(link,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        row.update(binary_sha256=sha(mutant),link=link)
        shutil.rmtree(source)
        name='negative-'+root.lower()
        command=['python3',str(DOC/'run_jobs.py'),name,'redis_tcl','--binary',str(mutant),
                 '--manifest',str(CONTROL/(root+'.json')),'--single-slot','--port','20080']
        with (dest/'gate.log').open('w') as stream:
            rc=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT).returncode
        receipt=json.loads((DOC/'jobs'/(name+'.json')).read_text())
        run=Path(receipt['artifacts']);unit_name,witness=witnesses[root]
        row.update(exit=rc,modes={},verified=rc==1)
        for mode in ('1s','2s'):
            result_path=run/'jobs/redis_tcl'/('redis-tcl-'+mode)/unit_name/'result.json'
            result=json.loads(result_path.read_text())
            statuses=[e['status'] for e in result['events'] if e['test']==witness+' in tests/'+unit_name+'.tcl']
            deadline=(not result['complete'] and result['exit_code']!=0 and statuses[-1:]==['testing']
                      and 'TIMEOUT' in result_path.with_name('suite.log').read_text())
            verified='testing' in statuses and 'ok' not in statuses and ('err' in statuses or deadline)
            row['modes'][mode]=dict(statuses=statuses,deadline=deadline,verified=verified)
            row['verified'] &= verified
        results.append(row);save(record_path,results)

        mutant.unlink()
        for obj in dest.glob('*.o'):obj.unlink()
        row['pruned']=True;save(record_path,results)
        print(root,'PASS' if row['verified'] else 'FAIL',flush=True)
    assert all(r['verified'] for r in results if r['post_sha256']==post_sha)

if __name__=='__main__':main()
