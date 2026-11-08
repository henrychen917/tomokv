#!/usr/bin/env python3
"""Offline PAD-A construction and strict linked hot-body inventory; no workloads."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/rlfix5'
DOC = ROOT / 'docs/rlfix5'
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'docs/wave9')]
from wave13_counts import sha, save


def text_size(binary):
    lines = subprocess.check_output(['size', '-A', str(binary)], text=True).splitlines()
    return int(next(x.split()[1] for x in lines if x.startswith('.text ')))


def pad():
    pre, post, output = (BUILD / arm for arm in ('PRE', 'POST', 'PAD-A'))
    directory = BUILD / 'pad-a'; directory.mkdir(exist_ok=True)
    wanted, before = text_size(post), text_size(pre)
    meta = json.loads((DOC / 'counts/pre/normal-build.json').read_text())
    link = [x for x in meta['link'] if not x.endswith('/probe.o')]
    link = [str(BUILD / 'pre/objects/db0/src/main.o') if x.endswith('/original-main.o') else x for x in link]
    link[link.index('-o') + 1] = str(output)
    compacted = []
    if wanted < before:
        # PRE source/behaviour, tighter alignment only in the cold CONFIG/INFO TUs.
        # This controls total text size, not individual function placement.
        root = directory / 'objects'
        compacted = ['src/cmd/t_server.o', 'db0/src/cmd/t_server.o']
        flags = ('-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread '
                 '-falign-functions=1 -falign-loops=1 -falign-jumps=1 -falign-labels=1')
        with (directory / 'compile.log').open('w') as log:
            subprocess.run(['make', '-j8', 'BUILD_ROOT=' + str(root), 'CXXFLAGS=' + flags,
                            *[str(root / name) for name in compacted]],
                           cwd=BUILD / 'pre/source', stdout=log, stderr=subprocess.STDOUT, check=True)
        replacements = {str(BUILD / 'pre/objects' / name): str(root / name) for name in compacted}
        link = [replacements.get(x, x) for x in link]
    subprocess.run(link, check=True)
    compact_size = text_size(output)
    padding = wanted - compact_size
    assert padding >= 0, 'cold alignment did not create enough room for PAD-A'
    for _ in range(3):
        source, obj = directory / 'pad.S', directory / 'pad.o'
        source.write_text('.section .text.rlfix5_pad,"ax",@progbits\n'
            '.globl tomo_rlfix5_pad\n.type tomo_rlfix5_pad,@function\n'
            f'tomo_rlfix5_pad:\n.fill {padding},1,0x90\n'
            '.size tomo_rlfix5_pad,.-tomo_rlfix5_pad\n'
            '.section .note.GNU-stack,"",@progbits\n')
        subprocess.run(['g++', '-c', str(source), '-o', str(obj)], check=True)
        subprocess.run(link + [str(obj)], check=True)
        actual = text_size(output)
        if actual == wanted:
            break
        padding += wanted - actual
    assert text_size(output) == wanted
    save(DOC / 'pad-a.json', dict(kind='A: behaviour twin', behaviour='ea48a6b272 PRE',
        control='PRE behaviour plus unreferenced NOPs; POST total .text size. '
                'Individual function placement is not matched.',
        pre_text_bytes=before, post_text_bytes=wanted, pad_text_bytes=text_size(output),
        compact_text_bytes=compact_size, cold_alignment_compacted=compacted,
        nop_bytes=padding, link=link + [str(obj)], sha256=sha(output)))


def identity():
    import identity as census
    from wave12_normalize import install
    install(census.audit)
    census.OUT = BUILD / 'identity-cache'
    arms = ('PRE', 'POST', 'PAD-A')
    with ThreadPoolExecutor(max_workers=3) as pool:
        data = dict(zip(arms, pool.map(lambda arm: census.inventory(BUILD / arm), arms)))
    # Include every production body actually entered by our command scopes,
    # beyond the gate's historical hot-name patterns.
    for label in ('pre', 'post', 'pre-scatter', 'post-scatter'):
        for row in json.loads((DOC / 'counts' / label / 'counts.json').read_text())['rows']:
            census.COUNTED_HOT.update(census.audit.canonical(name) for name in row['functions'])
    changed = census.compare(data['POST'], {'headline': data['PRE']})
    changed = [r for r in changed if not r['equal']]
    for row in changed:
        row['pre_bodies'] = data['PRE']['groups'].get(row['name'], [])
        row['post_bodies'] = data['POST']['groups'].get(row['name'], [])
    save(DOC / 'changed-bodies.json', changed)
    hot = [r for r in changed if r['hot']]
    save(DOC / 'changed-hot-bodies.json', hot)
    pad_changed = [r for r in census.compare(data['PAD-A'], {'headline': data['PRE']}) if not r['equal']]
    save(DOC / 'pad-a-changed-bodies.json', pad_changed)
    save(DOC / 'artifacts.json', {arm: dict(path=str(BUILD / arm), sha256=sha(BUILD / arm),
        text_bytes=text_size(BUILD / arm)) for arm in arms})
    lines = ['Changed hot symbol groups (strict gate normalization; identity is a proxy):', '',
             'Every emitted body has its address, size and normalized digest in changed-hot-bodies.json.', '']
    lines += [f"- `{r['name']}`: PRE {r['headline_sizes']}, POST {r['post_sizes']} bytes" for r in hot]
    (DOC / 'changed-hot-bodies.md').write_text('\n'.join(lines) + '\n')
    print('Changed bodies:', len(changed), 'hot:', len(hot), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('pad', 'identity'))
    a = p.parse_args()
    pad() if a.action == 'pad' else identity()
