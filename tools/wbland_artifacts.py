#!/usr/bin/env python3
"""Freeze policy 0/1 arms and audit every writeback-dependent object's text.

Never executes a server. PAD A is the REF half-rule behavior with the candidate
knob read and text layout. After adaptive-policy deletion it is byte-identical
to POST; the REF-vs-POST null still prices the knob/codegen cost.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT/'build'
PRE_BUILD = BUILD/'wbland3/pre-src/build'
ARMS = {'tomokv': 1, 'tomokv-pol0': 0, 'tomokv-pol1': 1, 'tomokv-pad': 1}
INPUTS = ('src/core/wb_rule.h', 'src/net/wb.h',
          'src/core/io_loop.h', 'src/core/reorder.cc')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def receipt(path):
    e = Elf(path)
    return dict(path=str(path.relative_to(ROOT)), sha256=digest(e.data),
                text=e.sections[e.names.index('.text')][5],
                tdata=e.sections[e.names.index('.tdata')][5],
                tbss=e.sections[e.names.index('.tbss')][5])


def arms(pre_build):
    original = BUILD/'tomokv'
    e = Elf(original)
    symbols = [s for s in e.symbols if s['name'].endswith('7wb_rule14default_policyEv')]
    assert len(symbols) == 2, [s['name'] for s in symbols]
    offsets = []
    for symbol in symbols:
        body = e.body(symbol)
        prefix = b'\xf3\x0f\x1e\xfa' if body.startswith(b'\xf3\x0f\x1e\xfa') else b''
        assert body == prefix+b'\xb8\x01\x00\x00\x00\xc3', (symbol, body.hex())
        sec = e.sections[symbol['sec']]
        offsets.append(sec[4]+symbol['value']-sec[3]+len(prefix)+1)
    rows = []
    for name, policy in ARMS.items():
        path = BUILD/name
        data = bytearray(e.data)
        for offset in offsets:
            struct.pack_into('<I', data, offset, policy)
        if path != original:
            path.write_bytes(data)
            path.chmod(original.stat().st_mode)
        observed = bytearray(path.read_bytes())
        for offset in offsets:
            observed[offset:offset+4] = e.data[offset:offset+4]
        assert observed == e.data, 'non-selector byte changed'
        rows.append(dict(name=name, default_policy=policy, **receipt(path)))
    # Retire the obsolete generated probe so it cannot be selected accidentally.
    (BUILD/'tomokv-auto2s-probe').unlink(missing_ok=True)
    pre = receipt(pre_build/'tomokv')
    out = dict(ref='37eeb5e90', pre=pre, arms=rows, selector_offsets=offsets,
               exact_layout=True, pad_kind='A: REF half behavior, candidate knob read and text layout',
               pad_equals_post=(BUILD/'tomokv-pad').read_bytes() == e.data,
               caveat='PAD equals POST; REF-vs-POST/PAD null prices common knob/codegen cost',
               text_delta=rows[0]['text']-pre['text'])
    (BUILD/'wbland-artifacts.json').write_text(json.dumps(out, indent=2)+'\n')
    assert out['pad_equals_post']
    print(f'PASS {len(rows)} exact-layout arms; PAD A == POST; .text delta {out["text_delta"]:+d}')
    for row in rows:
        print(row['name'], row['sha256'])


def dependencies(build):
    rows = {}
    for ns in ('src', 'db0/src'):
        objects = sorted((build/ns).rglob('*.o'))
        assert objects and all(path.with_suffix('.d').is_file() for path in objects), 'missing compiler dependency receipt'
        for path in sorted((build/ns).rglob('*.d')):
            line = path.read_text().replace('\\\n', '').splitlines()[0]
            deps = {os.path.normpath(token) for token in line.split(':', 1)[1].split()}
            matched = sorted(set(INPUTS) & deps)
            if matched:
                rows[str(path.with_suffix('.o').relative_to(build))] = matched
    return rows


def text_sections(elf):
    return {name: elf.section_data(i) for i, name in enumerate(elf.names)
            if name == '.text' or name.startswith('.text.')}


def section_receipt(sections):
    raw = sections.get('.text', b'')
    packed = b''.join(name.encode()+b'\0'+struct.pack('<Q', len(data))+data
                      for name, data in sorted(sections.items()))
    return dict(text_bytes=len(raw), text_sha256=digest(raw),
                all_text_bytes=sum(map(len, sections.values())),
                all_text_sha256=digest(packed), sections=len(sections))


def text_identity(pre_build):
    before_deps, after_deps = dependencies(pre_build), dependencies(BUILD)
    names = sorted(before_deps.keys() | after_deps.keys())
    assert names and all(any(header in deps for deps in after_deps.values()) for header in INPUTS)
    rows = []
    for name in names:
        before = text_sections(Elf(pre_build/name))
        after = text_sections(Elf(BUILD/name))
        rows.append(dict(object=name, pre_inputs=before_deps.get(name, []),
                         post_inputs=after_deps.get(name, []),
                         pre=section_receipt(before), post=section_receipt(after),
                         text_identical=before.get('.text') == after.get('.text'),
                         all_text_identical=before == after,
                         changed_sections=sorted(key for key in before.keys() | after.keys()
                                                 if before.get(key) != after.get(key)),
                         pad_equals_post=True))
    assert (BUILD/'tomokv-pad').read_bytes() == (BUILD/'tomokv').read_bytes()
    result = dict(ref='37eeb5e90', inputs=INPUTS,
                  coverage='union of PRE/POST compiler -MMD dependency closures, both namespaces',
                  comparison='raw .text plus all .text.* sections; no relocation normalization',
                  pad='exact POST binary copy; same objects', rows=rows)
    (BUILD/'wbland3/text-identity.json').write_text(json.dumps(result, indent=2)+'\n')
    same = sum(row['text_identical'] for row in rows)
    all_same = sum(row['all_text_identical'] for row in rows)
    print(f'REF-vs-POST .text exact: {same}/{len(rows)} objects; all .text.* exact: {all_same}/{len(rows)}')
    for row in rows:
        print(f'{row["object"]}: .text={"SAME" if row["text_identical"] else "DIFF"}, '
              f'all .text.*={"SAME" if row["all_text_identical"] else "DIFF"}, PAD=POST')


def identity(pre_build):
    rows = []
    for ns in ('src', 'db0/src'):
        for file in ('cmd/t_string.o', 'cmd/t_string_notify.o'):
            a, b = Elf(pre_build/ns/file), Elf(BUILD/ns/file)
            before, after = a.functions(), b.functions()
            names = sorted(before.keys() | after.keys())
            labels = subprocess.check_output(['c++filt'], input='\n'.join(names)+'\n', text=True).splitlines()
            for name, label in zip(names, labels):
                if re.search(r'::cmd_(get|set)(?:<|\(|_tls\(|_notify\()', label):
                    rows.append(dict(object=ns+'/'+file, name=label,
                                     identical=name in before and name in after and
                                     a.canonical(before[name]) == b.canonical(after[name])))
    (BUILD/'wbland-command-identity.json').write_text(json.dumps(rows, indent=2)+'\n')
    assert len(rows) == 16 and all(row['identical'] for row in rows), rows
    print('PASS GET/SET: 16/16 opcode and relocation identities')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('arms', 'text', 'identity'))
    parser.add_argument('--pre-build', type=Path, default=PRE_BUILD,
                        help='REF object directory built with g++ -MMD -MP')
    args = parser.parse_args()
    {'arms': arms, 'text': text_identity, 'identity': identity}[args.action](args.pre_build.resolve())
