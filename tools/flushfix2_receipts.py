#!/usr/bin/env python3
"""Retain compact, hashed correctness receipts before pruning build artifacts."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/flushfix2'


def read(path):
    return json.loads(path.read_text())


def ref(path):
    return dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def directed(root, expected):
    rows = []
    for path in sorted(root.glob('*/results.json')):
        for result in read(path):
            row = {k:result[k] for k in ('case', 'leg', 'databases', 'command', 'flush_mode', 'pass')}
            row['result_file'] = ref(path)
            folder = path.parent/result['leg']
            observations = sorted(folder.rglob('observations.json'))
            row['attempts'] = []
            for observation in observations:
                data = read(observation)
                row['attempts'].append(ref(observation) | {k:data.get(k) for k in
                    ('cycles', 'observations', 'torn', 'controls', 'control_final', 'errors')})
            falsifier = folder/'falsifiers.json'
            if falsifier.exists():
                row['falsifiers'] = read(falsifier)
                row['falsifier_file'] = ref(falsifier)
            if not result['pass']:
                row['error'] = result['error']
            rows.append(row)
    assert len(rows) == expected, (root, len(rows), expected)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directed', type=Path)
    p.add_argument('--siblings', action='store_true')
    p.add_argument('--pad', action='store_true')
    a = p.parse_args()
    if a.directed:
        rows = directed(a.directed.resolve()/'jobs/flushfix2', 126)
        assert all(r['pass'] for r in rows)
        for r in rows:
            if r['leg'].startswith('redis-'):
                continue
            fired = r['falsifiers'][-1]
            assert all(fired[k] > 0 for k in ('atomic_flush_units', 'atomic_flush_range_reads',
                'atomic_flush_post_versions', 'atomic_flush_script_conflicts', 'atomic_flush_slow_collapses'))
            assert fired['script_reply'] == [1, 1]
        (OUT/'post-final-witnesses.json').write_text(json.dumps(rows, indent=2)+'\n')
    if a.pad:
        rows = directed(ROOT/'build/flushfix2/pad-a-proof', 16)
        assert all(not r['pass'] and any(x['torn'] for x in r['attempts']) for r in rows)
        assert all(not x['errors'] for r in rows for x in r['attempts'])
        (OUT/'pad-a-witnesses.json').write_text(json.dumps(rows, indent=2)+'\n')
    if a.siblings:
        inventories = []
        for folder in sorted((ROOT/'build/flushfix2/siblings').iterdir()):
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob('results.json')):
                row = dict(run=folder.name, file=ref(path), results=read(path), details=[])
                for detail in sorted(path.parent.rglob('*.json')):
                    if detail.name not in ('siblings.json', 'reload-witness.json', 'server.exit.json'):
                        continue
                    row['details'].append(ref(detail) | dict(value=read(detail)))
                inventories.append(row)
        (OUT/'sibling-receipts.json').write_text(json.dumps(inventories, indent=2)+'\n')


if __name__ == '__main__':
    main()
