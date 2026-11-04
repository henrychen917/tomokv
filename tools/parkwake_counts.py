#!/usr/bin/env python3
"""parkwake: finite production instruction scopes, PRE vs POST. No server, load, timing or rates.

Three existing fixtures, each linked against one arm's production objects and single-stepped
between scope_begin/scope_end by tools/scriptfix3_trace.cc (the census in tools/wave13_counts.py):
  ordinary  tests/blockfix4_scope.cc, the 'lua' domain (wave15's ordinary scopes: every executable
            function, outlined STL included, fixture glue and shared libraries excluded);
  atomfix6  tests/txnorder_command_scope.cc with tools/atomfix6_counts.py's range rule;
  parser    tests/wave14_parser_scope.cc, 'lua' domain (wave15's parser scopes: the IO parse and
            dispatch of GET/SET/INCR frames).
Cases: GET/SET/INCR/MGET/MSET x 1s/2s x batch 1/32 x atomic 0/1, both namespaces; the parser kind
runs PARSE-GET/SET/INCR x 1s (read-local 0/1) / 2s x batch 1/32 at atomic 1, as wave15 did.
`compare` writes the PRE/POST table: every atomic-0 row and atomic-1 MGET must be identical,
atomic-1 MSET reports its delta, per function.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import wave13_counts as census  # noqa: E402

census.BUILD = ROOT / 'build/parkwake/counts'
census.DOC = ROOT / 'docs/parkwake/counts'
ARMS = {'pre': ROOT / 'build/parkwake/pre-source', 'post': ROOT}
FIXTURES = {'ordinary': ('tests/blockfix4_scope.cc', 'lua'),
            'atomfix6': ('tests/txnorder_command_scope.cc', 'complete'),
            'parser': ('tests/parkwake_parser_scope.cc', 'lua')}
CASES = list(itertools.product(('GET', 'SET', 'INCR', 'MGET', 'MSET'), ('1s', '2s'), (1, 32), (0, 1)))
PARSER_CASES = [(c, mode, batch, 1, local) for c in ('PARSE-GET', 'PARSE-SET', 'PARSE-INCR')
                for mode in ('1s', '2s') for batch in (1, 32) for local in ((0, 1) if mode == '1s' else (-1,))]


def trace_local(prepared, label, ns, domain, command, mode, batch, atomic, local):
    """census.trace with the fixture's fifth argument (read-local) instead of the fixed -1."""
    import bisect, gzip
    ranges, argv, digest = prepared
    target = census.DOC / label / domain / ('-'.join(map(str, (ns, command, mode, batch, atomic, local))) + '.json')
    run = subprocess.run(argv + [command, mode, str(batch), str(atomic), str(local)], text=True,
                         capture_output=True, timeout=900)
    if run.returncode:
        raise RuntimeError(str(target) + ' ' + run.stderr + run.stdout[-1500:])
    record = json.loads(next(l[6:] for l in run.stdout.splitlines() if l.startswith('TRACE=')))
    starts = [r[0] for r in ranges]; functions = {}
    for pc, n in record['sites'].items():
        at = int(pc, 16); i = bisect.bisect_right(starts, at) - 1
        assert i >= 0 and at < ranges[i][1]
        functions[ranges[i][3]] = functions.get(ranges[i][3], 0) + n
    row = dict(arm=label, namespace=ns, domain=domain, command=command, mode=mode, batch=batch,
               atomic=atomic, local=local, probe_sha256=digest, total=sum(functions.values()),
               functions=functions, clock_calls=record['clock_calls'], excluded_calls=record['excluded_calls'])
    census.save(target, row)
    print(label, domain, ns, command, mode, batch, atomic, local, row['total'], flush=True)
    return row


def run(arm, kind):
    source = ARMS[arm]
    objects = source / 'build'
    fixture, domain = FIXTURES[kind]
    label = f'{arm}-{kind}'
    rows = []
    for ns in ('normal', 'db0'):
        binary = census.build(label, source, objects, ns, fixture)
        prepared = census.prepare(binary, objects, ns, domain)
        if kind == 'atomfix6':
            ranges, argv, digest = prepared
            for row in ranges:  # tools/atomfix6_counts.py: outlined STL in, fixture glue out
                row[4] = not (('CoreConcurrencyTest::' in row[3] and '::poll<' not in row[3]) or
                              row[2] in ('main', '_Z11scope_beginv', '_Z9scope_endv'))
            whole = binary.parent / 'all-executable.ranges'
            whole.write_text(''.join(f'{r[0]:x} {r[1]:x} {int(r[4])}\n' for r in ranges))
            argv[2] = str(whole)
        with ThreadPoolExecutor(max_workers=8) as pool:
            if kind == 'parser':
                rows += list(pool.map(lambda case: trace_local(prepared, label, ns, domain, *case), PARSER_CASES))
            else:
                rows += list(pool.map(lambda case: census.trace(prepared, label, ns, domain, *case), CASES))
    census.save(census.DOC / label / 'counts.json', dict(
        server_sha256=census.sha(objects / 'tomokv'), fixture=fixture, domain=domain, rows=rows))


def compare(kind):
    def load(arm):
        rows = json.loads((census.DOC / f'{arm}-{kind}' / 'counts.json').read_text())['rows']
        return {(r['namespace'], r['command'], r['mode'], r['batch'], r['atomic'], r.get('local', -1)): r
                for r in rows}
    pre, post = load('pre'), load('post')
    table = []
    for key in sorted(pre):
        a, b = pre[key], post[key]
        functions = sorted(set(a['functions']) | set(b['functions']))
        changed = {f: [a['functions'].get(f, 0), b['functions'].get(f, 0)] for f in functions
                   if a['functions'].get(f, 0) != b['functions'].get(f, 0)}
        ns, command, mode, batch, atomic, local = key
        must_match = atomic == 0 or command != 'MSET'
        table.append(dict(namespace=ns, command=command, mode=mode, batch=batch, atomic=atomic, local=local,
                          pre=a['total'], post=b['total'], delta=b['total'] - a['total'],
                          identical=not changed and a['total'] == b['total'],
                          required_identical=must_match, changed_functions=changed))
    bad = [r for r in table if r['required_identical'] and not r['identical']]
    summary = dict(kind=kind, rows=len(table), required=sum(r['required_identical'] for r in table),
                   required_identical=sum(r['required_identical'] and r['identical'] for r in table),
                   violations=bad,
                   atomic1_mset=[{k: r[k] for k in ('namespace', 'mode', 'batch', 'pre', 'post', 'delta',
                                                     'changed_functions')}
                                 for r in table if r['atomic'] == 1 and r['command'] == 'MSET'])
    census.save(census.DOC / f'comparison-{kind}.json', dict(summary=summary, table=table))
    print(json.dumps({k: v for k, v in summary.items() if k != 'atomic1_mset'}, indent=1))
    for r in summary['atomic1_mset']:
        print('atomic-1 MSET', r['namespace'], r['mode'], 'batch', r['batch'], r['pre'], '->', r['post'],
              f"({r['delta']:+d})")
    return not bad


def main():
    # parkwake lane: CPUs 32-63 only.
    assert os.sched_getaffinity(0) <= set(range(32, 64)), 'parkwake traces on CPUs 32-63 only'
    os.environ['LC_ALL'] = 'C'
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('phase', choices=('run', 'compare'))
    p.add_argument('--arm', choices=tuple(ARMS))
    p.add_argument('--kind', choices=tuple(FIXTURES), required=True)
    a = p.parse_args()
    census.BUILD.mkdir(parents=True, exist_ok=True)
    tracer = census.BUILD / 'trace'
    if not tracer.exists():
        temporary = census.BUILD / f'trace-{os.getpid()}'
        subprocess.run(['g++', '-std=c++20', '-O2', '-g', str(ROOT / 'tools/scriptfix3_trace.cc'),
                        '-o', str(temporary)], check=True)
        temporary.replace(tracer)
    if a.phase == 'run':
        run(a.arm, a.kind)
    else:
        sys.exit(0 if compare(a.kind) else 1)


if __name__ == '__main__':
    main()
