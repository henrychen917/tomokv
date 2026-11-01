#!/usr/bin/env python3
"""Build and check the exact production-unit targets declared by gate.sh."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave13'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    assert os.sched_getaffinity(0) <= set(range(16))
    os.environ['LC_ALL'] = 'C'
    gate = (ROOT / 'tests/gate.sh').read_text()
    body = gate.split('job_production_units(){', 1)[1].split('\njob_multidb(){', 1)[0]
    first = body.split('>"$TMPDIR/build.log"', 1)[0]
    targets = list(dict.fromkeys(re.findall(r'build/[\w-]+', first)))
    assert len(targets) == 51, targets
    groups = [(['make'], ['all', *targets, 'build/benchtxn']),
              (['make', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk'],
               ['build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256']),
              (['make', '-f', 'Makefile', '-f', 'tools/blockfix2.mk'],
               ['build/blockfix2-unit', 'build/blockfix2-db0-unit']),
              (['make', 'BUILD_ROOT=build/mdbqsbr2-park'], ['all']),
              (['make', 'BUILD_ROOT=build/mdbqsbr2-no-wake'], ['all'])]
    results = []
    log = ROOT / 'build/wave13/logs/final-freshness-build.log'
    with log.open('w') as stream:
        for base, outputs in groups:
            argv = [*base, '-j16', *outputs]
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            results.append(dict(argv=argv, exit=result.returncode))
            assert result.returncode == 0, argv
    checks = []
    for base, outputs in groups:
        for target in outputs:
            argv = [*base, '-q', target]
            result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
            checks.append(dict(argv=argv, exit=result.returncode, output=result.stdout+result.stderr))
    production_diff = subprocess.check_output(['git', 'diff', '68f85e5d5', '--', 'src', 'third_party', 'Makefile'], cwd=ROOT)
    assert not production_diff, 'production changed after the frozen POST build'
    arms = {arm: dict(path='build/wave13/tomokv-' + arm,
                      sha256=sha(ROOT / ('build/wave13/tomokv-' + arm)),
                      asserts_sha256=sha(ROOT / ('build/wave13/tomokv-' + arm + '.asserts.tsv')))
            for arm in ('PRE', 'POST', 'PAD-A')}
    assert sha(ROOT / 'build/tomokv') == arms['POST']['sha256']
    result = dict(checked_at=time.time(), cpus='0-15', jobs=16,
                  source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  production_commit='68f85e5d52d6889e4669c31eb00b2268c9341f48', production_unchanged=True,
                  target_count=len(targets), targets=targets, builds=results, freshness=checks,
                  measurement_client=dict(path='build/benchtxn', sha256=sha(ROOT / 'build/benchtxn'),
                                          source_sha256=sha(ROOT / 'tools/benchtxn.cc'), executed=False),
                  fresh_targets=sum(r['exit'] == 0 for r in checks), arms=arms,
                  gate_expect_constants=re.findall(r'^EXPECT_(?:QUICK|FULL)=\d+', gate, re.M),
                  build_log_sha256=sha(log),
                  note='The mdbqsbr aggregate is phony; both actual BUILD_ROOT=... all targets are checked separately.')
    (DOC / 'delivery-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    assert all(r['exit'] == 0 for r in checks), checks
    assert result['gate_expect_constants'] == ['EXPECT_QUICK=999', 'EXPECT_FULL=1016']
    print(len(checks), 'fresh build targets; all three arms bound; EXPECT unchanged')


if __name__ == '__main__':
    main()
