#!/usr/bin/env python3
"""Build frozen writeback arms and PAD A by changing only cold ELF immediates.

No server execution. Every arm has identical sections, symbol addresses and hot
text. PAD A pins the original half-rule behavior with the candidate layout;
common dispatch overhead is separately priced by pol1 versus 9c4717da0.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT/'build'
ARMS = {'tomokv': 0, 'tomokv-pol0': 1, 'tomokv-pol1': 2,
        'tomokv-pad': 1 << 31, 'tomokv-auto2s-probe': 1 << 8}


def receipt(path):
    e = Elf(path)
    return dict(path=str(path), sha256=hashlib.sha256(e.data).hexdigest(),
                text=e.sections[e.names.index('.text')][5],
                tdata=e.sections[e.names.index('.tdata')][5],
                tbss=e.sections[e.names.index('.tbss')][5])


def arms():
    original = BUILD/'tomokv'; e=Elf(original)
    symbols=[s for s in e.symbols if s['name'].endswith('7wb_rule9build_armEv')]
    assert len(symbols)==2, [s['name'] for s in symbols]
    offsets=[]
    for s in symbols:
        body=e.body(s)
        prefix=b'\xf3\x0f\x1e\xfa' if body.startswith(b'\xf3\x0f\x1e\xfa') else b''
        assert body==prefix+b'\xb8\x00\x00\x00\x00\xc3', (s,body.hex())
        sec=e.sections[s['sec']]
        offsets.append(sec[4]+s['value']-sec[3]+len(prefix)+1)
    rows=[]
    for name,word in ARMS.items():
        path=BUILD/name; data=bytearray(e.data)
        for offset in offsets: struct.pack_into('<I',data,offset,word)
        if path!=original: path.write_bytes(data); path.chmod(original.stat().st_mode)
        observed=bytearray(path.read_bytes())
        for offset in offsets: observed[offset:offset+4]=e.data[offset:offset+4]
        assert observed==e.data, 'non-selector byte changed'
        rows.append(dict(name=name, arm_word=hex(word), **receipt(path)))
    pre=receipt(BUILD/'wbland-pre-src/build/tomokv')
    reference=receipt(Path('/home/user/Projects/bench-bins/tomokv-headline-9c4717da0'))
    assert reference['sha256']=='84ddb8abba4d8c32196edadb860da45114379490432a900dfee76efb71bfdd72'
    out=dict(pre=pre, reference=reference, arms=rows, selector_offsets=offsets,
             exact_layout=True, pad_kind='A: PRE half-rule behavior in exact candidate layout',
             caveat='new fixed-policy dispatch remains; require pol1-vs-PRE null',
             text_delta=rows[0]['text']-pre['text'])
    (BUILD/'wbland-artifacts.json').write_text(json.dumps(out,indent=2)+'\n')
    print(f'PASS {len(rows)} exact-layout arms; PAD A; .text delta {out["text_delta"]:+d}')
    for row in rows: print(row['name'],row['sha256'])


def identity(pre_build):
    rows=[]
    for ns in ('src','db0/src'):
        for file in ('cmd/t_string.o','cmd/t_string_notify.o'):
            a,b=Elf(pre_build/ns/file),Elf(BUILD/ns/file)
            before,after=a.functions(),b.functions(); names=sorted(before.keys() | after.keys())
            labels=subprocess.check_output(['c++filt'],input='\n'.join(names)+'\n',text=True).splitlines()
            for name,label in zip(names,labels):
                if re.search(r'::cmd_(get|set)(?:<|\(|_tls\(|_notify\()',label):
                    rows.append(dict(object=ns+'/'+file,name=label,
                                     identical=name in before and name in after and
                                     a.canonical(before[name])==b.canonical(after[name])))
    (BUILD/'wbland-command-identity.json').write_text(json.dumps(rows,indent=2)+'\n')
    assert len(rows)==16 and all(r['identical'] for r in rows), rows
    print('PASS GET/SET: 16/16 opcode and relocation identities')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('action',choices=('arms','identity'))
    p.add_argument('--pre-build', type=Path, default=BUILD/'wbland-pre-src/build',
                   help='matched mainline object directory for command identity')
    args=p.parse_args()
    if args.action=='arms': arms()
    else: identity(args.pre_build.resolve())
