#!/usr/bin/env python3
"""Freeze release arms and the explicit type-A common-image control pair."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import exec1s_pad as pad
from lbstall_artifacts import Elf

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/execfifo3';DOCS=ROOT/'docs/execfifo3'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    assert os.sched_getaffinity(0)<=set(range(96,112))
    subprocess.run(['make','-q','all'],cwd=ROOT,check=True)
    shutil.copy2(OUT/'pre-source/build/tomokv',OUT/'PRE-rebuilt')
    shutil.copy2(OUT/'original-artifacts/PRE',OUT/'PRE')
    shutil.copy2(OUT/'original-artifacts/FIFO',OUT/'FIFO')
    shutil.copy2(ROOT/'build/tomokv',OUT/'POST')
    assert sha(OUT/'PRE')=='735cbffb1afa279a4b47ddd42411cbc5d4e25a38653c01150ee15edc5fd6ebca'
    assert sha(OUT/'FIFO')=='ee5aee2768e0e8f8899a90f628a45f8a2ec47cebe3e405dbf9cf21210e9d0b0a'
    record=pad.build(OUT/'pre-source',ROOT,OUT,DOCS/'pad-a.json')
    rows=[]
    for name in ('PRE','FIFO','POST','POST-layout','PAD-A'):
        path=OUT/name;elf=Elf(path);text=elf.section_data(elf.names.index('.text'))
        rows.append(dict(arm=name,path=str(path.relative_to(ROOT)),sha256=sha(path),bytes=path.stat().st_size,
                         text_bytes=len(text),text_sha256=hashlib.sha256(text).hexdigest()))
    original=Elf(OUT/'original-artifacts/PRE');rebuilt=Elf(OUT/'PRE-rebuilt')
    equal=original.section_data(original.names.index('.text'))==rebuilt.section_data(rebuilt.names.index('.text'))
    assert equal,'Reconstructed PRE text differs from the frozen reference'
    rows.append(dict(arm='PRE-original-reference',path=str((OUT/'original-artifacts/PRE').relative_to(ROOT)),
        sha256=sha(OUT/'original-artifacts/PRE'),text_equal_to_rebuild=equal))
    rows.append(dict(arm='PRE-rebuilt-reference',path=str((OUT/'PRE-rebuilt').relative_to(ROOT)),
        sha256=sha(OUT/'PRE-rebuilt'),text_equal_to_original=equal))
    (DOCS/'arms.json').write_text(json.dumps(rows,indent=2)+'\n')
    (DOCS/'SHA256SUMS').write_text(''.join(r['sha256']+'  '+r['path']+'\n' for r in rows[:5]))
    shutil.rmtree(OUT/'pad-objects')
    print('Frozen arms:',[(r['arm'],r['sha256']) for r in rows])

if __name__=='__main__':main()
