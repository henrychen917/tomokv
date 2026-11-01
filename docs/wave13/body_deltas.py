#!/usr/bin/env python3
"""Retain normalized instruction evidence for every residual linked-body group."""
from concurrent.futures import ProcessPoolExecutor
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import wave13
from wave12_normalize import install
identity = wave13.references()
install(identity.audit)
DOC = ROOT/'docs/wave13/identity'
BUILD = ROOT/'build/wave13/body-deltas'
residual = [r for r in json.loads((DOC/'changed-bodies.json').read_text()) if not r['matches']]


def inventory(item):
    label, path = item
    out = BUILD/label
    out.mkdir(parents=True, exist_ok=True)
    cache = out/'selected.json.gz'
    if cache.exists():
        with gzip.open(cache, 'rt') as stream:
            return label, json.load(stream)
    binary = identity.audit.Binary(path, out, literal_pools=True)
    groups = {r['name']: sorted(binary.groups.get(r['name'], []), key=lambda b: b['addr']) for r in residual}
    result = dict(path=str(path), sha256=binary.sha256, groups=groups)
    with gzip.open(cache, 'wt') as stream:
        json.dump(result, stream)
    for dump in out.glob('*.objdump'):
        dump.unlink()
    return label, result


def main():
    arms = {k:v for k,v in identity.REFS.items() if not k.startswith('baseline_')}
    arms['POST'] = str(ROOT/'build/wave13/tomokv-POST')
    with ProcessPoolExecutor(5) as pool:
        inventories = dict(pool.map(inventory, arms.items()))
    rows = []
    for row in residual:
        name = row['name']
        references = {}
        after = inventories['POST']['groups'][name]
        for label in arms:
            if label == 'POST':
                continue
            before = inventories[label]['groups'][name]
            pairs = []
            for index in range(max(len(before),len(after))):
                a = before[index] if index < len(before) else dict(ins=[], encodings=[], size=0)
                b = after[index] if index < len(after) else dict(ins=[], encodings=[], size=0)
                delta = list(difflib.unified_diff(a['ins'], b['ins'], fromfile=label, tofile='POST', n=2))
                pairs.append(dict(instance=index, pre_size=a['size'], post_size=b['size'],
                                  instruction_diff=delta,
                                  encoding_equal=a['encodings']==b['encodings']))
            references[label] = pairs
        rows.append(dict(name=name, references=references))
    with gzip.open(DOC/'residual-instruction-deltas.json.gz', 'wt') as stream:
        json.dump(dict(arms={k:dict(path=v['path'],sha256=v['sha256']) for k,v in inventories.items()},
                       rows=rows), stream)
    print(len(rows), 'residual groups with all reference instruction diffs')


if __name__ == '__main__':
    main()
