#!/usr/bin/env python3
"""Attribute every serverless census delta to its executed native body."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave12'


def read(path):
    return json.loads((ROOT / path).read_text())


def key(row):
    return tuple(row[k] for k in ('namespace', 'command', 'mode', 'batch', 'atomic'))


def compare(before, after):
    old = {key(r): r for x in before for r in x['rows']}
    rows = []
    for new in after['rows']:
        k = key(new)
        if k not in old:
            continue
        pre = old[k]
        delta = {name: new['functions'].get(name, 0) - pre['functions'].get(name, 0)
                 for name in sorted(set(pre['functions']) | set(new['functions']))}
        delta = {name: n for name, n in delta.items() if n}
        assert sum(delta.values()) == new['total'] - pre['total']
        rows.append(dict(zip(('namespace', 'command', 'mode', 'batch', 'atomic'), k),
                         pre=pre['total'], post=new['total'], delta=new['total']-pre['total'],
                         function_deltas=delta))
    return rows


def main():
    files = {
        'pre': 'docs/wave12/instructions/pre/all-complete-counts.json',
        'pre_flush': 'docs/wave12/instructions/pre-flush/all-complete-counts.json',
        'post': 'docs/wave12/instructions/final-post/all-complete-counts.json',
        'pre_lua': 'docs/wave12/instructions/pre-gc/scripts-lua-counts.json',
        'post_lua': 'docs/wave12/instructions/final-gc/scripts-lua-counts.json',
        'scriptfix3': 'docs/wave11/instructions/scriptfix3/scripts-complete-counts.json',
        'scriptfix3_lua': 'docs/wave11/instructions/scriptfix3-gc/scripts-lua-counts.json',
    }
    data = {name: read(path) for name, path in files.items()}
    groups = {
        'headline_native': compare([data['pre'], data['pre_flush']], data['post']),
        'headline_lua': compare([data['pre_lua']], data['post_lua']),
        'scriptfix3_native': compare([data['scriptfix3']], data['post']),
        'scriptfix3_lua': compare([data['scriptfix3_lua']], data['post_lua']),
    }
    assert len(groups['headline_native']) == 244
    assert all(r['delta'] <= 0 for r in groups['headline_native']
               if r['command'] in ('GET', 'SET', 'INCR', 'READLOCAL-GET'))
    for label in ('scriptfix3_native', 'scriptfix3_lua'):
        assert len(groups[label]) == 96
        assert all(r['delta'] <= 0 for r in groups[label]
                   if r['command'].startswith(('EVAL-', 'EVALSHA-')))
    result = dict(
        scope='Serverless production command activation and completion. Native namespace instructions; '
              'Lua companion includes executable VM instructions. Fixture, shared-library bodies, '
              'network, io_uring syscalls and idle scheduler work are outside this census. '
              'No rates, cycles/op or IPC were measured.',
        attribution='Every nonzero delta is decomposed exactly into executed-function instruction counts. '
                    'Function movement/inlining can move instructions between bodies without changing totals. '
                    'See the linked-body inventory for source/lane versus compiler changes.',
        inputs={name: dict(path=path, sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),
                           server_sha256=data[name]['server_sha256']) for name, path in files.items()},
        historical_script_reference='Wave11 retained scriptfix3 receipts and production bindings; '
                                    'same tracer source, warm script activation and GC fixture semantics. '
                                    'These reference counts were not rerun in wave12.',
        comparisons=groups)
    (DOC/'instruction-comparison.json').write_text(json.dumps(result, indent=2)+'\n')
    lines = ['# Command-scope instruction census', '', result['scope'], '',
             'Counts are instructions per complete activation (batch columns are totals).', '',
             '| Namespace | Command | Mode | Batch/children | Atomic | PRE | POST | Delta |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    for row in groups['headline_native']:
        lines.append('| ' + ' | '.join(str(row[k]) for k in
            ('namespace','command','mode','batch','atomic','pre','post','delta')) + ' |')
    lines += ['', '## Scriptfix3 reference', '', result['historical_script_reference'], '',
              '| Domain | Namespace | Command | Delta min | Delta max |', '|---|---|---|---:|---:|']
    for label in ('scriptfix3_native', 'scriptfix3_lua'):
        families = collections.defaultdict(list)
        for row in groups[label]:
            families[row['namespace'],row['command']].append(row['delta'])
        for (ns, cmd), values in sorted(families.items()):
            lines.append(f'| {label} | {ns} | {cmd} | {min(values)} | {max(values)} |')
    (DOC/'instruction-comparison.md').write_text('\n'.join(lines)+'\n')
    print('244 native cells; 96 Lua cells; no scalar additions; EVAL/EVALSHA <= scriptfix3')


if __name__ == '__main__':
    main()
