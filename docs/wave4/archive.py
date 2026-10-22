#!/usr/bin/env python3
"""Archive completed proof text, with a digest inventory of all included evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def archive(source,destination):
    rows=[]
    destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(destination/'artifacts.tar.gz','w:gz') as tar:
        for path in sorted(source.rglob('*')):
            if not path.is_file() or path.is_symlink():continue
            relative=str(path.relative_to(source));size=path.stat().st_size
            with path.open('rb') as stream:prefix=stream.read(4096)
            if prefix.startswith(b'\x7fELF') or path.suffix in ('.o','.a','.objdump') or b'\0' in prefix:
                rows.append(dict(path=relative,bytes=size,included=False,reason='binary/object/disassembly; linked inputs separately identified'))
                continue
            if size>16*1024*1024:
                rows.append(dict(path=relative,bytes=size,included=False,reason='large scratch payload; retained in run directory'))
                continue
            data=path.read_bytes()
            try:data.decode('utf-8')
            except UnicodeDecodeError:
                rows.append(dict(path=relative,bytes=size,included=False,reason='binary scratch payload'))
                continue
            rows.append(dict(path=relative,bytes=size,included=True,sha256=hashlib.sha256(data).hexdigest()))
            tar.add(path,arcname=relative,recursive=False)
    manifest=dict(source=str(source),files=rows,archive_sha256=hashlib.sha256((destination/'artifacts.tar.gz').read_bytes()).hexdigest())
    (destination/'artifacts.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(source,len(rows),'files;',sum(r['included'] for r in rows),'text receipts')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('destination',type=Path);a=p.parse_args()
    archive(a.source,a.destination)
