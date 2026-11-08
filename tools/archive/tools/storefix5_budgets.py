#!/usr/bin/env python3
"""Compile-only inlining-budget controls for unchanged command-path bodies."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from ccfix_audit import audit

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT/'build/storefix5/pre-source'
OUT = ROOT/'build/storefix5/budgets'
DOC = ROOT/'docs/storefix5/budgets'
OUT.mkdir(parents=True, exist_ok=True); DOC.mkdir(parents=True, exist_ok=True)
assert os.sched_getaffinity(0) <= set(range(16,24))
objects = ('src/cmd/xshard.o', 'db0/src/cmd/xshard.o')


def compile(arm, obj, budget=None):
    source = PRE if arm == 'pre' else ROOT
    original = subprocess.check_output(['make','-B','-n','build/'+obj], cwd=source, text=True)
    cmd = shlex.split(next(line for line in reversed(original.splitlines())
                          if line.startswith('g++ ') and line.endswith(' -o build/'+obj)))
    if budget is None:
        budget = int(next(x.split('=')[1] for x in cmd if x.startswith('large-unit-insns=')))
    tag = arm+'-'+obj.replace('/','_')+'-'+str(budget)
    dest = OUT/(tag+'.o')
    cmd = ['-g0' if x == '-g' else 'large-unit-insns='+str(budget)
           if x.startswith('large-unit-insns=') else x for x in cmd]
    cmd[cmd.index('-o')+1] = str(dest)
    cmd += ['-fdump-ipa-inline','-dumpbase',str(OUT/tag)]
    with (OUT/(tag+'.log')).open('w') as log:
        subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    dump, = OUT.glob(tag+'*.inline')
    unit = next(int(m[1]) for line in dump.open()
                if (m := re.search(r'Starting with size (\d+)',line)))
    dump.unlink()
    result = dict(arm=arm, object=obj, budget=budget, unit=unit, command=cmd,
                  output=str(dest), sha256=hashlib.file_digest(dest.open('rb'),'sha256').hexdigest())
    (DOC/(tag+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(tag, 'unit', unit, flush=True)
    return result


if sys.argv[1] == 'initial':
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda job:compile(*job), [(a,o) for a in ('pre','post') for o in objects]))
    (DOC/'initial.json').write_text(json.dumps(rows,indent=2)+'\n')
elif sys.argv[1] == 'scan':
    initial = json.loads((DOC/'initial.json').read_text())
    by = {(r['arm'],r['object']):r for r in initial}
    jobs = []
    for obj in objects:
        old, new = by['pre',obj], by['post',obj]
        center = old['budget'] + new['unit'] - old['unit']
        for value in sorted({center-32,center-8,center,center+8,center+32}):
            jobs.append(('post',obj,value))
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda job:compile(*job),jobs))
    rows += [r for r in initial if r['arm']=='post']
    for row in rows:
        pre = audit.Elf(Path(by['pre',row['object']]['output']))
        post = audit.Elf(Path(row['output']))
        a,b=pre.functions(),post.functions()
        find = next(name for name in a if '9FlatStore4findE' in name)
        row['find_equal'] = find in b and pre.canonical(a[find]) == post.canonical(b[find])
        row['changed_common_bodies'] = sum(pre.canonical(a[name]) != post.canonical(b[name])
                                           for name in a.keys() & b.keys())
        print(row['object'],row['budget'],'find',row['find_equal'],
              'changed',row['changed_common_bodies'],flush=True)
    (DOC/'scan.json').write_text(json.dumps(rows,indent=2)+'\n')
elif sys.argv[1] == 'strings':
    objects = ('src/cmd/t_string.o', 'db0/src/cmd/t_string.o')
    with ThreadPoolExecutor(max_workers=4) as pool:
        initial = list(pool.map(lambda job:compile(*job), [(a,o) for a in ('pre','post') for o in objects]))
    by = {(r['arm'],r['object']):r for r in initial}
    jobs = []
    for obj in objects:
        old, new = by['pre',obj], by['post',obj]
        center = old['budget'] + new['unit'] - old['unit']
        for value in sorted({center-32,center-8,center,center+8,center+32}):
            jobs.append(('post',obj,value))
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda job:compile(*job),jobs))
    rows += initial
    for row in rows:
        pre = audit.Elf(Path(by['pre',row['object']]['output']))
        post = audit.Elf(Path(row['output']))
        a,b=pre.functions(),post.functions()
        names = [name for name in a if '12store_stringE' in name]
        row['store_string_equal'] = {name: name in b and pre.canonical(a[name]) == post.canonical(b[name]) for name in names}
    (DOC/'strings.json').write_text(json.dumps(rows,indent=2)+'\n')
elif sys.argv[1] in ('retirement', 'retirement-wide'):
    obj = 'db0/src/cmd/xshard.o'
    values = ((166757, 166789, 166853, 166981, 167237) if sys.argv[1] == 'retirement'
              else (168000, 170000, 175000, 180000))
    jobs = [('retirement', obj, value) for value in values]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda job: compile(*job), jobs))
    prior = json.loads((DOC/'pre-db0_src_cmd_xshard.o-165926.json').read_text())
    pre = audit.Elf(Path(prior['output']))
    a = pre.functions()
    find = next(name for name in a if '9FlatStore4findE' in name)
    for row in rows:
        post = audit.Elf(Path(row['output']))
        b = post.functions()
        row['find_equal'] = find in b and pre.canonical(a[find]) == post.canonical(b[find])
        row['find_key_eq_call'] = 'key_eq' in str(post.canonical(b[find]))
        row['changed_common_bodies'] = sum(pre.canonical(a[name]) != post.canonical(b[name])
                                           for name in a.keys() & b.keys())
        print(row['budget'], row['unit'], row['find_equal'], row['find_key_eq_call'],
              row['changed_common_bodies'], flush=True)
    (DOC/(sys.argv[1]+'.json')).write_text(json.dumps(rows, indent=2)+'\n')
else:
    raise SystemExit('initial or scan required')
