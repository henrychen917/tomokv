#!/usr/bin/env python3
"""Bounded compile and instruction-count trials of scatter inlining limits."""
import concurrent.futures
import argparse
import json
import os
from pathlib import Path
import subprocess
import wave12_counts as c

ROOT = Path(__file__).resolve().parents[1]
c.BUILD = ROOT / 'build/clientcompat/counts'
c.DOC = ROOT / 'docs/clientcompat/instructions'
OUT = ROOT / 'build/clientcompat/budgets'
SKIP_COMPILE = False
EARLY = False
COMPILE_ONLY = False


def trial(case):
    namespace, auto, value, early = case
    tag = f'inline-{namespace}-{auto}-{value}-early{early}'
    row = json.loads((ROOT/'docs/clientcompat/budgets'/f"{namespace}-xshard-{158654 if namespace == 'normal' else 161645}.json").read_text())
    obj = OUT/(tag+'.o')
    command = [f'max-inline-insns-auto={auto}' if arg.startswith('max-inline-insns-auto=') else
               f'large-unit-insns={value}' if arg.startswith('large-unit-insns=') else arg
               for arg in row['command']]
    command[command.index('-o')+1] = str(obj)
    if early is not None:
        command += ['--param', f'early-inlining-insns={early}']
    if not SKIP_COMPILE:
        with (OUT/(tag+'.log')).open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    if COMPILE_ONLY:
        return dict(tag=tag,command=command,object_sha256=c.sha(obj))
    folder = c.BUILD/'scopes'/tag
    folder.mkdir(parents=True, exist_ok=True)
    binary = folder/'probe'
    recipe = json.loads((c.DOC/'POST'/(namespace+'-build.json')).read_text())['link']
    original = ROOT/'build'/('db0/src/cmd/xshard.o' if namespace=='db0' else 'src/cmd/xshard.o')
    recipe = [str(obj) if arg==str(original) else arg for arg in recipe]
    recipe[recipe.index('-o')+1] = str(binary)
    recipe += ['-Wl,--strip-debug']
    with (OUT/(tag+'.link.log')).open('w') as log:
        subprocess.run(recipe, stdout=log, stderr=subprocess.STDOUT, check=True)
    prepared = c.prepare(binary, ROOT/'build', namespace, 'complete')
    ranges,argv,digest=prepared
    for row in ranges:
        row[4]=not ('CoreConcurrencyTest::' in row[3] or row[2] in ('main','_Z11scope_beginv','_Z9scope_endv'))
    whole=binary.parent/'elf.ranges'
    whole.write_text(''.join(f'{r[0]:x} {r[1]:x} {int(r[4])}\n' for r in ranges))
    argv[2]=str(whole)
    counts = [c.trace(prepared, tag, namespace, 'complete', verb, '2s', 1, atomic)
              for verb, atomic in [('GET',1),('SET',1),('INCR',1),('MGET',0),('MGET',1),('MSET',1)]]
    for count in counts:
        name = '-'.join(map(str,(namespace,count['command'],'2s',1,count['atomic'])))+'.json'
        before = json.loads((c.DOC/'PRE-elf/complete'/name).read_text())['total']
        count['delta'] = count['total']-before
    result = dict(namespace=namespace,auto=auto,budget=value,command=command,link=recipe,
                  object_sha256=c.sha(obj),rows=counts)
    c.save(ROOT/'docs/clientcompat/budgets'/(tag+'.json'),result)
    print(tag,[row['delta'] for row in counts],flush=True)
    return result


def main():
    global SKIP_COMPILE, COMPILE_ONLY
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-compile', action='store_true')
    parser.add_argument('--cases', default='')
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    SKIP_COMPILE = args.skip_compile
    COMPILE_ONLY = args.compile_only
    assert os.sched_getaffinity(0) <= set(range(64,80))
    os.environ['LC_ALL']='C'
    cases=[(ns,auto,base,early) for ns,auto,base in [('normal',14,158654),('db0',18,161645)] for early in (4,5,7,8)]
    if args.cases:
        cases=[(parts[0],int(parts[1]),int(parts[2]),int(parts[3])) for row in args.cases.split(',') for parts in [row.split(':')]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        rows=list(pool.map(trial,cases))
    c.save(ROOT/'docs/clientcompat/budgets/inline-trials.json',rows)


if __name__=='__main__':
    main()
