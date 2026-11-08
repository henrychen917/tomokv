#!/usr/bin/env python3
"""Rebase compile-only inlining trials onto the final integration source.

The first round scores linked images against the frozen lane and mainline arms.
This round preserves that selection's headroom after subsequent cold fixes,
then chooses the object retaining the most previously selected hot bodies.
The final linked audit and instruction census remain the acceptance checks.
"""
import os
os.environ['WAVE15_BUDGET_ROUND'] = '-final'
from concurrent.futures import ProcessPoolExecutor
import json
import re
from pathlib import Path
import wave15_budgets as b

def compare(job):
    old, new = job
    def functions(path):
        elf = b.audit.Elf(Path(path))
        return {name: elf.canonical(body) for name, body in elf.functions().items()}
    before, after = functions(old['output']), functions(new['output'])
    changed = [name for name in before if before[name] != after.get(name)]
    def contains(name, tokens): return any(token in name for token in tokens)
    return dict(new, score=[
        sum(contains(n, ('FlatStore4find', 'FlatStore15find_read_local')) for n in changed),
        sum(contains(n, ('cmd_get', 'cmd_set', 'cmd_incr', 'cmd_mget', 'cmd_mset')) for n in changed),
        sum(contains(n, ('process_input', 'parse', 'drain_client', 'send_client', 'recv_client')) for n in changed),
        len(changed)], changed_symbols=changed)

def main():
    b.OUT.mkdir(parents=True, exist_ok=True); b.DOC.mkdir(parents=True, exist_ok=True)
    choices = json.loads((b.ROOT/'docs/wave15/budgets/selected.json').read_text())
    old = {r['object']: next(t for t in r['trials'] if t['budget'] == r['budget']) for r in choices}
    workers = int(os.getenv('WAVE15_BUILD_WORKERS', '12'))
    with ProcessPoolExecutor(workers) as pool:
        current = list(pool.map(b.trial, [dict(arm='post', object=o, budget=r['budget']) for o,r in old.items()]))
        trials = []
        for row in current:
            previous = old[row['object']]
            center = previous['budget'] + row['unit'] - previous['unit']
            for value in sorted({row['budget'], center-8, center, center+8}):
                trials.append(dict(arm='post', object=row['object'], budget=value, derived=center))
        compiled = list(pool.map(b.trial, trials))
        # Cache hits retain their original metadata; attach this round's derivation.
        compiled = [dict(c, **j) for c,j in zip(compiled, trials)]
        unique = {}
        for row in compiled: unique.setdefault((row['object'], row['code_digest']), row)
        scores = list(pool.map(compare, [(old[r['object']], r) for r in unique.values()]))
    by = {(r['object'],r['code_digest']):r for r in scores}
    selected = []
    makefile = b.ROOT/'Makefile'; text = makefile.read_text()
    for obj, previous in old.items():
        options = [dict(r, score=by[obj,r['code_digest']]['score']) for r in compiled if r['object']==obj]
        best = min(options, key=lambda r:(r['score'], abs(r['budget']-r['derived']), r['budget']!=previous['budget']))
        selected.append(dict(object=obj, previous=previous, selected=best, trials=options))
        pattern = r'(^\$\(BUILD_ROOT\)/'+re.escape(obj)+r':[^\n]*large-unit-insns=)\d+'
        text, count = re.subn(pattern, lambda m:m[1]+str(best['budget']), text, flags=re.M)
        assert count==1, obj
        print('selected', obj, previous['budget'], '->', best['budget'], best['score'], flush=True)
    (b.DOC/'selected.json').write_text(json.dumps(selected,indent=2)+'\n')
    (b.DOC/'scored.json').write_text(json.dumps(scores,indent=2)+'\n')
    makefile.write_text(text)

if __name__ == '__main__': main()
