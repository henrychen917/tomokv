#!/usr/bin/env python3
"""Serverless falsifiers for the single EXECABORT gate row; launches no server."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ExecabortRow(unittest.TestCase):
    def run_row(self, failure=''):
        source = (ROOT / 'tests/gate.sh').read_text()
        start = source.index('row_begin "EXECABORT releases WATCH reservation"')
        end = source.index("# SURVIVING.md's atomic lane", start)
        script = r'''
CORES=112-119
row_begin(){ :; }
unit_ready(){ [ "$FAILURE" != build ]; }
ok(){ echo ok; }
bad(){ echo FAIL; }
taskset(){
  shift 2
  printf '%s\n' "$*" >> "$TMPDIR/calls"
  if [ "${3:-}" = no-arm ]; then
    [ "$FAILURE" != unarmed-success ] || return 0
    if [ "$FAILURE" = wrong-failure ]; then echo 'unrelated failure'; return 1; fi
    echo 'FAIL execabort-watch: WATCH window never armed'
    return 1
  fi
  [ "$FAILURE" != witness ]
}
''' + source[start:end]
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            result = subprocess.run(['bash'], input=script, text=True, capture_output=True,
                                    env=dict(os.environ, TMPDIR=directory, FAILURE=failure), timeout=5)
            calls = Path(directory, 'calls')
            return result, calls.read_text().splitlines() if calls.exists() else []

    def test_one_row_requires_both_variants_modes_and_controls(self):
        result, calls = self.run_row()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['ok'])
        self.assertEqual(len(calls), 14)
        self.assertEqual(sum(call.endswith('no-arm') for call in calls), 2)

    def test_build_or_witness_failure_is_red(self):
        for failure in ('build', 'witness'):
            with self.subTest(failure=failure):
                result, _ = self.run_row(failure)
                self.assertEqual(result.stdout.splitlines(), ['FAIL'])

    def test_unarmed_success_or_unrelated_failure_cannot_pass(self):
        for failure in ('unarmed-success', 'wrong-failure'):
            with self.subTest(failure=failure):
                result, _ = self.run_row(failure)
                self.assertEqual(result.stdout.splitlines(), ['FAIL'])


if __name__ == '__main__':
    unittest.main()
