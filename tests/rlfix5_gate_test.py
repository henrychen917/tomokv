#!/usr/bin/env python3
"""Exercise the real RL5 gate's fixture selection without starting any server."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FixtureSelection(unittest.TestCase):
    def selection(self, *, release=0, build=0, fresh=0, external=''):
        source = (ROOT / 'tests/gate.sh').read_text()
        body = source[source.index('job_rlfix5(){'):source.index('\njob_rlfix3_info(){')]
        # Stop at the first row, before the oracle or any listener is started.
        mocks = r'''
py(){ return 0; }
cmp(){ return 0; }
make(){
  if [ "$*" = '-q all' ]; then return "$RELEASE_RC"; fi
  return "$FRESH_RC"
}
pausable(){ return "$BUILD_RC"; }
row_begin(){ printf '%s\n' "$unit_root"; exit 0; }
'''
        with tempfile.TemporaryDirectory(prefix='rlfix5-gate-') as directory:
            env = dict(os.environ, TMPDIR=directory, PORT='21500',
                       RELEASE_RC=str(release), BUILD_RC=str(build), FRESH_RC=str(fresh),
                       GATE_RLFIX5_UNITS=external, LC_ALL='C')
            result = subprocess.run(['bash', '-c', mocks + body + '\njob_rlfix5 monotonic'],
                                    cwd=ROOT, env=env, text=True, capture_output=True, check=True)
            selected = result.stdout.strip()
            return selected, directory + '/missing'

    def test_current_fixture(self):
        self.assertEqual(self.selection()[0], str(ROOT / 'build/rlfix5/counts/scopes/post'))

    def test_failed_build_rejects_old_fixture(self):
        actual, missing = self.selection(build=1)
        self.assertEqual(actual, missing)

    def test_stale_fixture_rejected(self):
        actual, missing = self.selection(fresh=1)
        self.assertEqual(actual, missing)

    def test_stale_release_rejected(self):
        actual, missing = self.selection(release=1)
        self.assertEqual(actual, missing)

    def test_explicit_pre_fixture(self):
        self.assertEqual(self.selection(external='/explicit/pre')[0], '/explicit/pre')


if __name__ == '__main__':
    unittest.main()
