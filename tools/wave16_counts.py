#!/usr/bin/env python3
"""wave16: command-scope instruction census of the merged tree against the 8be4f68323 receipts.

No server, load, timing or rates. The same fixtures, tracer and accounting the three lanes used:
  ordinary / atomfix6 / parser  tools/parkwake_counts.py (tests/blockfix4_scope.cc 'lua',
                                tests/txnorder_command_scope.cc with atomfix6's range rule,
                                tests/wave14_parser_scope.cc 'lua', see FIXTURES below);
  wave11                        tools/iowake_counts.py (tests/wave11_scope.cc 'complete').
GET/SET/INCR/MGET/MSET x 1s/2s x batch 1/32 x atomic 0/1 x normal/db0 (80 rows per kind); the
parser kind is PARSE-GET/SET/INCR x 1s (read-local 0/1) / 2s x batch 1/32 at atomic 1 (36 rows).
The PRE side is not re-traced: it is the committed 8be4f68323 receipt of the lane that owns the
fixture (docs/parkwake/counts/pre-<kind>/counts.json, docs/iowake/counts/PRE/results.json).
`compare` requires EVERY row identical, total and per function, atomic-1 MSET included.

  taskset -c 0-31,64-111 python3 tools/wave16_counts.py run --kind ordinary
  taskset -c 0-31,64-111 python3 tools/wave16_counts.py compare --kind ordinary
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import parkwake_counts as lane  # noqa: E402  (binds wave13_counts as lane.census)
import wave11_counts as wave11  # noqa: E402

census = lane.census
census.BUILD = ROOT / 'build/wave16/counts'
census.DOC = ROOT / 'build/wave16/counts-doc'   # raw per-case traces stay out of git
wave11.BUILD = census.BUILD / 'wave11'
wave11.DOC = census.DOC
SUMMARY = ROOT / 'docs/wave16/counts'            # committed: counts.json + comparison per kind
lane.ARMS = {'post': ROOT}
# The parser kind uses tests/wave14_parser_scope.cc (topology on CPUs 0-7, driver on 0/8), the
# fixture blockwake ran; parkwake's copy differs only in declaring CPUs 48-55 for its own CPU range.
# CPU ids are placement metadata: blockwake's and parkwake's PRE parser receipts for 8be4f68323
# are identical in all 36 rows, totals and per-function counts.
lane.FIXTURES['parser'] = ('tests/wave14_parser_scope.cc', 'lua')
KINDS = tuple(lane.FIXTURES) + ('wave11',)
PRE_RECEIPT = {kind: ROOT / f'docs/parkwake/counts/pre-{kind}/counts.json' for kind in lane.FIXTURES}
PRE_RECEIPT['wave11'] = ROOT / 'docs/iowake/counts/PRE/results.json'


def rows_of(path):
    data = json.loads(path.read_text())
    return data['rows'] if isinstance(data, dict) else data


def key(row):
    return (row['namespace'], row['command'], row['mode'], row['batch'], row['atomic'], row.get('local', -1))


def run_wave11():
    rows = []
    objects = ROOT / 'build'
    for ns in ('normal', 'db0'):
        binary = wave11.build('post-wave11', ROOT, objects, ns, 'tests/wave11_scope.cc')
        prepared = wave11.prepare(binary, objects, ns, 'complete')
        cases = [(cmd, mode, batch, atomic) for cmd in ('GET', 'SET', 'INCR', 'MGET', 'MSET')
                 for mode in ('1s', '2s') for batch in (1, 32) for atomic in (0, 1)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows += list(pool.map(lambda c: wave11.trace(prepared, 'post-wave11', ns, 'complete', *c), cases))
    wave11.save(census.DOC / 'post-wave11' / 'counts.json',
                dict(server_sha256=census.sha(objects / 'tomokv'), fixture='tests/wave11_scope.cc',
                     domain='complete', rows=rows))


def compare(kind):
    pre = {key(r): r for r in rows_of(PRE_RECEIPT[kind])}
    post = {key(r): r for r in rows_of(census.DOC / f'post-{kind}' / 'counts.json')}
    assert set(pre) == set(post), ('row sets differ', sorted(set(pre) ^ set(post)))
    table = []
    for k in sorted(pre):
        a, b = pre[k], post[k]
        names = sorted(set(a['functions']) | set(b['functions']))
        changed = {f: [a['functions'].get(f, 0), b['functions'].get(f, 0)] for f in names
                   if a['functions'].get(f, 0) != b['functions'].get(f, 0)}
        ns, command, mode, batch, atomic, local = k
        table.append(dict(namespace=ns, command=command, mode=mode, batch=batch, atomic=atomic,
                          local=local, pre=a['total'], post=b['total'], delta=b['total'] - a['total'],
                          identical=not changed and a['total'] == b['total'], changed_functions=changed))
    summary = dict(kind=kind, pre_receipt=str(PRE_RECEIPT[kind].relative_to(ROOT)), rows=len(table),
                   identical=sum(r['identical'] for r in table),
                   violations=[r for r in table if not r['identical']])
    census.save(SUMMARY / f'comparison-{kind}.json', dict(summary=summary, table=table))
    census.save(SUMMARY / f'post-{kind}' / 'counts.json',
                json.loads((census.DOC / f'post-{kind}' / 'counts.json').read_text()))
    print(json.dumps(dict(kind=kind, rows=summary['rows'], identical=summary['identical'],
                          violations=len(summary['violations'])), indent=1))
    for r in summary['violations']:
        print('DELTA', r['namespace'], r['command'], r['mode'], 'b', r['batch'], 'a', r['atomic'],
              'l', r['local'], r['pre'], '->', r['post'], r['changed_functions'])
    return not summary['violations']


def main():
    allowed = set(range(0, 112)) if os.getenv('WAVE16_ALL_CPUS') == '1' else set(range(0, 32)) | set(range(64, 112))
    assert os.sched_getaffinity(0) <= allowed, 'wave16 traces on its own CPUs only'
    os.environ['LC_ALL'] = 'C'
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('phase', choices=('run', 'compare'))
    p.add_argument('--kind', choices=KINDS, required=True)
    a = p.parse_args()
    census.BUILD.mkdir(parents=True, exist_ok=True)
    tracer = census.BUILD / 'trace'
    if not tracer.exists():
        temporary = census.BUILD / f'trace-{os.getpid()}'
        subprocess.run(['g++', '-std=c++20', '-O2', '-g', str(ROOT / 'tools/scriptfix3_trace.cc'),
                        '-o', str(temporary)], check=True)
        temporary.replace(tracer)
    if a.phase == 'run':
        if a.kind == 'wave11':
            wave11.BUILD.mkdir(parents=True, exist_ok=True)
            if not (wave11.BUILD / 'trace').exists():
                (wave11.BUILD / 'trace').symlink_to(tracer)
            run_wave11()
        else:
            lane.run('post', a.kind)
    else:
        sys.exit(0 if compare(a.kind) else 1)


if __name__ == '__main__':
    main()
