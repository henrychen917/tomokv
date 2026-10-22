#!/usr/bin/env python3
"""Complete-frame parse-selection path of every dispatcher clone, from objdump.

Input: the disassembly inventories written by tools/respresume_artifacts.py for
PRE and POST. For each non-cold parse_and_dispatch / r7_parse_and_dispatch body:

  window = the call-free control-flow path from the op->rbuf_off store
           (`mov %eN,0x18(%rOP)`; Op::rbuf_off is at offset 24) to the call of the
           default-limit parser resp_parse_t<false[, true]>, constrained to pass
           through the inline-selection compare `cmpb $0x2a,(...)` ('*', i.e. a
           multibulk frame with bytes available); shortest such path.

Every other selection outcome (resume, inline, pre-AUTH or configured limits)
reaches a different call, so a call-free path to the default parser is exactly
the complete authenticated multibulk route. The parser body itself is counted
separately by tools/respresume_trace.py. The report lists each window's
instructions so every count can be checked by hand.
"""
import argparse
from collections import deque
import gzip
import json
from pathlib import Path
import re

DISPATCHER = re.compile(r'::IoLoop::(r7_)?parse_and_dispatch<[^()]*>\((tomo|tomo_db0)::Client\*\)'
                        r'( \[clone [^\]]*\])*$')
LINE = re.compile(r'([0-9a-f]+): (\S+)\s*(.*)')
JUMP = re.compile(r'^j\w*$')
TARGET = re.compile(r'^([0-9a-f]+) <')


def parse(body):
    insns = []
    for text in body:
        m = LINE.match(text)
        insns.append((int(m[1], 16), m[2], m[3], text))
    return insns


def successors(insns, index, by_address):
    addr, op, args, _ = insns[index]
    out = []
    if JUMP.match(op):
        m = TARGET.match(args)
        if m and int(m[1], 16) in by_address:
            out.append(by_address[int(m[1], 16)])
        if op == 'jmp':
            return out
    if op.startswith('ret') or op == 'ud2':
        return out
    if index + 1 < len(insns):
        out.append(index + 1)
    return out


def shortest(insns, by_address, start, goals):
    """BFS over call-free instructions; returns {goal: path} reachable from start."""
    previous = {start: None}
    queue = deque([start])
    while queue:
        i = queue.popleft()
        if i in goals and i != start:
            continue
        if insns[i][1].startswith('call') and i != start:
            continue
        for j in successors(insns, i, by_address):
            if j not in previous:
                previous[j] = i
                queue.append(j)
    paths = {}
    for g in goals:
        if g in previous:
            path, k = [], g
            while k is not None:
                path.append(k)
                k = previous[k]
            paths[g] = path[::-1]
    return paths


def window(row):
    insns = parse(row['instructions_text'])
    by_address = {a: i for i, (a, *_rest) in enumerate(insns)}
    hot = [i for i, x in enumerate(insns)
           if x[1].startswith('call') and re.search(r'resp_parse_t<false[,>]', x[2])]
    assert len(hot) == 1, (row['name'], len(hot))
    stars = [i for i, x in enumerate(insns) if x[1] == 'cmpb' and x[2].startswith('$0x2a,')]
    starts = [i for i, x in enumerate(insns) if x[1] == 'mov' and re.match(r'%e\w+,0x18\(%r\w+\)$', x[2])]
    best = None
    for s in starts:
        to_star = shortest(insns, by_address, s, set(stars))
        for star, head in to_star.items():
            tail = shortest(insns, by_address, star, {hot[0]}).get(hot[0])
            if tail is None:
                continue
            path = head + tail[1:]
            if best is None or len(path) < len(best):
                best = path
    assert best is not None, row['name']
    return [insns[i] for i in best]


def summarize(inventory):
    data = json.loads(gzip.decompress(inventory.read_bytes()))
    rows = []
    for row in data['rows']:
        if not DISPATCHER.search(row['name']) or '.cold' in row['name']:
            continue
        path = window(row)
        text = [p[3] for p in path]
        rows.append(dict(address=row['address'], bytes=row['bytes'], static_instructions=row['instructions'],
                         name=row['name'], window_instructions=len(path),
                         window=text))
    return data['binary'], data['sha256'], rows


def is_store(text):
    m = LINE.match(text)
    op, operands = m[2], m[3]
    if op.startswith('push'):
        return True
    return op.startswith(('mov', 'vmov')) and '(' in operands.rsplit(',', 1)[-1]


def key(name):
    # Clone identity independent of addresses: demangled name.
    return name


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('pre', type=Path)
    ap.add_argument('post', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--pre-trace', type=Path, help='fast-path.json from respresume_trace.py (PRE)')
    ap.add_argument('--post-trace', type=Path, help='fast-path.json from respresume_trace.py (POST)')
    args = ap.parse_args()
    pre_binary, pre_sha, pre = summarize(args.pre)
    post_binary, post_sha, post = summarize(args.post)
    assert len(pre) == len(post), (len(pre), len(post))
    # Same demangled name can occur several times (IPA clones); pair them in address order.
    pairs = []
    by_name = {}
    for r in pre:
        by_name.setdefault(key(r['name']), []).append(r)
    taken = {}
    for r in post:
        k = key(r['name'])
        n = taken.get(k, 0)
        pairs.append((by_name[k][n], r))
        taken[k] = n + 1
    out = dict(pre=dict(binary=pre_binary, sha256=pre_sha), post=dict(binary=post_binary, sha256=post_sha),
               clones=[dict(name=b['name'], pre_address=a['address'], post_address=b['address'],
                            pre_bytes=a['bytes'], post_bytes=b['bytes'],
                            pre_static=a['static_instructions'], post_static=b['static_instructions'],
                            pre_window=a['window_instructions'], post_window=b['window_instructions'],
                            pre_path=a['window'], post_path=b['window']) for a, b in pairs])
    traces = {}
    for tag, path in (('pre', args.pre_trace), ('post', args.post_trace)):
        if path:
            for r in json.loads(path.read_text()):
                traces[(tag, int(r['address'], 16), r['command'])] = r
    for c in out['clones']:
        for tag in ('pre', 'post'):
            call = c[f'{tag}_path'][-1]
            callee = int(TARGET.match(LINE.match(call)[3])[1], 16)
            c[f'{tag}_callee'] = hex(callee)
            c[f'{tag}_window_stores'] = sum(is_store(x) for x in c[f'{tag}_path'])
            for command in ('GET', 'SET'):
                r = traces.get((tag, callee, command))
                if r:
                    c[f'{tag}_{command}_parser'] = r['instructions']
                    c[f'{tag}_{command}_total'] = r['instructions'] + c[f'{tag}_window']
    args.output.write_text(json.dumps(out, indent=2) + '\n')
    for c in out['clones']:
        totals = ''
        if 'pre_GET_total' in c and 'post_GET_total' in c:
            totals = (f"GET {c['pre_GET_total']}->{c['post_GET_total']} "
                      f"SET {c['pre_SET_total']}->{c['post_SET_total']}  ")
        print(f"window {c['pre_window']:3}->{c['post_window']:3} stores {c['pre_window_stores']}->"
              f"{c['post_window_stores']}  {totals}bytes {c['pre_bytes']:6}->{c['post_bytes']:6}  "
              f"{c['name'][c['name'].find('IoLoop::'):][:100]}")


if __name__ == '__main__':
    main()
