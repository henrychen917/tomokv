#!/usr/bin/env python3
"""Compile and inspect DWARF/constant arrays only; never execute the objects."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import struct
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf
OUT = Path(__file__).resolve().parent
BUILD = ROOT / 'build/lbosc3/lbosc3b'
NAMES = ['Op', 'Client', 'ThreadCtx', 'Shard', 'FlatStore', 'Rob<64>', 'AtomicEntry', 'Config']
EXPECTED = [336, 1984, 1408, 1440, 944, 192, 144, 624]
KEYS = list(json.loads((ROOT / 'docs/lbosc3/layout.json').read_text())['pre'])


def inspect(pair):
    arm, db0 = pair
    name = arm + ('-db0' if db0 else '-multi')
    headers = ROOT / 'build/lbosc3/PRE/source' if arm == 'PRE' else ROOT
    obj = BUILD / (name + '-layout.o')
    cmd = ['taskset', '-c', '112-127', 'g++', '-std=c++20', '-O0', '-g',
           '-fno-eliminate-unused-debug-types', '-DTOMO_CORE_CONCURRENCY_TEST',
           '-DTOMO_JEMALLOC', '-I' + str(headers)]
    if db0: cmd += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
    cmd += ['-c', str(ROOT / 'tests/multidb_layout.cc'), '-o', str(obj)]
    with (BUILD / (name + '-layout.log')).open('w') as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    elf = Elf(obj)
    symbol = next(s for s in elf.symbols if s['name'] == 'multidb_layout_values')
    vals = struct.unpack('<' + 'Q' * (symbol['size'] // 8), elf.body(symbol))
    ns = 'tomo_db0' if db0 else 'tomo'
    program = '\n'.join(['import gdb,json', 'out={}',
        'for name in ' + repr(NAMES) + ':',
        f' t=gdb.lookup_type({ns!r}+"::"+name)',
        f' out[{ns!r}+"::"+name]={{"size":t.sizeof,"fields":{{f.name:f.bitpos for f in t.fields() if f.name and hasattr(f,"bitpos")}}}}',
        'print(json.dumps(out,sort_keys=True))'])
    raw = subprocess.check_output(['gdb', '-nx', '-batch', '-iex', 'set debuginfod enabled off',
                                   str(obj), '-ex', 'python exec(' + repr(program) + ')'], text=True)
    return name, dict(command=cmd, exported=dict(zip(KEYS, vals)), fields=json.loads(raw))


def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = dict(pool.map(inspect, [(a,d) for a in ('PRE','POST') for d in (False,True)]))
    origin = json.loads((ROOT / 'docs/encodingfix/layouts.json').read_text())['POST']
    previous = json.loads((ROOT / 'docs/lbosc3/layout.json').read_text())
    for db0 in (False,True):
        suffix = '-db0' if db0 else '-multi'
        pre, post = rows['PRE'+suffix], rows['POST'+suffix]
        assert pre['exported'] == post['exported'] == previous['pre-db0' if db0 else 'pre']
        ns = 'tomo_db0' if db0 else 'tomo'
        for name, size in zip(NAMES,EXPECTED):
            key = ns+'::'+name
            assert pre['fields'][key] == origin[key], ('PRE differs from encodingfix',key)
            a,b=pre['fields'][key],post['fields'][key]
            assert a['size'] == b['size'] == size
            assert {k:v for k,v in a['fields'].items() if k != 'layout_reserved'} == {
                k:v for k,v in b['fields'].items() if k not in ('layout_reserved','key_lb_damping')}, key
        cfg=post['fields'][ns+'::Config']['fields']
        assert cfg['stream_limits']==560*8 and cfg['key_lb_damping']==568*8 and cfg['layout_reserved']==572*8
    result=dict(all_origin_nonreserved_fields_equal=True, previous_exported_layouts_equal=True,
                both_namespaces_equal=True, config_bytes=624, stream_limits_offset=560,
                key_lb_damping_offset=568, layout_reserved_offset=572, layout_reserved_bytes=52, rows=rows)
    (OUT/'layouts.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS all encodingfix non-reserved field offsets and lbosc3 exported layouts; both namespaces; Config 624')


if __name__=='__main__': main()
