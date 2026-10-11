#!/usr/bin/env python3
"""trial.py's compile, then report every HOT body (lbstall HOT regex) that is not identical to PRE
(bytes + resolved relocation targets), with no intended-code exemption, plus trial.py's counts.
Usage: trialhot.py <object> '<params>' ['<params>' ...]"""
import concurrent.futures as cf, json, os, subprocess, sys
os.environ['TRIAL_OBJ'] = sys.argv[1]
sys.path.insert(0, '/home/user/Projects/cx-flipfix/build/flipfix')
import trial_lib as T
def hot_changes(path):
    a, b = T.audit.Elf(T.WT / 'build/flipfix/pre' / T.obj), T.audit.Elf(path)
    fa, fb = a.functions(), b.functions()
    names = sorted(set(fa) | set(fb))
    readable = dict(zip(names, subprocess.check_output(['c++filt'], input=('\n'.join(names) + '\n').encode()).decode().splitlines()))
    out = []
    for n in names:
        if not T.audit.HOT.search(readable[n]): continue
        if n in fa and n in fb and a.canonical(fa[n]) == b.canonical(fb[n]): continue
        out.append(f"{fa.get(n, {}).get('size', 0)}->{fb.get(n, {}).get('size', 0)} {readable[n][:120]}")
    return out
with cf.ThreadPoolExecutor(int(os.environ.get('JOBS', '6'))) as pool:
    for params, path in pool.map(T.compile_with, sys.argv[2:]):
        counts, collateral = T.classify(path)
        hot = hot_changes(path)
        print(json.dumps({'object': T.obj, 'params': params, 'hot_changed': len(hot), **counts}), flush=True)
        for line in hot: print('    HOT ' + line, flush=True)
        for line in collateral[:int(os.environ.get('SHOW', '8'))]: print('    ' + line, flush=True)
