#!/usr/bin/env python3
"""Losslessly archive completed scope probes while retaining their identities."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'build/execfifo3'
RECORD=ROOT/'docs/execfifo3/probe-archives.json'

def digest(stream):
    value=hashlib.sha256()
    for chunk in iter(lambda:stream.read(1<<20),b''):value.update(chunk)
    return value.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore',action='store_true')
    parser.add_argument('--kind',choices=('commands','memory','all'),default='all')
    args=parser.parse_args()
    assert os.sched_getaffinity(0)<=set(range(96,112))
    rows=json.loads(RECORD.read_text()) if RECORD.exists() else []
    if args.restore:
        for row in rows:
            if args.kind!='all' and row['kind']!=args.kind:continue
            path=ROOT/row['path'];archive=ROOT/row['archive']
            assert path.is_relative_to(BASE) and archive.is_relative_to(BASE)
            if path.exists():
                with path.open('rb') as stream:assert digest(stream)==row['sha256']
                continue
            temp=path.with_suffix('.restoring')
            with gzip.open(archive,'rb') as source,temp.open('wb') as dest:
                shutil.copyfileobj(source,dest,1<<20)
            with temp.open('rb') as stream:assert digest(stream)==row['sha256']
            temp.chmod(row['mode']);temp.replace(path)
            print('Restored',path.relative_to(ROOT),flush=True)
        return
    saved=0
    for kind in ('commands','memory'):
        if args.kind not in ('all',kind):continue
        for path in sorted((BASE/(kind+'-scopes')).glob('*/probe')):
            stat=path.stat();archive=path.with_suffix('.gz');temp=path.with_suffix('.gz.tmp')
            with path.open('rb') as stream:before=digest(stream)
            receipt=ROOT/'docs/execfifo3'/kind/(path.parent.name+'-build.json')
            assert json.loads(receipt.read_text())['sha256']==before,path
            with path.open('rb') as source,gzip.open(temp,'wb',compresslevel=1) as dest:
                shutil.copyfileobj(source,dest,1<<20)
            with gzip.open(temp,'rb') as stream:assert digest(stream)==before
            temp.replace(archive)
            with archive.open('rb') as stream:compressed=digest(stream)
            row=dict(kind=kind,path=str(path.relative_to(ROOT)),archive=str(archive.relative_to(ROOT)),
                     sha256=before,archive_sha256=compressed,bytes=stat.st_size,
                     archive_bytes=archive.stat().st_size,mode=stat.st_mode&0o777)
            rows=[r for r in rows if r['path']!=row['path']]+[row]
            RECORD.write_text(json.dumps(rows,indent=2)+'\n')
            path.unlink();saved+=stat.st_size-archive.stat().st_size
            print('Archived',path.relative_to(ROOT),flush=True)
    print('Bytes saved:',saved)

if __name__=='__main__':main()
