#!/usr/bin/env python3
"""Link the EOF trial budgets against frozen production objects; compile-only."""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from wave14 import ROOT, BUILD, DOC, references, save, sha


def score_worker(selection):
    # Forked compile-only workers inherit the immutable linked-image inventory.
    return SCORE_IMPL(selection)


def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    trials = json.loads((DOC/'eof-budgets/scan.json').read_text())
    initial = json.loads((DOC/'eof-budgets/initial.json').read_text())
    candidates = {}
    for row in trials:
        candidates.setdefault(row['object'], {}).setdefault(row['code_digest'], row)
    chosen = {r['object']: r for r in initial if r['arm'] == 'post'}
    out = BUILD/'eof-links';out.mkdir(exist_ok=True)
    base = out/'base';base.mkdir(exist_ok=True)
    recipe = subprocess.check_output(['make','-n','-W','build/src/main.o','all'], text=True)
    link = shlex.split(next(s for s in recipe.splitlines()
                           if ' -o build/tomokv ' in s))
    manifest = []
    for arg in link:
        if not arg.endswith('.o'):
            continue
        original = ROOT/arg;copied = base/arg.removeprefix('build/')
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, copied)
        manifest.append(dict(object=arg, sha256=sha(copied)))
    save(DOC/'eof-budgets/base.json', manifest)
    identity = references()
    before = identity.inventory(BUILD/'post-r7/tomokv')
    cache = {}

    def intentional(name):
        if '::epoll_pass<' in name or '::r7_epoll_pass<' in name:
            return True
        match = re.search(r'::(?:r7_)?run_loop<([^>]+)>', name)
        return bool(match and match[1].split(', ')[2] == 'true')

    def score(selection):
        key = hashlib.sha256(repr(sorted((k, v['code_digest'])
            for k,v in selection.items())).encode()).hexdigest()
        if key in cache:
            return cache[key]
        saved = DOC/'eof-budgets/links'/(key+'.json')
        if saved.exists():
            record = json.loads(saved.read_text())
            assert record['selection'] == {k:v['budget'] for k,v in selection.items()}
            cache[key] = record
            return record
        binary = out/(key+'.tomokv')
        command = [selection[a[6:]]['output'] if a.startswith('build/') and a[6:] in selection
                   else str(base/a[6:]) if a.startswith('build/') and a.endswith('.o')
                   else a for a in link]
        command[command.index('-o')+1] = str(binary)
        command += ['-Wl,--strip-debug']
        with (out/(key+'.log')).open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        after = identity.inventory(binary)
        rows = identity.compare(after, {'headline':before})
        changed = [r for r in rows if not r['equal']]
        direct = re.compile(r'::cmd_(?:get|set|mget|mset)(?:\(|<)')
        value = [sum(bool(direct.search(r['name'])) for r in changed),
                 sum('::parse_and_dispatch<' in r['name'] or
                     '::r7_parse_and_dispatch<' in r['name'] for r in changed),
                 sum(r['hot'] and not intentional(r['name']) for r in changed),
                 sum(not intentional(r['name']) for r in changed), len(changed)]
        record = dict(key=key, score=value, sha256=after['sha256'],
            selection={k:v['budget'] for k,v in selection.items()},
            command=command, changed=changed)
        save(DOC/'eof-budgets/links'/(key+'.json'), record)
        binary.unlink()
        cache[key] = record
        print('SCORE', key[:12], value, flush=True)
        return record

    current = score(chosen)
    global SCORE_IMPL
    SCORE_IMPL = score
    decisions = []
    for sweep in range(2):
        moved = False
        for obj, variants in candidates.items():
            options = [dict(chosen, **{obj:row}) for row in variants.values()]
            with ProcessPoolExecutor(max_workers=4,
                    mp_context=multiprocessing.get_context('fork')) as pool:
                results = list(pool.map(score_worker, options))
            cache.update((record['key'], record) for record in results)
            ranked = list(zip(options, results)) + [(chosen, current)]
            winner, result = min(ranked, key=lambda pair:
                (pair[1]['score'], pair[0][obj]['budget'] != chosen[obj]['budget'],
                 abs(pair[0][obj]['budget'] - pair[0][obj].get('derived', pair[0][obj]['budget']))))
            old = chosen[obj]['budget'];new = winner[obj]['budget']
            decisions.append(dict(sweep=sweep, object=obj, old=old, budget=new,
                score=result['score'], trials=[r['key'] for r in results]))
            moved |= old != new
            chosen = winner.copy();current = result
            save(DOC/'eof-budgets/selected.json',dict(chosen=chosen,score=current,
                decisions=decisions, complete=False))
        if not moved:
            break
    save(DOC/'eof-budgets/selected.json',dict(chosen=chosen,score=current,
        decisions=decisions, complete=True))
    print('SELECTED', current['score'], {k:v['budget'] for k,v in chosen.items()}, flush=True)


if __name__ == '__main__':
    main()
