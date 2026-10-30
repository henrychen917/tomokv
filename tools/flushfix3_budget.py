#!/usr/bin/env python3
"""Compile isolated scatter budget trials and count finite MGET/MSET scopes."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess

import flushfix2_budget as budget
import flushfix3_counts as counts_setup
counts = counts_setup.counts
ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--normal', default='156000:14,156000:18,156000:20')
    p.add_argument('--db0', default='159000:14,159000:18,159000:20')
    p.add_argument('--jobs', type=int, default=4)
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(16))
    budget.BUILD = ROOT / 'build/flushfix3/budgets'
    budget.OUT = ROOT / 'docs/flushfix3/budgets'
    budget.PRE = ROOT / 'build/flushfix3/pre-source/build'
    for directory in (budget.BUILD, budget.OUT): directory.mkdir(parents=True, exist_ok=True)
    counts.BUILD = ROOT / 'build/flushfix3/budget-counts'
    counts.OUT = ROOT / 'docs/flushfix3/budget-counts'
    counts.scope.BUILD = counts.BUILD
    for directory in (counts.BUILD, counts.OUT): directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(['gcc', '-O2', str(ROOT/'tools/crlffix_step.c'), '-o', str(counts.BUILD/'step')], check=True)
    recipes = budget.recipes()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    revision += ':' + hashlib.sha256(subprocess.check_output(['git', 'diff', 'HEAD', '--', 'src', 'Makefile'])).hexdigest()
    trials = [(ns, unit, value) for ns, unit, values in (
        ('normal', 'src/cmd/xshard.o', a.normal), ('db0', 'db0/src/cmd/xshard.o', a.db0))
        for value in values.split(',') if value]
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as pool:
        list(pool.map(budget.trial, [(unit, value, recipes, revision, True) for ns, unit, value in trials]))
    prepared = {}
    for ns, unit, value in trials:
        dest = counts.BUILD / (value+'-'+ns)
        dest.mkdir(exist_ok=True)
        obj = budget.BUILD / (unit.replace('/', '_')+'-'+value+'.o')
        receipt = json.loads((ROOT/'docs/flushfix3/counts'/('post-'+ns+'-build.json')).read_text())
        link = [str(obj) if item == str(ROOT/'build'/unit) else item for item in receipt['link']]
        assert str(obj) in link
        link[link.index('-o')+1] = str(dest/'probe')
        subprocess.run(link, stdout=subprocess.DEVNULL, check=True)
        prepared[value, ns] = counts.fast.prepare(value, ns)
        print('prepared', value, ns, flush=True)
    cases = [(arm, ns, command, mode, 1, atomic, -1) for arm, ns in prepared
             for command in ('MGET', 'MSET') for mode in ('1s', '2s') for atomic in (0, 1)]
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as pool:
        rows = list(pool.map(lambda case: counts.run(case, prepared), cases))
    comparisons = []
    for row in rows:
        stem = '-'.join(str(row[k]) for k in ('namespace', 'command', 'mode', 'batch', 'atomic', 'threshold'))
        pre = json.loads((ROOT/'docs/flushfix3/counts'/('pre-'+stem+'.json')).read_text())
        comparisons.append({k:v for k,v in row.items() if k != 'functions'} |
                           dict(pre=pre['total'], delta=row['total']-pre['total']))
    label = hashlib.sha256((a.normal+'|'+a.db0).encode()).hexdigest()[:12]
    (counts.OUT/(label+'.json')).write_text(json.dumps(comparisons, indent=2)+'\n')
    for arm, ns in prepared:
        selected = [r for r in comparisons if r['arm']==arm and r['namespace']==ns]
        print(ns, arm, 'added', sum(r['delta']>0 for r in selected),
              [(r['command'],r['mode'],r['atomic'],r['delta']) for r in selected], flush=True)


if __name__ == '__main__':
    main()
