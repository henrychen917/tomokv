#!/usr/bin/env python3
"""Bounded compiler-only fanout trials, judged by finite production command scopes."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import wave13_counts as counts
import wave13_budgets as budgets
OUT = ROOT / 'build/wave13/fanout-trials'
DOC = ROOT / 'docs/wave13/fanout-trials'


def trial(item):
    ns, budget, automatic = item
    name = f'{ns}-{budget}-{automatic}'
    dest = OUT / name
    dest.mkdir(parents=True, exist_ok=True)
    receipt = DOC / (name + '.json')
    if receipt.exists():
        return json.loads(receipt.read_text())
    unit = ('db0/' if ns == 'db0' else '') + 'src/cmd/xshard.o'
    cmd = budgets.recipe('post', unit)
    cmd = ['-g0' if x == '-g' else 'large-unit-insns=' + str(budget)
           if x.startswith('large-unit-insns=') else 'max-inline-insns-auto=' + str(automatic)
           if x.startswith('max-inline-insns-auto=') else x for x in cmd]
    obj = dest / 'xshard.o'
    cmd[cmd.index('-o') + 1] = str(obj)
    with (dest / 'build.log').open('w') as log:
        subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    template = json.loads((counts.DOC / 'initial-post' / (ns + '-build.json')).read_text())
    link = [str(obj) if x == str(ROOT / 'build' / unit) else x for x in template['link']]
    assert str(obj) in link
    probe = dest / 'probe'
    link[link.index('-o') + 1] = str(probe)
    with (dest / 'link.log').open('w') as log:
        subprocess.run(link, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    prepared = counts.prepare(probe, ROOT / 'build', ns, 'complete')
    rows = [counts.trace(prepared, 'fanout-' + name, ns, 'complete', command, mode, 1, atomic)
            for command in ('MGET', 'MSET') for mode in ('1s', '2s') for atomic in (0, 1)]
    result = dict(namespace=ns, budget=budget, automatic=automatic, compile=cmd, link=link,
                  object_sha256=hashlib.sha256(obj.read_bytes()).hexdigest(), rows=rows)
    receipt.write_text(json.dumps(result, indent=2) + '\n')
    print('FANOUT', name, [r['total'] for r in rows], flush=True)
    return result


def main():
    assert os.sched_getaffinity(0) <= set(range(16))
    OUT.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    cases = []
    for ns, budget, automatic in (('normal', 156257, 14), ('db0', 159264, 18)):
        cases += [(ns, budget, a) for a in (12, 14, 16, 18, 20)]
        cases += [(ns, budget + d, automatic) for d in (128, 512, 2048)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(trial, cases))
    (DOC / 'trials.json').write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
