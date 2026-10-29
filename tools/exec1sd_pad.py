#!/usr/bin/env python3
"""Type-A common-image control, using headline PRE and the final production POST."""
import json, os, shutil
import exec1sd as d
import exec1s_pad as pad

def main():
    assert os.sched_getaffinity(0)<=set(range(64,96))
    record=pad.build(d.OUT/'PRE-source',d.ROOT,d.OUT,d.DOCS/'pad-a.json')
    manifest=json.loads((d.DOCS/'arms.json').read_text())
    pre=next(row for row in manifest if row['arm']=='PRE')
    post=next(row for row in manifest if row['arm']=='POST')
    assert record['release_sha256']==post['sha256']
    for name,source in (('POST-layout',post),('PAD-A',pre)):
        binary=d.OUT/name
        manifest=[row for row in manifest if row['arm']!=name]
        manifest.append(dict(arm=name,source_commit=source['source_commit'],binary=str(binary),
            sha256=d.sha(binary),bytes=binary.stat().st_size,
            control='A: PRE behaviour in the exact combined POST-layout image; larger than release POST'))
    d.save(d.DOCS/'arms.json',manifest)
    (d.DOCS/'SHA256SUMS').write_text(''.join(f"{row['sha256']}  {row['binary']}\n" for row in manifest))
    shutil.rmtree(d.OUT/'pad-objects')
    shutil.rmtree(d.OUT/'PRE-source')

if __name__=='__main__':main()
