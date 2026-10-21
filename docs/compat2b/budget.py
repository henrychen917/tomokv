#!/usr/bin/env python3
"""Compile-only compat2b trials, with headline and frozen compat2 body references.

All commands inherit CPUs 64-79. At most sixteen compiler processes run at once.
Input: JSON list of {object, tree?: headline|post, budget?, auto?}.
Canonical bytes/relocations use the unchanged ccfix_audit implementation.
"""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/compat2b'
HEAD = ROOT / 'build/compat2b/headline-src'
OLD = ROOT / 'build/compat2b/compat2'
sys.path.insert(0, str(ROOT / 'tools'))
import ccfix_audit

audit = ccfix_audit.audit
HOT_EXTRA = re.compile(r'ExLoopT<.*>::run\(|ExLoopT<true>::prepare_local_read')
LANE_CHANGED = {(r['object'], r['symbol']) for r in json.loads(
    (ROOT / 'docs/compat2/identity-complete/body-reasons.json').read_text())}


def hot(name):
    return bool(audit.HOT.search(name) or HOT_EXTRA.search(name))


class Bodies:
    def __init__(self, path):
        self.elf = audit.Elf(path) if path.exists() else None
        self.funcs = self.elf.functions() if self.elf else {}
        self.cache = {}

    def canon(self, sym):
        if sym not in self.funcs:
            return None
        if sym not in self.cache:
            self.cache[sym] = self.elf.canonical(self.funcs[sym])
        return self.cache[sym]

    def size(self, sym):
        return self.funcs.get(sym, {}).get('size', 0)


def compare(path, obj):
    ref, old, post = Bodies(HEAD / 'build' / obj), Bodies(OLD / obj), Bodies(path)
    symbols = sorted(ref.funcs.keys() | post.funcs.keys())
    names = subprocess.check_output(['c++filt'], input='\n'.join(symbols)+'\n', text=True).splitlines()
    rows, hot_count, hot_equal = [], 0, 0
    for sym, name in zip(symbols, names):
        a, b = ref.canon(sym), post.canon(sym)
        is_hot = hot(name)
        hot_count += is_hot
        if a is not None and a == b:
            hot_equal += is_hot
            continue
        c = old.canon(sym)
        lane = (obj, sym) in LANE_CHANGED
        match_old = b is not None and b == c
        same_targets = bool(a and b and a[1] == b[1])
        rows.append(dict(object=obj, symbol=sym, name=name, hot=is_hot,
                         headline=ref.size(sym), compat2=old.size(sym), post=post.size(sym),
                         lane_changed=lane, equals_compat2=match_old,
                         admitted=bool(lane and match_old), targets_equal=same_targets,
                         kind='added' if a is None else 'removed' if b is None else
                              'relocation-only' if a[0] == b[0] else 'code'))
    return dict(total=len(symbols), hot=hot_count, hot_equal_headline=hot_equal,
                hot_equal_compat2=sum(r['hot'] and r['admitted'] for r in rows),
                residual_hot=sum(r['hot'] and not r['admitted'] for r in rows),
                residual=sum(not r['admitted'] for r in rows), changed=len(rows), rows=rows)


def trial(job, keys, outdir):
    obj, tree = job['object'], job.get('tree', 'post')
    root = HEAD if tree == 'headline' else ROOT
    lines = (OUT / ('headline-build.log' if tree == 'headline' else 'post-commands.log')).read_text().splitlines()
    command = next(shlex.split(line) for line in lines
                   if line.startswith('g++ ') and line.endswith(' -o build/' + obj))
    for key, option in [('budget', 'large-unit-insns'), ('auto', 'max-inline-insns-auto')]:
        if key in job:
            for i, arg in enumerate(command):
                if arg.startswith(option+'='):
                    command[i] = option+'='+str(job[key])
                    break
            else:
                command += ['--param', option+'='+str(job[key])]
    cachekey = hashlib.sha256((str(root)+keys[tree]+' '.join(command)).encode()).hexdigest()[:16]
    base = ROOT / 'build/compat2b/trials' / (obj.replace('/', '_')+'.'+cachekey)
    base.parent.mkdir(parents=True, exist_ok=True)
    output = Path(str(base)+'.o')
    receipt = Path(str(base)+'.json')
    command[command.index('-o')+1] = str(output)
    command += ['-fdump-ipa-inline', '-dumpbase', str(base)]
    if receipt.exists():
        row = json.loads(receipt.read_text())
    else:
        with Path(str(base)+'.log').open('w') as log:
            subprocess.run(['taskset', '-c', '64-79', *command], cwd=root,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        dump = next(base.parent.glob(base.name+'*.inline'))
        unit = None
        with dump.open(errors='replace') as stream:
            for line in stream:
                m = re.search(r'Starting with size (\d+)', line)
                if m:
                    unit = int(m[1]); break
        assert unit is not None
        dump.unlink()
        row = dict(job, tree=tree, source_sha256=keys[tree], unit=unit,
                   command=['taskset','-c','64-79',*command], cwd=str(root), output=str(output),
                   sha256=hashlib.sha256(output.read_bytes()).hexdigest(), **compare(output,obj))
        receipt.write_text(json.dumps(row,indent=2)+'\n')
    name=obj.replace('/','_')+'.'+tree+'.'+str(job.get('budget','default'))
    if 'auto' in job: name += '.auto'+str(job['auto'])
    (outdir/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n')
    print(json.dumps({k:v for k,v in row.items() if k in
          ('object','tree','budget','auto','unit','hot','hot_equal_headline',
           'hot_equal_compat2','residual_hot','residual','changed')}),flush=True)
    return row


def main():
    jobs=json.loads(Path(sys.argv[1]).read_text())
    outdir=Path(sys.argv[2]); outdir.mkdir(parents=True,exist_ok=True)
    keys={}
    for tree in {j.get('tree','post') for j in jobs}:
        root=HEAD if tree=='headline' else ROOT
        digest=hashlib.sha256()
        for p in sorted((root/'src').rglob('*')):
            if p.is_file(): digest.update(str(p.relative_to(root)).encode()+p.read_bytes())
        keys[tree]=digest.hexdigest()
    with ProcessPoolExecutor(max_workers=16) as pool:
        rows=list(pool.map(trial,jobs,[keys]*len(jobs),[outdir]*len(jobs)))
    (outdir/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')


if __name__=='__main__':
    main()
