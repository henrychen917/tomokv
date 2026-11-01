#!/usr/bin/env python3
"""Audit the retained final correctness receipts; never boot a server."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/blockfix4'
RECEIPTS = DOC / 'gate-receipts'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((DOC / 'binary-manifest.json').read_text())
    for arm in manifest['arms'].values():
        assert sha(ROOT / arm['path']) == arm['sha256']
    post = manifest['arms']['POST']['sha256']
    assert not subprocess.check_output(['git', 'diff', 'd6d435ece', '--', 'src', 'Makefile'], cwd=ROOT)
    records = {p.stem: json.loads(p.read_text()) for p in RECEIPTS.glob('*.json')}
    for record in records.values():
        assert sha(ROOT / record['archive']) == record['archive_sha256']
    required = []
    for name in (DOC / 'required-jobs.txt').read_text().split():
        required.extend({'differ-split': ['differ-split-0', 'differ-split-1', 'differ-equivalence'],
                         'differ-armed': ['differ-armed-0', 'differ-armed-1']}.get(name, [name]))
    coverage = {}
    for engine in ('uring', 'epoll'):
        matches = {name: [] for name in required}
        for tag, record in records.items():
            if record.get('binary_sha256') != post or record.get('env', {}).get('GATE_NET_IO') != engine:
                continue
            for job in record['jobs']:
                if (job['job'] in matches and job['done'] and job['done'].split('\t')[0] == '0'
                        and job['failed'] == 0 and job['passed'] > 0):
                    matches[job['job']].append(tag)
        assert len(matches) == 45 and all(matches.values()), matches
        coverage[engine] = matches
        for prefix in ('fused-debug-', 'fused-supplement-'):
            record = records[prefix + engine]
            assert record['exit_code'] == 0 and record['env']['GATE_TXN_FUSED'] == '1'
    sources = {str(p.relative_to(ROOT / 'tests')): sha(p) for p in
               [ROOT / 'tests/blockfix4.py', *sorted((ROOT / 'tests/blockfix4_repro').rglob('*.py'))]}
    matrices = []
    for tag in ('post-extended-uring', 'functional-epoll',
                'normal-namespace-uring', 'normal-namespace-epoll'):
        record = records[tag]
        assert record['exit_code'] == 0 and record['binary_sha256'] == post
        legs = passed = 0
        with tarfile.open(ROOT / record['archive']) as tar:
            for case in ('scripts', 'moves', 'creators', 'removed', 'mpop'):
                base = f'jobs/blockfix4/{case}/'
                witness = json.load(tar.extractfile(base + 'witness.json'))
                assert witness['sources'] == sources and witness['binary_sha256'] == post
                results = json.load(tar.extractfile(base + 'results.json'))
                legs += len(results)
                passed += sum(r['passed'] for r in results)
        assert legs == passed == 116
        matrices.append(dict(receipt=tag, legs=legs, passed=passed))
    negative = {}
    for tag in ('pre-extended', 'pad-a-negative'):
        job = next(j for j in records[tag]['jobs'] if j['job'] == 'blockfix4')
        assert job['passed'] == 0 and job['failed'] == 5
        negative[tag] = 5
    differ = {}
    for engine in ('uring', 'epoll'):
        record = records['functional-' + engine]
        comparisons = repeats = 0
        with tarfile.open(ROOT / record['archive']) as tar:
            for mode in ('split', 'armed'):
                for atomic in (0, 1):
                    body = tar.extractfile(f'jobs/differ-{mode}-{atomic}/output.log').read().decode()
                    lines = body.splitlines()
                    comparisons += sum(s.startswith('  differ ') and ' ok (' in s for s in lines)
                    repeats += sum(' rep ' in s and ' ok (' in s for s in lines)
                    assert 'fail=0 runtime=' in body
        assert comparisons == 938 and repeats == 8
        differ[engine] = dict(comparisons=comparisons, fixed_multi_repetitions=repeats)
    ordinary = json.loads((DOC / 'instructions/comparison.json').read_text())
    scripts = json.loads((DOC / 'instructions/scripts-comparison.json').read_text())
    assert len(ordinary) == 64 and all(r['post'] <= r['pre'] and r['delta'] == r['post'] - r['pre'] for r in ordinary)
    assert len(scripts) == 44
    freshness = json.loads((DOC / 'freshness.json').read_text())
    assert len(freshness['commands']) == 5 and all(c['exit_code'] == 0 for c in freshness['commands'])
    current_gate = (ROOT / 'tests/gate.sh').read_text().splitlines()
    original_gate = subprocess.check_output(['git', 'show', '7d2f8a205:tests/gate.sh'], cwd=ROOT, text=True).splitlines()
    tallies = lambda lines: [s for s in lines if s.startswith(('EXPECT_QUICK=', 'EXPECT_FULL='))]
    assert tallies(current_gate) == tallies(original_gate)
    report = dict(post_sha256=post, archives_verified=len(records), required_job_coverage=coverage,
                  final_witness_matrices=matrices, expected_negative_rows=negative,
                  differential=differ, ordinary_instruction_pairs=64, script_exec_instruction_pairs=44,
                  freshness_commands=5, unchanged_expect=tallies(current_gate), DQ=5, DF=5,
                  retained_nonzero_invocations={tag: r['exit_code'] for tag, r in records.items()
                                                if r.get('exit_code')})
    (DOC / 'final-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Verified: 45 required jobs per engine, 464 witness legs, 64 ordinary cost pairs, and all receipt archives.')


if __name__ == '__main__':
    main()
