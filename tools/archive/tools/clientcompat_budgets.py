#!/usr/bin/env python3
"""Compile-only GCC unit-growth evidence; bounded to this lane's CPUs."""
import concurrent.futures
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from ccfix4_budget import inventory, compare

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/clientcompat/budgets'
DOC = ROOT / 'docs/clientcompat/budgets'


def trial(case):
    arm, namespace, unit = case
    source = ROOT / 'build/clientcompat/PRE' if arm == 'PRE' else ROOT
    objects = source if arm == 'PRE' else ROOT / 'build'
    obj = objects / ('db0/src' if namespace == 'db0' else 'src') / 'cmd' / (unit+'.o')
    recipe = subprocess.check_output(['make', '-B', '-n', 'BUILD_ROOT='+str(objects), str(obj)],
                                     cwd=source, text=True)
    command = shlex.split(next(line for line in reversed(recipe.splitlines())
                              if line.startswith('g++ ') and line.endswith(' -o '+str(obj))))
    tag = '-'.join(case)
    dest = OUT / (tag+'.o')
    command = ['-g0' if word == '-g' else word for word in command]
    command[command.index('-o')+1] = str(dest)
    command += ['-fdump-ipa-inline', '-dumpbase', str(OUT/tag)]
    with (OUT/(tag+'.log')).open('w') as log:
        subprocess.run(command, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    dump, = OUT.glob(tag+'*.inline')
    text = dump.read_text()
    initial = int(re.search(r'Starting with size (\d+)', text)[1])
    result = dict(arm=arm, namespace=namespace, unit=unit, initial=initial,
                  command=command, object_sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
    (DOC/(tag+'.json')).write_text(json.dumps(result, indent=2)+'\n')
    dump.unlink()
    print(tag, initial, flush=True)
    return result


def main():
    assert os.sched_getaffinity(0) <= set(range(64, 80))
    os.environ['LC_ALL'] = 'C'
    OUT.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan', action='store_true')
    args = parser.parse_args()
    if args.scan:
        survey = json.loads((DOC/'survey.json').read_text())
        by = {(r['arm'],r['namespace'],r['unit']):r for r in survey}
        def scan(case):
            namespace, unit, value = case
            record = by['POST',namespace,unit]
            tag = f'{namespace}-{unit}-{value}'
            dest = OUT/(tag+'.o')
            command = record['command'][:]
            command = command[:command.index('-fdump-ipa-inline')]
            command = [f'large-unit-insns={value}' if x.startswith('large-unit-insns=') else x
                       for x in command]
            if not any(x.startswith('large-unit-insns=') for x in command):
                command += ['--param','inline-unit-growth=0','--param',f'large-unit-insns={value}']
            command[command.index('-o')+1] = str(dest)
            with (OUT/(tag+'.log')).open('w') as log:
                subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
            old = inventory(OUT/f'PRE-{namespace}-{unit}.o')
            new = inventory(dest)
            diff = compare(old,new)
            hot_names = set()
            for path in (ROOT/'docs/clientcompat/instructions/PRE/complete').glob(namespace+'-*.json'):
                hot_names.update(json.loads(path.read_text())['functions'])
            selected = [r for r in diff['rows'] if r['name'] in hot_names]
            result = dict(namespace=namespace,unit=unit,budget=value,command=command,
                          object_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                          score=[len(selected),diff['changed']],changed_scope_functions=selected,
                          differences=diff)
            (DOC/(tag+'.json')).write_text(json.dumps(result,indent=2)+'\n')
            print(tag,result['score'],flush=True)
            return result
        cases=[]
        for namespace in ('normal','db0'):
            for unit in ('xshard','tracking'):
                pre,post=by['PRE',namespace,unit],by['POST',namespace,unit]
                old = (156257 if namespace=='normal' else 159264) if unit=='xshard' else int(pre['initial']*1.4)
                center=old+post['initial']-pre['initial']
                cases += [(namespace,unit,value) for value in sorted({old,center-8,center,center+8})]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows=list(pool.map(scan,cases))
        (DOC/'trials.json').write_text(json.dumps(rows,indent=2)+'\n')
        return
    cases = [(arm, namespace, unit) for arm in ('PRE','POST')
             for namespace in ('normal','db0') for unit in ('xshard','tracking')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(trial, cases))
    (DOC/'survey.json').write_text(json.dumps(rows, indent=2)+'\n')


if __name__ == '__main__':
    main()
