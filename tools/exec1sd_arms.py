#!/usr/bin/env python3
"""Frozen attribution arms, built serially; never starts a workload."""
import argparse, difflib, json, os, shutil, subprocess
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
    if arm in ('X12','X3','X5'):
        # The committed source receipt makes every isolated arm reconstructible
        # after all intermediate source trees and objects have been retired.
        receipt=json.loads((d.DOCS/(arm+'-source.json')).read_text())
        source,ref=d.snapshot(receipt['base'],arm)
        patch=d.DOCS/(arm+'.patch')
        assert d.sha(patch)==receipt['patch_sha256']
        subprocess.run(['patch','--batch','--forward','-p1','-i',str(patch)],
                       cwd=source,check=True,stdout=subprocess.DEVNULL)
        assert all(d.sha(source/name)==digest for name,digest in receipt['files'].items())
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
        # git apply from a nested snapshot silently filters repository-relative
        # paths. Build the two source edits explicitly and assert their presence.
        current=(d.ROOT/'src/store/flatstore_atomic.inc').read_text()
        start=current.index('    // Owner-only newest-match lookup')
        end=current.index('    // A conservative blind-group count:',start)
        helper=current[start:end].replace('            TOMO_EXEC1S_VISIT();\n','')
        path=source/'src/store/flatstore_atomic.inc'
        anchor='    template <typename Visit>\n    void atomic_visit_unit_records('
        replace(path,anchor,helper+anchor)
        path=source/'src/cmd/multi.inc';text=path.read_text()
        start=text.index('    bool private_head = false;')
        end=text.index('    if (private_head) {',start)
        text=text[:start]+'''    const bool private_head = shard.store().atomic_reuses_transaction(
        hash, key, &state.decision.epoch, &state.shard_aborted[shard.id()]);
'''+text[end:]
        path.write_text(text)
        assert 'atomic_reuses_transaction(' in path.read_text()
        finish(arm,source,ref,'EXEC')

if __name__=='__main__':main()
