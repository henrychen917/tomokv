#!/usr/bin/env python3
"""Losslessly archive superseded images; never touch the five final arms."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT/'docs/execfifo3'
BASE=ROOT/'build/execfifo3'
RECORD=DOCS/'image-archives.json'

def digest(stream):
    value=hashlib.sha256()
    for chunk in iter(lambda:stream.read(1<<20),b''):value.update(chunk)
    return value.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore',action='store_true');args=parser.parse_args()
    assert os.sched_getaffinity(0)<=set(range(96,112))
    stage=json.loads((DOCS/'stage1-arms.json').read_text())
    final=json.loads((DOCS/'arms.json').read_text())
    expected={BASE/'stage1'/row['arm']:row['sha256'] for row in stage
              if row['arm'] in ('POST','POST-layout','PAD-A')}
    expected[BASE/'original-artifacts/PRE']=next(row['sha256'] for row in final
                                               if row['arm']=='PRE-original-reference')
    expected[BASE/'original-artifacts/FIFO']=next(row['sha256'] for row in final
                                                if row['arm']=='FIFO')
    assert len(expected)==5
    rows=json.loads(RECORD.read_text()) if RECORD.exists() else []
    saved=0
    for path,sha in expected.items():
        archive=path.with_suffix('.gz')
        old=next((row for row in rows if row['path']==str(path.relative_to(ROOT))),None)
        if path.exists():
            with path.open('rb') as stream:assert digest(stream)==sha,path
            if args.restore:continue
        else:
            assert old and old['sha256']==sha,path
            with archive.open('rb') as stream:assert digest(stream)==old['archive_sha256']
            if not args.restore:continue
        if args.restore:
            temp=path.with_suffix('.restoring')
            with gzip.open(archive,'rb') as source,temp.open('wb') as dest:
                shutil.copyfileobj(source,dest,1<<20)
            with temp.open('rb') as stream:assert digest(stream)==sha
            temp.chmod(old['mode']);temp.replace(path)
            print('Restored',path.relative_to(ROOT),flush=True)
            continue
        stat=path.stat();temp=path.with_suffix('.gz.tmp')
        with path.open('rb') as source,gzip.open(temp,'wb',compresslevel=1) as dest:
            shutil.copyfileobj(source,dest,1<<20)
        with gzip.open(temp,'rb') as stream:assert digest(stream)==sha
        temp.replace(archive)
        with archive.open('rb') as stream:compressed=digest(stream)
        row=dict(path=str(path.relative_to(ROOT)),archive=str(archive.relative_to(ROOT)),
                 sha256=sha,archive_sha256=compressed,bytes=stat.st_size,
                 archive_bytes=archive.stat().st_size,mode=stat.st_mode&0o777)
        rows=[r for r in rows if r['path']!=row['path']]+[row]
        RECORD.write_text(json.dumps(rows,indent=2)+'\n')
        path.unlink();saved+=stat.st_size-archive.stat().st_size
        print('Archived',path.relative_to(ROOT),flush=True)
    print('Bytes saved:',saved)

if __name__=='__main__':main()
