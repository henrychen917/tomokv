#!/usr/bin/env python3
"""wave3 identity attribution (adapted from docs/wave2/tools/attribute.py). Offline ELF body
comparison only; never runs a binary.

PRE is f821104a9 (wave 2), the base of the integration branch. Every wave-3 lane branches from
991d48f65 (BASE, wave 2's own base), so a lane "changed" a body when the lane tip's own default
build differs from the 991d48f65 default build, and wave 2 "changed" it when f821104a9 differs
from 991d48f65. For every production object, compare every function body of the integrated
build (M) with PRE in tools/ccfix_audit.py's canonical form (opcodes + resolved relocation
targets, with its TLS/data-object/code-address extensions). For each changed body record which
change-sets changed that symbol (the five lanes, plus `wave2`) and which lane bodies M equals.
mkfix's reference is 5b8ab21f4 (mkfix2 A+B): part C is reverted on this branch.

Classes: A lane-identical (exactly one change-set changed it and M equals that lane's body),
B multi-change-set composite, C unattributed (nothing changed the symbol), D one change-set
changed it but M differs from its body (for `wave2`: M is not f821104a9's body).
Hot = tools/lbstall_artifacts.py HOT plus ccfix_audit's ExLoopT<...>::run( (HOT already names
ExLoopT<true>::prepare_local_read since wave 2).

  attribute.py <out.json> [--objects o1 o2 ...] [--merged DIR] [--jobs N]
"""
import argparse, json, re, subprocess, sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

WT = Path('/home/user/Projects/cx-wave3')
sys.path.insert(0, str(WT / 'tools'))
import ccfix_audit  # noqa: F401  (patches lbstall_artifacts.Elf.canonical/target)
import lbstall_artifacts as audit

LANES = ['respresume', 'rlfix', 'mkfix', 'aoforder', 'hexpread']
REFS = WT / 'build/wave3/refs'
PRE = REFS / 'pre-src/build'            # f821104a9 default build
BASE = REFS / 'base991-src/build'       # 991d48f65 default build (every wave-3 lane's base)
LANE_DIRS = {l: REFS / f'{l}-src/build' for l in LANES}
HOT_EXTRA = re.compile(r'ExLoopT<.*>::run\(|ExLoopT<true>::prepare_local_read')


def is_hot(name):
    return bool(audit.HOT.search(name) or HOT_EXTRA.search(name))


def objects(merged=WT / 'build'):
    merged = Path(merged)
    return sorted(str(p.relative_to(merged)) for p in merged.rglob('*.o')
                  if p.relative_to(merged).parts[0] in ('src', 'db0')
                  and (p.relative_to(merged).parts[0] == 'src' or p.relative_to(merged).parts[1] == 'src'))


class Lazy:
    def __init__(self, path):
        self.path, self.elf, self.funcs, self.cache = Path(path), None, None, {}

    def load(self):
        if self.elf is None:
            self.elf = audit.Elf(self.path) if self.path.exists() else None
            self.funcs = self.elf.functions() if self.elf else {}

    def canon(self, name):
        self.load()
        if name not in self.funcs:
            return None
        if name not in self.cache:
            self.cache[name] = self.elf.canonical(self.funcs[name])
        return self.cache[name]

    def size(self, name):
        self.load()
        return self.funcs[name]['size'] if name in self.funcs else 0


_REF = {}


def ref(path):
    # Reference builds never change during a run: reuse parsed ELF/canonical bodies across trials.
    if path not in _REF:
        _REF[path] = Lazy(path)
    return _REF[path]


def tset(c):
    return None if c is None else Counter(repr(t[2]) for t in c[1])


def run(obj, merged):
    for path in [p for p in _REF if not str(p).endswith('/' + obj)]:
        del _REF[path]
    m, pre, base = Lazy(Path(merged) / obj), ref(PRE / obj), ref(BASE / obj)
    lanes = {l: ref(LANE_DIRS[l] / obj) for l in LANES}
    m.load(); pre.load(); base.load()
    names = sorted(set(m.funcs) | set(pre.funcs))
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    rows, equal, hot_total, hot_equal = [], 0, 0, 0
    for sym, name in zip(names, labels):
        hot = is_hot(name)
        cm, cp = m.canon(sym), pre.canon(sym)
        hot_total += hot
        if cm is not None and cm == cp:
            equal += 1; hot_equal += hot
            continue
        cb = base.canon(sym)
        changed, match = [], []
        for l, lz in lanes.items():
            cl = lz.canon(sym)
            if cl != cb:
                changed.append(l)
            if cl == cm and (cm is not None or cl != cb):
                match.append(l)
        if cp != cb:
            changed.append('wave2')
        kind = ('added' if cp is None else 'removed' if cm is None else
                'reloc-only' if cm[0] == cp[0] else 'code')
        tm = tset(cm)
        if not changed:
            cls = 'C'
        elif len(changed) == 1 and changed[0] in match:
            cls = 'A'
        elif len(changed) > 1:
            cls = 'B'
        else:
            cls = 'D'
        targets_lane = [l for l in changed if l != 'wave2' and tm is not None and
                        tm == tset(lanes[l].canon(sym))]
        if 'wave2' in changed and tm is not None and tm == tset(cp):
            targets_lane.append('wave2')
        rows.append(dict(object=obj, symbol=sym, name=name, hot=hot, kind=kind, cls=cls,
                         pre_size=pre.size(sym), post_size=m.size(sym), base_size=base.size(sym),
                         lanes_changed=changed, merged_equals_lane=match,
                         merged_equals_base=cm is not None and cm == cb,
                         targets_equal_pre=tm is not None and tm == tset(cp),
                         targets_equal_lane=targets_lane,
                         lane_sizes={l: lanes[l].size(sym) for l in changed if l != 'wave2'}))
    by_name = {r['name']: r for r in rows}
    for r in rows:
        if '::r7_' in r['name'] and not r['lanes_changed']:
            base_row = by_name.get(r['name'].replace('::r7_', '::'))
            if base_row and base_row['lanes_changed']:
                r['r7_mirror_of'] = base_row['lanes_changed']
    return dict(object=obj, total=len(names), equal=equal, hot=hot_total, hot_equal=hot_equal,
                rows=rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('out')
    p.add_argument('--objects', nargs='*')
    p.add_argument('--merged', default=str(WT / 'build'))
    p.add_argument('--jobs', type=int, default=12)
    a = p.parse_args()
    objs = a.objects or objects(a.merged)
    results = []
    with ProcessPoolExecutor(a.jobs) as pool:
        for r in pool.map(run, objs, [a.merged] * len(objs)):
            cls = Counter(x['cls'] for x in r['rows'])
            hcls = Counter(x['cls'] for x in r['rows'] if x['hot'])
            print(f"{r['object']}: {r['total']} bodies, {len(r['rows'])} changed {dict(cls)}, "
                  f"hot {r['hot_equal']}/{r['hot']} changed-hot {dict(hcls)}", flush=True)
            results.append(r)
    Path(a.out).write_text(json.dumps(results, indent=1) + '\n')
    rows = [x for r in results for x in r['rows']]
    print(json.dumps(dict(objects=len(results), bodies=sum(r['total'] for r in results),
                          equal=sum(r['equal'] for r in results), changed=len(rows),
                          hot=sum(r['hot'] for r in results),
                          hot_equal=sum(r['hot_equal'] for r in results),
                          classes=dict(Counter(x['cls'] for x in rows)),
                          hot_classes=dict(Counter(x['cls'] for x in rows if x['hot'])))))


if __name__ == '__main__':
    main()
