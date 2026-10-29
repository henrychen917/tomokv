#!/usr/bin/env python3
"""Delete only fully completed, hash-verified probes; retain their proof binding."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import exec1s_scope as s

def main():
    assert os.sched_getaffinity(0)<=set(range(48,64))
    dest=s.ROOT/'docs/exec1s/probe-retirements.json'
    retired=json.loads(dest.read_text()) if dest.exists() else []
    for directory in s.BUILD.iterdir():
        binary=directory/'probe'
        if not directory.is_dir() or not binary.exists():continue
        label=directory.name;arm,ns=label.rsplit('-',1)
        expected=24 if arm in ('PRE','POST','PAD-A') else (1 if arm.startswith('IDLE-') else
                 (4 if arm in ('IO-X3','IO-X4') else 2))
        build_path=s.OUT/(label+'-build.json');build=json.loads(build_path.read_text())
        completed=[]
        for path in s.OUT.glob(label+'-*.json'):
            if path==build_path:continue
            row=json.loads(path.read_text());log=path.with_suffix('.log')
            if not isinstance(row,dict) or row.get('probe_sha256')!=build['sha256'] or not log.exists():continue
            text=log.read_text()
            if 'Exit: 0\n' in text and ('COUNT '+str(row['total'])) in text:completed.append(path.name)
        if len(completed)!=expected:continue
        with binary.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        assert digest==build['sha256']
        retired=[r for r in retired if r['probe']!=label]
        retired.append(dict(probe=label,sha256=digest,completed_cases=completed,
                            build_receipt_sha256=hashlib.sha256(build_path.read_bytes()).hexdigest()))
        # Publish the binding before deleting the binary and fixture objects.
        s.save(dest,retired);shutil.rmtree(directory)
        print('RETIRED',label,len(completed),flush=True)

if __name__=='__main__':main()
