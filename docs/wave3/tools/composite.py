#!/usr/bin/env python3
"""wave3: decompose multi-lane composite bodies (attribute.py class B). Offline; never runs a binary.

For every B body (default: hot ones) that is changed only by wave-3 lanes, disassemble the
f821104a9 body (W), each changing lane's own body (L1, L2, ...) and the integrated body (M) with
objdump -d -r -w, and normalize each instruction: no addresses; relocations by type and symbol
(section-relative targets such as .text+0x123 and constant-pool ordinals .LCn, which move with
every placement change, and intra-function branch targets become placeholders).

Checks, from strongest to weakest, each on the whole normalized instruction sequence:
  equals-<lane>   M is exactly that lane's own body (the other lane's change to this body was code
                  generation only, e.g. no marker instruction in its own build either);
  additive        the lanes' W->Li edit scripts (difflib opcodes) touch disjoint W ranges and
                  applying all of them reproduces M exactly;
  projection      for some lane Li, the edits Li->M are exactly the other lanes' W->Lj edits (the
                  same removed/inserted instruction runs, as a multiset): M is Li's own body plus
                  the other lanes' changes;
  projection/reg  the same with general-purpose register names replaced by one placeholder, i.e.
                  modulo register allocation of the combined function;
  contains        every instruction run another lane inserts (W->Lj, register placeholder) occurs
                  in M, and so does every run Li inserts: M carries each lane's own change;
  calls+markers   the call/jump relocation-target multiset is additive (M = L1 + L2 - W) and each
                  lane's marker instructions occur in M exactly as often as in that lane's own body
                  (respresume: the pending-bit load from Client+0x4c and the frontier lea of
                  Client+0x60; mkfix2 A: the and $0xfffffffb / cmp $0xfffffffa completed-tag test),
                  i.e. both changes are present and the residual is the combined function's
                  register allocation and scheduling.
usage: composite.py <attr.json> <out.json> [--all] [--merged=DIR]
"""
import difflib, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import attribute as A

INSN = re.compile(r'^\s*[0-9a-f]+:\t(.*)$')
INLINE_RELOC = re.compile(r'\s[0-9a-f]+: (R_X86_64_\S+)\s+(\S+)')
REGS = re.compile(r'%(?:[re]?(?:ax|bx|cx|dx|si|di|bp|sp)|[abcd]l|[sd]il|[bs]pl|r(?:[89]|1[0-5])[dwb]?)\b')


def norm_target(target):
    # Constant-pool ordinals (.LCn) shift whenever the unit gains a constant; section-relative
    # code targets move with placement. Both become placeholders (lbstall's canonical form
    # resolves them to content/function; this text view only needs them address-free).
    target = re.sub(r'\.LC\d+', '.LC?', target)
    return re.sub(r'^\.text(?:\.\S+)?(?:\+0x[0-9a-f]+|-0x[0-9a-f]+)?$', '.text+?', target)


def disassemble(obj, symbol):
    text = subprocess.check_output(['objdump', '-d', '-r', '-w', '--no-show-raw-insn',
                                    f'--disassemble={symbol}', str(obj)], text=True)
    out = []
    for line in text.splitlines():
        m = INSN.match(line)
        if not m:
            continue
        body = m[1]
        relocs = [f'@{t}:{norm_target(s)}' for t, s in INLINE_RELOC.findall(body)]
        body = INLINE_RELOC.sub('', body).split('#')[0]
        ins = re.sub(r'\s+', ' ', body).strip()
        ins = re.sub(r'\b[0-9a-f]+ <[^>]*>', '<L>', ins)   # branch/call targets: placeholder
        out.append(' '.join([ins] + relocs))
    return out


def regless(seq):
    return [REGS.sub('%R', s) for s in seq]


def merge(base, scripts):
    """Apply several W->L edit scripts to W; None if two edits overlap."""
    spans = []
    for name, other in scripts:
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, other, autojunk=False).get_opcodes():
            if tag != 'equal':
                spans.append((i1, i2, other[j1:j2], name))
    spans.sort(key=lambda s: (s[0], s[1]))
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1] or (b[0] == a[1] == b[1] == a[0]):
            return None
    merged, at = [], 0
    for i1, i2, repl, _ in spans:
        merged += base[at:i1] + repl
        at = i2
    return merged + base[at:]


def edits(a, b):
    return sorted((tuple(a[i1:i2]), tuple(b[j1:j2]))
                  for t, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
                  if t != 'equal')


def contains(haystack, needle):
    if not needle:
        return True
    n = len(needle)
    return any(haystack[i:i + n] == list(needle) for i in range(len(haystack) - n + 1))


MARKERS = {'respresume': [re.compile(r'0x4c\(%r\w+\),%'), re.compile(r'lea 0x60\(%r\w+\),%')],
           'mkfix': [re.compile(r'and \$0xfffffffb,'), re.compile(r'cmp \$0xfffffffa,')]}


def calls(seq):
    from collections import Counter
    return Counter(s.split(' @', 1)[1] for s in seq if s.startswith(('call', 'jmp')) and ' @' in s)


def markers(seq, lane):
    return [sum(bool(rx.search(s)) for s in seq) for rx in MARKERS.get(lane, [])]


def analyse(w, m, lanes):
    result = {}
    result['additive'] = merge(w, list(lanes.items())) == m
    result['projection'] = [l for l in lanes if edits(lanes[l], m) ==
                            sorted(e for o in lanes if o != l for e in edits(w, lanes[o]))]
    rw, rm = regless(w), regless(m)
    rl = {l: regless(b) for l, b in lanes.items()}
    result['projection_reg'] = [l for l in rl if edits(rl[l], rm) ==
                                sorted(e for o in rl if o != l for e in edits(rw, rl[o]))]
    inserted = {l: [new for old, new in edits(rw, rl[l]) if new] for l in rl}
    result['contains'] = {l: all(contains(rm, run) for run in runs) for l, runs in inserted.items()}
    result['lane_edit_runs'] = {l: len(edits(w, b)) for l, b in lanes.items()}
    expected = calls(w)
    for b in lanes.values():
        expected = expected + calls(b)
    expected = expected - calls(w) * len(lanes) if False else expected
    # M = W + sum(Li - W): compute with signed counts.
    from collections import Counter
    signed = Counter(calls(w))
    for b in lanes.values():
        for k, v in calls(b).items():
            signed[k] += v
        for k, v in calls(w).items():
            signed[k] -= v
    result['calls_additive'] = {k: v for k, v in signed.items() if v} == dict(calls(m))
    result['markers'] = {l: dict(pre=markers(w, l), lane=markers(b, l), merged=markers(m, l))
                         for l, b in lanes.items() if l in MARKERS}
    result['markers_present'] = all(v['merged'] == v['lane'] and v['lane'] != v['pre']
                                    for v in result['markers'].values()) if result['markers'] else False
    return result


def main():
    attr = json.load(open(sys.argv[1]))
    everything = '--all' in sys.argv
    merged_dir = Path(next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--merged=')), A.WT / 'build'))
    rows = []
    for r in attr:
        for x in r['rows']:
            if x['cls'] != 'B' or (not everything and not x['hot']) or 'wave2' in x['lanes_changed']:
                continue
            obj = x['object']
            w = disassemble(A.PRE / obj, x['symbol'])
            m = disassemble(merged_dir / obj, x['symbol'])
            lanes = {l: disassemble(A.LANE_DIRS[l] / obj, x['symbol']) for l in x['lanes_changed']}
            base = disassemble(A.BASE / obj, x['symbol'])
            res = analyse(w, m, lanes)
            same = [l for l, b in lanes.items() if b == m]
            level = ('equals-' + '+'.join(same) if same else 'additive' if res['additive'] else 'projection' if res['projection'] else
                     'projection-modulo-registers' if res['projection_reg'] else
                     'contains-every-lane-change' if all(res['contains'].values()) else
                     'calls-additive+markers' if res['calls_additive'] and res['markers_present'] else
                     'calls-additive' if res['calls_additive'] else 'unexplained')
            rows.append(dict(object=obj, name=x['name'], lanes=x['lanes_changed'], level=level,
                             pre_equals_991d48f65=base == w,
                             instructions=dict(pre=len(w), merged=len(m), **{l: len(b) for l, b in lanes.items()}),
                             **res))
            print(f"{level:28} {obj} {'+'.join(x['lanes_changed'])} {len(w)}->{len(m)} {x['name'][:96]}", flush=True)
    Path(sys.argv[2]).write_text(json.dumps(rows, indent=1) + '\n')
    from collections import Counter
    print(json.dumps(dict(bodies=len(rows), levels=dict(Counter(r['level'] for r in rows)))))


if __name__ == '__main__':
    main()
