#!/usr/bin/env python3
"""Exercise the real subset planner/collector without building or booting anything."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

import gate_receipt

ROOT = Path(__file__).resolve().parents[1]
GATE = (ROOT / 'tests/gate.sh').read_text()
PLAN = GATE[GATE.index('plan_jobs(){'):GATE.index('\nstart_workers(){')]
DEPS = GATE[GATE.index('job_dependencies(){'):GATE.index('\njob_ready(){')]


def select(spec='', partial=True, tier='full', mutation=''):
    script = ('set -eu\nsource tests/gate_subset.sh\n' + PLAN + '\n' + DEPS + mutation +
              '\nplan_jobs\nselect_jobs >&2\nprintf "%s\\n" "${JOB_NAMES[@]}"\n')
    return subprocess.run(['bash', '-c', script], cwd=ROOT, text=True, capture_output=True,
                          env=dict(os.environ, GATE_PARTIAL=str(int(partial)),
                                   GATE_ONLY_JOBS=spec, TIER=tier))


class Subset(unittest.TestCase):
    def test_only_requested_jobs_and_transitive_builds(self):
        result = select('debug-0,debug-1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ['release', 'production_units', 'debug-0', 'debug-1'])
        result = select('core_units')
        self.assertEqual(set(result.stdout.splitlines()),
                         {'release', 'core_tsan_build', 'production_units', 'core_units'})

    def test_unknown_empty_and_wrong_tier_fail_before_workers(self):
        for spec, tier in [('debug-2', 'full'), ('   ', 'full'), ('*', 'full'),
                           ('differ-split', 'quick'), ('asan_batteries', 'quick'),
                           ('production_units', 'full')]:
            result = select(spec, tier=tier)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(result.stdout, '')

    def test_atomic_barrier_does_not_pull_in_unrequested_work(self):
        result = select('atomic_batteries')
        self.assertEqual(result.stdout.splitlines(), ['release', 'atomic_batteries'])

    def test_differ_alias_keeps_all_fold_children(self):
        result = select('differ-split')
        self.assertEqual(set(result.stdout.splitlines()),
                         {'release', 'differ-split-0', 'differ-split-1', 'differ-equivalence'})

    def test_disabled_selector_is_byte_identical(self):
        baseline = select(partial=False, mutation='\nselect_jobs(){ :; }\n')
        complete = select('debug-0', partial=False)
        self.assertEqual(complete.returncode, 0, complete.stderr)
        self.assertEqual(complete.stdout, baseline.stdout)

    def test_unset_selector_defaults_to_complete_under_nounset(self):
        baseline = select(partial=False)
        complete = select(mutation='\nunset GATE_PARTIAL\n')
        self.assertEqual(complete.returncode, 0, complete.stderr)
        self.assertEqual(complete.stdout, baseline.stdout)

    def test_partial_ledger_cannot_be_a_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger'
            path.write_text('PARTIAL\t0\tNOT A RECEIPT\nok\t1.0\tdebug fixture\n')
            with self.assertRaisesRegex(ValueError, 'invalid ledger row'):
                gate_receipt.ledger_rows(path, passing=True)

    def test_finalizer_failure_is_not_hidden_by_partial_collection(self):
        with tempfile.TemporaryDirectory() as temp:
            script = r'''set -eu
source tests/gate_subset.sh
JOB_NAMES=(production_units); PASS=0; FAIL=0; LEDGER="$RUN_DIR/ledger"
mkdir -p "$RUN_DIR/jobs/production_units"
printf '17 0 0\n' > "$RUN_DIR/jobs/production_units/done"
join_workers(){ :; }; phase(){ :; }; cleanup(){ :; }
job_label(){ echo "$1"; }
bad(){ FAIL=$((FAIL+1)); echo "FAIL $1: $2"; }
collect_job(){ echo 'unexpected row collection'; exit 99; }
partial_gate
'''
            result = subprocess.run(['bash', '-c', script], cwd=ROOT, text=True,
                                    capture_output=True, env=dict(os.environ, RUN_DIR=temp))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('prerequisite did not complete', result.stdout)


if __name__ == '__main__':
    unittest.main()
