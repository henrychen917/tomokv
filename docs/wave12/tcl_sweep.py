#!/usr/bin/env python3
"""Every named skip, three fresh attempts per mode; no pass on a missing test."""
import argparse
import concurrent.futures
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave12/tcl-skips'
BUILD = ROOT / 'build/wave12/tcl-skips'
sys.path.insert(0, str(ROOT / 'tests'))
import redis_tcl as suite


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2) + '\n').encode()
    if path.parent.name.isdigit() or path.name == 'summary.json':
        with gzip.GzipFile(filename=str(path)+'.gz', mode='wb', mtime=0) as stream:
            stream.write(data)
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(data)


def read(path):
    if path.exists():
        return json.loads(path.read_text())
    with gzip.open(str(path)+'.gz', 'rt') as stream:
        return json.load(stream)


def worker(slot, cases, binary):
    # Each worker owns eight CPUs and three ports. The upstream controller is
    # explicitly pinned to its slot; its default 32-port discovery is disabled.
    cpus = set(range(64 + 8 * slot, 72 + 8 * slot))
    os.sched_setaffinity(0, cpus)
    cores = f'{min(cpus)}-{max(cpus)}'
    port = 20060 + 4 * slot
    tree = BUILD / f'checkout-{slot}'
    suite.prepare(Path('/home/user/Projects/redis'), tree, controller_port=port + 1)
    digest = suite.sha(binary)
    results = []
    for index, unit, name, spec in cases:
        for mode in ('1s', '2s'):
            for attempt in range(1, 4):
                target = DOC / f'{index:03d}' / f'{mode}-{attempt}.json'
                if target.exists() or Path(str(target)+'.gz').exists():
                    row = read(target)
                    assert row['binary_sha256'] == digest
                else:
                    output = BUILD / f'{index:03d}' / f'{mode}-{attempt}'
                    args = argparse.Namespace(output=output, binary=binary, mode=mode,
                        cores=cores, port=port, baseport=port + 2, ratio='6:2',
                        idle_timeout=20, file_timeout=75)
                    observed = suite.run_file(args, tree, unit, only=[name],
                        extra=spec.get('extra_args', ()), server_args=spec.get('server_args', ()))
                    expected = name + ' in tests/' + unit + '.tcl'
                    selected = [e for e in observed['events']
                                if e['test'] == expected and e['status'] in ('ok', 'err', 'exception')]
                    failures = [e for e in observed['events'] if e['status'] in ('err', 'exception')]
                    # A test may occur twice (EVAL and FUNCTION). Every observed
                    # occurrence must pass and the full file must finish.
                    validation_error = None
                    try:
                        suite.validate_passing(observed, [expected] * len(selected),
                                               spec.get('known_setup_errors', ()))
                        passed = bool(selected) and all(e['status'] == 'ok' for e in selected)
                    except ValueError as exc:
                        validation_error = str(exc)
                        passed = False
                    first = next((e['data'] for e in selected if e['status'] != 'ok'), None)
                    if not first:
                        first = observed['error'] or next((e['data'] for e in failures), None)
                    if not selected:
                        first = 'Selected assertion did not run. ' + (first or '')
                    if passed:
                        first = None
                    elif not first:
                        first = validation_error or 'Selected assertion occurrence count changed.'
                    row = dict(index=index, file=unit, test=name, mode=mode, attempt=attempt,
                        binary_sha256=digest, passed=passed, occurrences=len(selected),
                        selected=selected, first_failure=first, complete=observed['complete'],
                        exit_code=observed['exit_code'], error=observed['error'],
                        validation_error=validation_error,
                        raw_result=str(output / unit / 'result.json'),
                        raw_sha256=suite.sha(output / unit / 'result.json'))
                    data = output / unit / 'data'
                    row['pruned_data'] = [dict(path=str(p.relative_to(data)), bytes=p.stat().st_size,
                                               sha256=suite.sha(p))
                                          for p in data.rglob('*') if p.is_file()]
                    shutil.rmtree(data)
                    save(target, row)
                results.append(row)
                print(index, mode, attempt, 'PASS' if row['passed'] else 'SKIP', name, flush=True)
    assert suite.sha(binary) == digest
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', type=Path, default=ROOT / 'build/wave12/tomokv-POST')
    p.add_argument('--promote', action='store_true')
    args = p.parse_args()
    manifest_path = ROOT / 'tests/redis_tcl_passing.json'
    frozen = DOC / 'manifest-before.json'
    if not frozen.exists():
        save(frozen, json.loads(manifest_path.read_text()))
    manifest = json.loads(frozen.read_text())
    cases = []
    for unit, spec in manifest['files'].items():
        for name in spec.get('skip_tests', {}):
            cases.append((len(cases), unit, name, spec))
    if not args.promote:
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker, slot, cases[slot::4], args.binary.resolve()) for slot in range(4)]
            for f in futures:
                f.result()
    historical = json.load(gzip.open(ROOT / 'docs/harness5/redis-tcl-failures.json.gz', 'rt'))
    roots = {}
    for row in historical:
        roots.setdefault((row['file'], row['test']), set()).add(row['root'])
    summary = []
    for index, unit, name, spec in cases:
        rows = [read(DOC / f'{index:03d}' / f'{mode}-{attempt}.json')
                for mode in ('1s', '2s') for attempt in range(1, 4)]
        passed = all(r['passed'] for r in rows) and len({r['occurrences'] for r in rows}) == 1
        summary.append(dict(index=index, file=unit, test=name, roots=sorted(roots.get((unit, name), {'UNCLASSIFIED'})),
            promote=passed, occurrences=rows[0]['occurrences'],
            first_failure=next((r['first_failure'] for r in rows if not r['passed']), None),
            attempts=[dict(mode=r['mode'], attempt=r['attempt'], passed=r['passed']) for r in rows]))
        if args.promote and passed:
            del spec['skip_tests'][name]
            full = name + ' in tests/' + unit + '.tcl'
            assert full not in spec['passed_tests']
            spec['passed_tests'].extend([full] * rows[0]['occurrences'])
            spec['passed_tests'].sort()
    save(DOC / 'summary.json', summary)
    if args.promote:
        manifest['wave12_promotions'] = [dict(file=r['file'], test=r['test'], occurrences=r['occurrences'])
                                         for r in summary if r['promote']]
        save(manifest_path, manifest)
    print('cases', len(summary), 'promotable', sum(r['promote'] for r in summary), flush=True)


if __name__ == '__main__':
    main()
