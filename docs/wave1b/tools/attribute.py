#!/usr/bin/env python3
"""wave1b identity attribution (adapted from cx-wave1's docs/wave1/tools/attribute.py: seven
correctness lanes, no perfex; reference builds rebuilt from git archive under build/wave1b/refs).
Offline ELF body comparison only (never runs a binary).

For every production object, compare every function body of the wave1b build (M) with the
origin/cpp 1ba80bd4e default build (B1), using tools/ccfix_audit.py's canonical form (opcodes +
resolved relocation targets, TLS/data-object/code-address extensions). For each changed body,
record which lanes changed that same symbol on their own branch (lane POST vs the shared
5146b78ee PRE, B0), whether aoffix2 changed it (B1 vs B0), which lane POST bodies the merged
body equals, whether it equals the bisection build B4 (b959fc844, lanes' own budgets), and
whether it is one of the cherry-picked climon fix's drain bodies (ec0317384). Usage:
  attribute.py <out.json> [--objects o1 o2 ...] [--merged DIR] [--jobs N]
"""
import argparse, json, os, re, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

WT = Path('/home/user/Projects/cx-wave1b')
sys.path.insert(0, str(WT / 'tools'))
import ccfix_audit  # noqa: F401  (patches lbstall_artifacts.Elf.canonical/target)
import lbstall_artifacts as audit

LANES = ['scriptfix', 'savefix', 'aclfix', 'authfix', 'clientfix', 'racefix', 'flipfix']
REFS = WT / 'build/wave1b/refs'
B0 = REFS / 'b0-src/build'                                           # 5146b78ee default build
B1 = REFS / 'pre-src/build'                                          # origin/cpp 1ba80bd4e
B4 = WT / 'build/wave1b/b4-build'      # frozen copy of /home/user/Projects/bisect-w1/b4/build
LANE_DIRS = {l: REFS / f'{l}-src/build' for l in LANES}              # lane heads, own Makefiles
# The cherry-picked climon fix (ec0317384): the cold suppressing drain gains `retire_plain`
# (renamed instantiations), its two climon callers pass it, and tracking.o gains the helper.
CLIMONFIX = re.compile(r'serve_suppressing|prepare_suppressing|climon_serve_suppressed|'
                       r'climon_prepare_suppressed|tracking_retire_plain')
HOT_RUN = re.compile(r'ExLoopT<.*>::run\(')


def objects():
    proof = json.loads((WT / 'docs/ttlclean/proof.json').read_text())
    return proof['production_objects']


class Lazy:
    def __init__(self, path):
        self.path, self.elf, self.funcs, self.cache = path, None, None, {}
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
    # Reference builds never change during a run: reuse their parsed ELF and canonical bodies
    # across trial classifications of the same object (objdump dominates the cost).
    if path not in _REF:
        _REF[path] = Lazy(path)
    return _REF[path]


def run(obj, merged):
    for path in [p for p in _REF if not str(p).endswith('/' + obj)]:
        del _REF[path]
    m, b1, b0, b4 = Lazy(merged / obj), ref(B1 / obj), ref(B0 / obj), ref(B4 / obj)
    lanes = {l: ref(LANE_DIRS[l] / obj) for l in LANES}
    m.load(); b1.load()
    names = sorted(set(m.funcs) | set(b1.funcs))
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    rows, equal = [], 0
    hot_total = hot_equal = 0
    for sym, name in zip(names, labels):
        hot = bool(audit.HOT.search(name) or HOT_RUN.search(name))
        cm, c1 = m.canon(sym), b1.canon(sym)
        hot_total += hot
        if cm is not None and cm == c1:
            equal += 1; hot_equal += hot
            continue
        c0 = b0.canon(sym)
        lane_changed, lane_match = [], []
        for l, lz in lanes.items():
            cl = lz.canon(sym)
            if cl != c0:
                lane_changed.append(l)
            if cl == cm and (cm is not None or cl != c0):
                lane_match.append(l)   # same body, or the same removal
        kind = ('added' if c1 is None else 'removed' if cm is None else
                'reloc-only' if cm[0] == c1[0] else 'code')
        from collections import Counter
        tset = lambda c: None if c is None else Counter(repr(t[2]) for t in c[1])
        tm = tset(cm)
        targets_equal_pre = tm is not None and tm == tset(c1)
        targets_equal_lane = [l for l in lane_changed if tm is not None and tm == tset(lanes[l].canon(sym))]
        rows.append(dict(object=obj, symbol=sym, name=name, hot=hot, kind=kind,
                         pre_size=b1.size(sym), post_size=m.size(sym),
                         aoffix2_changed=c1 != c0, lanes_changed=lane_changed,
                         merged_equals_lane=lane_match,
                         merged_equals_b0=(cm is not None and cm == c0),
                         merged_equals_b4=(cm == b4.canon(sym)),
                         climonfix=bool(CLIMONFIX.search(name)),
                         targets_equal_pre=targets_equal_pre, targets_equal_lane=targets_equal_lane))
    # R7 generated copies mirror ordinary methods: attribute an r7_ body to the lanes that
    # changed its source method in the same object (tests/r7shadow_sync.py regenerates them).
    by_name = {r['name']: r for r in rows}
    for r in rows:
        if '::r7_' in r['name'] and not r['lanes_changed']:
            base = by_name.get(r['name'].replace('::r7_', '::'))
            if base and base['lanes_changed']:
                r['r7_mirror_of'] = base['lanes_changed']
    return dict(object=obj, total=len(names), equal=equal, hot=hot_total, hot_equal=hot_equal, rows=rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('out')
    p.add_argument('--objects', nargs='*')
    p.add_argument('--merged', default=str(WT / 'build'))
    p.add_argument('--jobs', type=int, default=12)
    a = p.parse_args()
    objs = a.objects or objects()
    merged = Path(a.merged)
    results = []
    with ProcessPoolExecutor(a.jobs) as pool:
        for r in pool.map(run, objs, [merged] * len(objs)):
            print(f"{r['object']}: {r['total']} bodies, {len(r['rows'])} changed, hot {r['hot_equal']}/{r['hot']}", flush=True)
            results.append(r)
    Path(a.out).write_text(json.dumps(results, indent=1) + '\n')


if __name__ == '__main__':
    main()
