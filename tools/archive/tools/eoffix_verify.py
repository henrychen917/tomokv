#!/usr/bin/env python3
"""Require the complete final proof inventory; an interrupted run is not a pass."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from eoffix_source_sync import runtime_identity

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/eoffix'


def read(name):
    return json.loads((DOC / name).read_text())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    arms = {row['arm']: row for row in read('arms-final.json')}
    expected = ['complete-eof-aof', 'complete-layout', 'complete-pad']
    expected += [f'complete-tcl-{engine}-{index}' for engine in ('epoll', 'uring')
                 for index in range(1, 4)]
    expected += [f'complete-differ-{engine}' for engine in ('epoll', 'uring')]
    expected += ['complete-internal']
    expected += ['complete-source-sync']
    expected += ['complete-complete-supplement']
    expected += [f'complete-live-{engine}' for engine in ('epoll', 'uring')]
    expected += [f'complete-mode-{engine}-{mode}' for engine in ('epoll', 'uring')
                 for mode in ('0', '1')]
    expected += [f'txn-complete-{engine}-{index:02d}' for engine in ('epoll', 'uring')
                 for index in range(1, 51)]
    rows, errors, tcl, differential = [], [], [], []
    for tag in expected:
        if not (DOC / (tag + '.json')).exists():
            errors.append(tag + ': NOT RUN or incomplete')
            continue
        record = read(tag + '.json')
        arm = {'complete-layout': 'POST-layout', 'complete-pad': 'PAD-A'}.get(tag, 'POST')
        lines = [line for ledger in record.get('ledgers', {}).values() for line in ledger.splitlines()]
        failures = [line for line in lines if line.startswith('FAIL\t')]
        resolved = []
        valid = record['native_sha256'] == arms[arm]['sha256']
        valid &= record['env']['LC_ALL'] == 'C'
        valid &= record['env']['GATE_PROOF_NO_RATES'] == '1'
        command = record['command']
        valid &= command[command.index('--server-cores') + 1] == '0-7'
        valid &= command[command.index('--load-cores') + 1] == '0-7'
        valid &= command[command.index('--ports') + 1] == '21900-21902'
        if tag == 'complete-pad':
            valid &= record['exit_code'] == 1 and len(failures) == 2
            valid &= all('epoll directed correctness' in line for line in failures)
            for mode in ('1s', '2s'):
                folder = Path(record['directory']) / ('jobs/netio-' + mode)
                uring = (folder / 'uring.log').read_text()
                epoll = (folder / 'epoll.log').read_text()
                valid &= 'netio(uring): 101 checks, 0 failures' in uring
                valid &= 'netio(epoll): 101 checks, 1 FAILURES' in epoll
                valid &= epoll.count('  FAIL F5 closed blocking pipeline retired its exact client:') == 1
        elif tag == 'complete-internal' and failures:
            # Preserve the original red receipt. This one source-only failure
            # is resolved only by the separately required, unchanged gate jobs.
            valid &= record['exit_code'] == 1
            label = 'writeback policy clauses witnesses + negative controls'
            source_failures = [line for line in failures if line.split('\t')[-1] == label]
            log = (Path(record['directory']) / 'jobs/wbland_units/wbland-clauses.log').read_text()
            sync = read('source-sync-identity.json')
            source_resolved = (len(source_failures) == 1 and 'ValueError: stale R7 envelope:' in log and
                               log.count('PASS clauses ') == 50 and sync['equivalent'] and
                               len(sync['added_comments']) == 2 and
                               read('complete-source-sync.json')['exit_code'] == 0)
            if source_resolved:
                resolved.append(dict(label=label, followup='complete-source-sync'))
            valid &= source_resolved and len(failures) == len(source_failures)
        else:
            valid &= record['exit_code'] == 0 and not failures
        if not valid:
            unresolved = [line.split('\t')[-1] for line in failures
                          if line.split('\t')[-1] not in {item['label'] for item in resolved}]
            errors.append(tag + ': failed verdict, geometry or arm identity' +
                          ('; unresolved rows: ' + ', '.join(unresolved) if unresolved else ''))
        rows.append(dict(tag=tag, arm=arm, exit_code=record['exit_code'],
                         passed_rows=sum(line.startswith('ok\t') for line in lines),
                         failures=failures, jobs=record['jobs'],
                         resolved_failures=resolved))
        if tag.startswith('complete-differ-'):
            parts = ('differ-split-0', 'differ-split-1', 'differ-armed-0',
                     'differ-armed-1', 'differ-equivalence')
            fixed = {int(line.split('#')[0]) for line in
                     (ROOT / 'tests/differ_seeds.txt').read_text().splitlines() if line.split('#')[0].strip()}
            for part in parts:
                path = Path(record['directory']) / 'jobs' / part / 'output.log'
                text = path.read_text()
                found = re.search(r'DIFFER matrix: .* seeds=\{([^}]*)\}', text)
                seeds = [int(seed) for seed in found[1].split()] if found else []
                if not fixed <= set(seeds) or len(seeds) <= len(fixed):
                    errors.append(tag + ': standard seed inventory missing from ' + part)
                differential.append(dict(tag=tag, part=part, seeds=seeds))
            if any(record['env'].get(key) for key in
                   ('GATE_DIFFER_PROOF_SUITES', 'GATE_DIFFER_PROOF_SEEDS', 'GATE_DIFFER_DRIVER')):
                errors.append(tag + ': focused differential override was enabled')
        if tag.startswith('complete-tcl-'):
            summaries = list((Path(record['directory']) / 'jobs/redis_tcl').glob('*/summary.json'))
            if len(summaries) != 2:
                errors.append(tag + ': missing Tcl mode summary')
            for path in summaries:
                result = json.loads(path.read_text())
                failed = [row['file'] for row in result['rows'] if row['error'] or not row['complete'] or
                          any(event['status'] == 'err' and event['test'] for event in row['events'])]
                if len(result['rows']) != 39 or failed:
                    errors.append(tag + ': incomplete or failing Tcl manifest in ' + result['mode'])
                tcl.append(dict(tag=tag, mode=result['mode'], files=len(result['rows']), failures=failed))
    for arm, row in arms.items():
        if digest(ROOT / row['path']) != row['sha256']:
            errors.append(arm + ': arm digest changed')
    sync = read('source-sync-identity.json')
    rebuilt = runtime_identity(ROOT / arms['POST']['path'], ROOT / 'build/tomokv')
    if (not sync['equivalent'] or rebuilt['before_sha256'] != sync['before_sha256'] or
            rebuilt['after_sha256'] != sync['after_sha256'] or
            rebuilt['allocated_sections'] != sync['allocated_sections'] or
            rebuilt['load_segments'] != sync['load_segments'] or
            len(sync['negative_controls']) != 3 or
            not all(row['rejected'] for row in sync['negative_controls'])):
        errors.append('fresh production runtime differs from frozen POST')
    identity = read('source-files-final.json')
    for row in identity['production_files']:
        if digest(ROOT / row['path']) != row['sha256']:
            errors.append('source changed: ' + row['path'])
    for row in read('complete-build.json'):
        if row['exit_code']:
            errors.append('required build failed: ' + str(row['command']))
    for row in read('comment-sync-build.json'):
        if row['exit_code']:
            errors.append('comment synchronization build failed: ' + str(row['command']))
    for index in range(len(read('build-freshness-final.json')['commands'])):
        if read(f'freshness-release-{index}-driver.json')['exit_code']:
            errors.append('freshness failed: ' + str(index))
    if read('gates-test-release-complete-driver.json')['exit_code']:
        errors.append('gates_test failed')
    counts = read('instruction-comparison-final.json')
    if len(counts['rows']) != 144 or counts['command_parser_nonzero'] or counts['receive_deltas'] != [2]:
        errors.append('instruction census changed')
    binding = read('scope-binding-post-complete.json')
    if sum(row['matched'] for row in binding) != 283 or any(row['matched'] != row['entered_groups'] for row in binding):
        errors.append('instruction bodies are not fully bound')
    loops = read('validation-summary.json')['transaction_loops']
    loop_rows = []
    for engine in ('epoll', 'uring'):
        selected = [row for row in loops if row['tag'].startswith('txn-complete-' + engine + '-')]
        bad = [row['tag'] for row in selected if row['exit_code'] or not row['aof_pass'] or
               not row['exact_reload'] or row['shutdown_failed'] or row['build_done'].split('\t')[0] != '0']
        if len(selected) != 50 or bad:
            errors.append(engine + ': incomplete or failing transaction repetitions')
        loop_rows.append(dict(engine=engine, complete=len(selected), failures=bad))
    base = subprocess.check_output(['git', 'show', 'ea48a6b27:tests/gate.sh'], cwd=ROOT, text=True)
    current = (ROOT / 'tests/gate.sh').read_text()
    for name in ('EXPECT_QUICK', 'EXPECT_FULL'):
        pattern = rf'^{name}=\d+'
        if re.findall(pattern, base, re.M) != re.findall(pattern, current, re.M):
            errors.append(name + ' was changed')
    pre_loops = []
    for engine in ('epoll', 'uring'):
        selected = [row for row in loops if row['arm'] == 'PRE' and row['engine'] == engine and
                    row['build_done'].split('\t')[0] == '0']
        pre_loops.append(dict(engine=engine, complete=len(selected),
                              whole_jobs_passed=sum(row['exit_code'] == 0 for row in selected),
                              aof_reload_passed=sum(row['aof_pass'] and row['exact_reload'] for row in selected),
                              shutdown_timeouts=sum(row['shutdown_failed'] for row in selected)))
    output = dict(expected_gate_invocations=len(expected), completed=len(rows), jobs=rows,
                  tcl=tcl, differential=differential, transaction_loops=loop_rows, errors=errors,
                  pre_transaction_loops=pre_loops,
                  fifo_attribution=dict(pre=read('fifo-complete-pre.json'), post=read('fifo-complete-post.json'),
                                        pre_overlap=read('fifo-pre-commit-overlap.json'),
                                        post_overlap=read('fifo-post-commit-overlap.json'),
                                        verdict='The FIFO timing failure remains a failed POST row; PRE attribution does not waive it.'),
                  performance='NOT RUN: owner-owned measurements and full iteration')
    (DOC / 'proof-complete.json').write_text(json.dumps(output, indent=2) + '\n')
    print('gate invocations', len(rows), '/', len(expected), 'Tcl legs', len(tcl), 'errors', len(errors))
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()
