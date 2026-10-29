#!/usr/bin/env python3
"""Count true scatter children without replacing any frozen merit binary."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import struct
import subprocess

import exec1sd as d


def allocated_sections(path):
    blob=path.read_bytes()
    assert blob[:6]==b'\x7fELF\x02\x01'
    offset=struct.unpack_from('<Q',blob,40)[0]
    size,count,names=struct.unpack_from('<HHH',blob,58)
    headers=[struct.unpack_from('<IIQQQQIIQQ',blob,offset+i*size) for i in range(count)]
    strings=headers[names];strings=blob[strings[4]:strings[4]+strings[5]]
    rows={}
    for h in headers:
        if not h[2]&2:continue
        name=strings[h[0]:strings.index(b'\0',h[0])].decode()
        # The build id may include debug-only source paths; it is not code or
        # program data. Every other allocated section must match exactly.
        if name=='.note.gnu.build-id':continue
        rows[name]=dict(type=h[1],flags=h[2],address=h[3],bytes=h[5],alignment=h[8],
            sha256=None if h[1]==8 else hashlib.sha256(blob[h[4]:h[4]+h[5]]).hexdigest())
    return rows


def main():
    assert os.sched_getaffinity(0)<=set(range(64,96))
    parser=argparse.ArgumentParser()
    parser.add_argument('arm',choices=['POST','PRE','MERGE','X12','X3','X5'])
    parser.add_argument('--reuse-probes',action='store_true')
    args=parser.parse_args();arm=args.arm
    frozen=next(x for x in json.loads((d.DOCS/'arms.json').read_text()) if x['arm']==arm)
    assert d.sha(frozen['binary'])==frozen['sha256']
    if arm=='POST':source=d.ROOT
    else:
        source,_=d.snapshot(frozen['source_commit'],arm)
        manifest=d.DOCS/(arm+'-source.json')
        if manifest.exists():
            manifest=json.loads(manifest.read_text())
            patch=d.DOCS/(arm+'.patch')
            assert d.sha(patch)==manifest['patch_sha256']
            if patch.stat().st_size:
                subprocess.run(['patch','--batch','--forward','-p1','-i',str(patch)],
                               cwd=source,check=True,stdout=subprocess.DEVNULL)
            assert all(d.sha(source/name)==digest for name,digest in manifest['files'].items())
        d.run(['make','-j32','all'],d.OUT/'evidence'/('SCAT-'+arm+'-build.log'),cwd=source)
    original=d.OUT/arm;rebuilt=source/'build/tomokv'
    before=allocated_sections(original);after=allocated_sections(rebuilt)
    mismatches=[name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)]
    binding=dict(arm=arm,frozen_sha256=d.sha(original),rebuilt_sha256=d.sha(rebuilt),
        all_allocated_sections_equal=not mismatches,mismatches=mismatches,sections=after,
        excluded='.note.gnu.build-id only; debug sections are not allocated',
        fixture_sha256=d.sha(d.ROOT/'tests/exec1sd_scope.cc'))
    binding_path=d.DOCS/('SCAT-'+arm+'-binding.json')
    if args.reuse_probes:
        previous=json.loads(binding_path.read_text())
        assert previous['fixture_sha256']==binding['fixture_sha256']
    d.save(binding_path,binding)
    assert not mismatches,mismatches
    s=d.scope_module();label='SCAT-'+arm
    s.ARMS[label]=(source,source/'build');s.FIXTURE=d.ROOT/'tests/exec1sd_scope.cc'
    for ns in ('normal','db0'):
        if not args.reuse_probes:s.build(label,ns)
        else:
            receipt=json.loads((s.OUT/(label+'-'+ns+'-build.json')).read_text())
            assert receipt['sha256']==d.sha(s.BUILD/(label+'-'+ns)/'probe')
            assert receipt['production_sha256']==binding['rebuilt_sha256']
    import crlffix_fast_scope as fast
    fast.scope=s;fast.OUT=s.OUT
    prepared={(label,ns):fast.prepare(label,ns) for ns in ('normal','db0')}
    cases=[(label,ns,'EXEC-scatter-'+shape,mode,n,atomic,-1)
           for ns in ('normal','db0') for shape in ('same','cross')
           for mode in ('1s','2s') for n in (1,2,4) for atomic in (0,1)]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows=list(pool.map(lambda case:fast.run(case,prepared),cases))
    path=d.DOCS/(label+'-counts.json');d.save(path,rows)
    retirements=[]
    for ns in ('normal','db0'):
        folder=s.BUILD/(label+'-'+ns)
        receipt=json.loads((s.OUT/(label+'-'+ns+'-build.json')).read_text())
        assert receipt['sha256']==d.sha(folder/'probe')
        assert all(x['probe_sha256']==receipt['sha256'] for x in rows if x['namespace']==ns)
        receipt.update(namespace=ns,count_sha256=d.sha(path),binding_sha256=d.sha(d.DOCS/(label+'-binding.json')))
        retirements.append(receipt)
        d.save(d.DOCS/(label+'-retirements.json'),retirements)
        shutil.rmtree(folder)
    for root in (s.BUILD,s.OUT):
        for path in root.glob(label+'-*'):
            if path.is_file():
                retirements.append(dict(retired=str(path),sha256=d.sha(path),bytes=path.stat().st_size))
                d.save(d.DOCS/(label+'-retirements.json'),retirements);path.unlink()
    if source!=d.ROOT:shutil.rmtree(source)
    print(arm,'48 true-scatter scopes PASS; frozen image unchanged',flush=True)


if __name__=='__main__':main()
