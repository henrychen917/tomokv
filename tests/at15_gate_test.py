"""One AT15 gate row; exercise its actual shell verdict with serverless command stubs."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class At15Gate(unittest.TestCase):
    def run_row(self, failed):
        source = (ROOT / 'tests/gate.sh').read_text()
        start = source.index('row_begin "MULTI admin command replies"')
        end = source.index('# EXPECT_*', start)
        row = source[start:end]
        with tempfile.TemporaryDirectory() as directory:
            script = '''CORES=112-127
TMPDIR=%s
row_begin(){ :; }
unit_ready(){ [ "%s" != build ]; }
taskset(){ [ "%s" != witness ]; }
ok(){ echo PASS; }
bad(){ echo FAIL; }
''' % (directory, failed, failed)
            result = subprocess.run(['bash', '-c', script + row], check=True,
                                    text=True, stdout=subprocess.PIPE)
        return result.stdout.strip()

    def test_success(self):
        self.assertEqual(self.run_row(''), 'PASS')

    def test_build_failure(self):
        self.assertEqual(self.run_row('build'), 'FAIL')

    def test_witness_failure(self):
        self.assertEqual(self.run_row('witness'), 'FAIL')

    def test_collection_and_build(self):
        source = (ROOT / 'tests/gate.sh').read_text()
        self.assertEqual(source.count('row_begin "MULTI admin command replies"'), 1)
        for variant in ('at15-unit', 'at15-db0-unit'):
            self.assertIn('build/' + variant, source)
            self.assertIn('build/' + variant + ':', (ROOT / 'Makefile').read_text())
        self.assertLess(source.index('collect_job storage_units'), source.index('if [ "$TIER" = quick ]'))


if __name__ == '__main__':
    unittest.main()
