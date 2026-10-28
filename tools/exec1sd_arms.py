#!/usr/bin/env python3
"""Frozen attribution arms, built serially; never starts a workload."""
import argparse, difflib, json, os, re, shutil, subprocess
from pathlib import Path
import exec1sd as d

def replace(path, old, new, count=1):
    text=path.read_text()
    assert text.count(old)==count, (path,old,text.count(old),count)
    path.write_text(text.replace(old,new))

def provenance(arm, source, ref):
    files=sorted(p.relative_to(source).as_posix() for p in (source/'src').rglob('*') if p.is_file())
    patch=[]
    for name in files:
        result=subprocess.run(['git','show',ref+':'+name],cwd=d.ROOT,capture_output=True,text=True)
        old=result.stdout if result.returncode==0 else ''
        new=(source/name).read_text()
        if old!=new:
            patch.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                fromfile='a/'+name if result.returncode==0 else '/dev/null',tofile='b/'+name))
    path=d.DOCS/(arm+'.patch');path.write_text(''.join(patch))
    d.save(d.DOCS/(arm+'-source.json'),dict(base=ref,patch=str(path),patch_sha256=d.sha(path),
        files={name:d.sha(source/name) for name in files}))

def finish(arm, source, ref, kinds):
    d.run(['make','-j32','all'],d.OUT/'evidence'/(arm+'-build.log'),cwd=source)
    d.record(arm,source,ref)
    provenance(arm,source,ref)
    d.probes(arm,source,kinds)
    d.traces(arm,kinds)
    d.retire(arm)
    shutil.rmtree(source)

def main():
    assert os.sched_getaffinity(0)<=set(range(64,96))
    p=argparse.ArgumentParser();p.add_argument('arm',choices=['X12','X3','X5','PRE','REUSE']);a=p.parse_args()
    arm=a.arm
    if arm=='X12':
        source=d.OUT/'X12-source';ref=(source/'SOURCE-COMMIT').read_text().strip()
        # Keep the pre-X5 state only until the isolated X3 arm has been prepared.
        for name in ('multi.inc','multi_execute.inc'):
            shutil.copy2(source/'src/cmd'/name,d.OUT/('X12-'+name))
        finish(arm,source,ref,'EXEC,IDLE')
    elif arm=='X3':
        source,ref=d.snapshot('d602c8c36',arm)
        for name in ('multi.inc','multi_execute.inc'):
            shutil.copy2(d.OUT/('X12-'+name),source/'src/cmd'/name)
        (source/'src/cmd/txn_key_queue.inc').write_bytes(subprocess.check_output(
            ['git','show','393d6ceb1:src/cmd/txn_key_queue.inc'],cwd=d.ROOT))
        old=d.ROOT/'src/cmd/multi.inc'
        text=old.read_text();start=text.index('void multi_ring_participants(');end=text.index('\nvoid multi_enqueue_node',start)
        path=source/'src/cmd/multi.inc'
        replace(path,'void multi_enqueue_node',text[start:end]+'\nvoid multi_enqueue_node')
        for anchor in ('            state.watch_arrived.fetch_add(1, std::memory_order_acq_rel);',
                       '        state.watch_phase_done.store(true, std::memory_order_release);'):
            replace(path,anchor,anchor+'\n        multi_ring_participants(state);')
        path=source/'src/cmd/multi_execute.inc'
        for anchor in ('        finish_command(state, command, stage, owner_thread_id);',
                       '                state.finalized.store(true, std::memory_order_release);'):
            replace(path,anchor,anchor+'\n        multi_ring_participants(state);')
        finish(arm,source,ref,'EXEC,IDLE')
        for path in d.OUT.glob('X12-multi*'):path.unlink()
    elif arm=='X5':
        source,ref=d.snapshot('d602c8c36',arm)
        for name in ('src/core/io_loop.h','src/core/reorder.cc','src/core/ex_loop.h',
                     'src/cmd/multi.inc','src/cmd/multi_execute.inc'):
            (source/name).write_bytes(subprocess.check_output(['git','show',ref+':'+name],cwd=d.ROOT))
        for name in ('src/core/io_loop.h','src/core/reorder.cc'):
            path=source/name;text=path.read_text()
            text,n=re.subn(r'(?m)^[ ]+if constexpr \(Fused && !SplitLocal\) \{\n'
                r'[ ]+if \(fused_executor_->fused_owner_ready\(\)\)\n'
                r'[ ]+did \+= fused_executor_->fused_owner_turn(?:<true>)?\(\);\n'
                r'[ ]+\}\n','',text)
            assert n==2,(name,n);path.write_text(text)
        replace(source/'src/core/ex_loop.h','        ring_fused_owner();\n','',2)
        for name in ('multi.inc','multi_execute.inc'):
            path=source/'src/cmd'/name;text=path.read_text()
            text,n=re.subn(r'^\s+multi_ring_participants\(state\);\n','\n',text,flags=re.M)
            assert n==2,(name,n)
            if name=='multi.inc':
                start=text.index('void multi_ring_participants(');end=text.index('void multi_enqueue_node',start)
                text=text[:start]+text[end:]
            path.write_text(text)
        finish(arm,source,ref,'EXEC,IDLE')
    elif arm=='PRE':
        source,ref=d.snapshot('393d6ceb1',arm)
        d.run(['make','-j32','all'],d.OUT/'evidence/PRE-build.log',cwd=source)
        d.record(arm,source,ref);provenance(arm,source,ref)
        d.probes(arm,source,'ORD,EXEC,RL');d.traces(arm,'ORD,EXEC,RL')
        d.retire(arm)
        # Keep PRE objects until the final common-image PAD-A link, then retire them.
    else:
        source,ref=d.snapshot('393d6ceb1',arm)
        patch=subprocess.check_output(['git','show','--format=','5fb8dc7b0','--','src'],cwd=d.ROOT,text=True)
        # This arm predates X5's slot mapping and X0's visit instrumentation.
        patch=patch.replace('state.shard_aborted[state.slot(shard.id())]','state.shard_aborted[shard.id()]')
        patch=patch.replace('+            TOMO_EXEC1S_VISIT();\n','')
        result=subprocess.run(['git','apply','--recount','--unsafe-paths','-'],input=patch,text=True,cwd=source,capture_output=True)
        assert result.returncode==0,result.stderr
        finish(arm,source,ref,'EXEC')

if __name__=='__main__':main()
