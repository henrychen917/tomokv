#!/usr/bin/env python3
"""Retain completed jobs' persistence data before removing their loose copies."""
import hashlib
import json
import os
from pathlib import Path
import tarfile
from wave14 import ROOT, BUILD, DOC, save, sha


def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    dest=BUILD/'data-archives';dest.mkdir(exist_ok=True)
    index=DOC/'data-archives.json'
    records=json.loads(index.read_text()) if index.exists() else []
    saved={r['job_directory'] for r in records}
    for done in sorted((ROOT/'build').glob('gate-run.*/jobs/*/done')):
        job=done.parent
        if str(job) in saved or not (job/'cleaned').exists():continue
        files=[p for p in job.rglob('*') if p.is_file() and not p.is_symlink()
               and p.suffix in ('.tomo','.aof','.rdb')]
        if sum(p.stat().st_size for p in files)<64*1024*1024:continue
        members=[dict(path=str(p.relative_to(job)),bytes=p.stat().st_size,sha256=sha(p)) for p in files]
        archive=dest/(job.parent.parent.name+'-'+job.name+'.tar.gz')
        assert not archive.exists()
        with tarfile.open(archive,'w:gz',compresslevel=1) as output:
            for p,r in zip(files,members):output.add(p,arcname=r['path'],recursive=False)
        with tarfile.open(archive,'r:gz') as stored:
            assert stored.getnames()==[r['path'] for r in members]
            for r in members:
                with stored.extractfile(r['path']) as stream:
                    assert hashlib.file_digest(stream,'sha256').hexdigest()==r['sha256']
        records.append(dict(job_directory=str(job),done=done.read_text(),
            archive=str(archive.relative_to(ROOT)),archive_sha256=sha(archive),
            original_bytes=sum(r['bytes'] for r in members),archive_bytes=archive.stat().st_size,
            members=members))
        save(index,records)
        for p,r in zip(files,members):
            assert sha(p)==r['sha256']
            p.unlink()
        print(job.name,records[-1]['original_bytes'],'->',archive.stat().st_size,flush=True)


if __name__=='__main__':main()
