#!/usr/bin/env python3
"""Use compile-only budget trial objects in finite serverless scopes."""
import concurrent.futures
import argparse
import json
from pathlib import Path
import subprocess
import flushfix2_counts as counts

ROOT = counts.ROOT
BUILD = ROOT / 'build/flushfix2/budget-counts'
OUT = ROOT / 'docs/flushfix2/budget-counts'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--current', action='store_true')
    p.add_argument('--values', help='explicit compile-only trial budgets')
    args = p.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    counts.BUILD, counts.OUT, counts.scope.BUILD = BUILD, OUT, BUILD
    subprocess.run(['gcc', '-O2', str(ROOT / 'tools/crlffix_step.c'), '-o', str(BUILD / 'step')], check=True)
    prepared = {}
    for ns, unit in [('normal', 'src/cmd/xshard.o'), ('db0', 'db0/src/cmd/xshard.o')]:
        stem = unit.replace('/', '_')
        pre = json.loads((ROOT / 'docs/flushfix2/budgets' / (stem+'-pre.json')).read_text())
        post = json.loads((ROOT / 'docs/flushfix2/budgets' / (stem+'-current.json')).read_text())
        centre = pre['old_budget'] + post['initial'] - pre['initial']
        values = args.values.split(',') if args.values else (
            ('current',) if args.current else (centre-2, centre, centre+2))
        for value in values:
            arm = str(value)
            dest = BUILD / (arm+'-'+ns)
            dest.mkdir(exist_ok=True)
            obj = ROOT / 'build/flushfix2/budgets' / (stem+'-'+arm+'.o')
            assert obj.exists()
            receipt = json.loads((ROOT / 'docs/flushfix2/counts' / ('post-'+ns+'-build.json')).read_text())
            link = [str(obj) if x == str(ROOT/'build'/unit) else x for x in receipt['link']]
            assert str(obj) in link
            link[link.index('-o')+1] = str(dest/'probe')
            subprocess.run(link, stdout=subprocess.DEVNULL, check=True)
            prepared[arm, ns] = counts.fast.prepare(arm, ns)
    cases = [(arm, ns, command, '1s', batch, atomic, -1) for arm, ns in prepared
             for command in ('MGET', 'MSET') for batch in (1, 32) for atomic in (0, 1)]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda case: counts.run(case, prepared), cases))
    (OUT/'results.json').write_text(json.dumps(rows, indent=2)+'\n')


if __name__ == '__main__':
    main()
