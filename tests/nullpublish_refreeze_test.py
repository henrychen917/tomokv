#!/usr/bin/env python3
"""Exercise the real refreeze command and campaign preflight in a disposable repo.

make copies identity strings; these artifacts are never executed. No production
build, server, generator, calibration, or campaign is started by these controls.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPORT = 'MEASURE-REQUEST-nullpublish3.md'


class RefreezeControls(unittest.TestCase):
    def test_refreeze_guards_idempotence_and_stale_manifest_preflight(self):
        with tempfile.TemporaryDirectory(prefix='refreeze-controls-', dir=ROOT / 'build') as tmp:
            root = Path(tmp)

            def run(*args, good=True):
                result = subprocess.run(args, cwd=root, text=True, capture_output=True, timeout=60)
                if good:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout + result.stderr

            def commit(message):
                run('git', 'add', '-A')
                run('git', 'commit', '-qm', message)

            def head():
                return run('git', 'rev-parse', 'HEAD').strip()

            def land():
                run('git', 'update-ref', 'refs/remotes/origin/cpp', 'HEAD')

            def refreeze(*, good=True):
                return run(sys.executable, 'tools/nullpublish_refreeze.py', '--memtier',
                           str(root / 'build/generator'), good=good)

            for directory in ('src', 'tools', 'tests', 'build'):
                (root / directory).mkdir()
            # Real dependency traversal and manifest generation, on copied code.
            from abba_instrument import instrument_fingerprint
            for row in instrument_fingerprint(ROOT)['entries']:
                target = root / row['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / row['path'], target)
            for name in ('tests/headline_cells.txt', 'tests/gate_measurements.json',
                         'tools/nullpublish_refreeze.py', REPORT):
                shutil.copy2(ROOT / name, root / name)
            (root / '.gitignore').write_text('/build/\n__pycache__/\n')
            (root / 'src/identity').write_text('synthetic server one, never executed\n')
            (root / 'build/generator').write_text('synthetic generator identity, never executed\n')
            (root / 'build/generator').chmod(0o755)
            (root / 'Makefile').write_text('build/tomokv build/tailgen:\n\t@mkdir -p build\n'
                                         '\t@cp src/identity $@\n\t@chmod +x $@\n')
            run('git', 'init', '-q')
            run('git', 'config', 'user.name', 'Refreeze controls')
            run('git', 'config', 'user.email', 'fixture@invalid')
            commit('synthetic landed source')
            land()
            first = head()
            run(sys.executable, 'tools/nullpublish_refreeze.py', '--generate-script')
            self.assertFalse((root / 'build/tomokv').exists())
            self.assertFalse((root / 'build/nullpublish-freeze.json').exists())
            generated = (root / 'build/nullpublish-campaign.sh').read_text()
            self.assertIn('--null-holdout 1', generated)
            self.assertIn('|| HOLDOUT_RC=$?', generated)
            self.assertIn('verify-null-holdout', generated)
            self.assertIn('publish-standing-null', generated)
            self.assertNotIn('PYEXPECTED', generated)
            self.assertEqual(head(), first, 'script-only generation must not commit a freeze')
            with self.subTest(guard='untracked dirty tree'):
                (root / 'dirty').write_text('uncommitted')
                self.assertIn('dirty worktree', refreeze(good=False))
                self.assertFalse((root / 'build/tomokv').exists())
                (root / 'dirty').unlink()
            with self.subTest(guard='tracked dirty tree'):
                original = (root / 'src/identity').read_bytes()
                (root / 'src/identity').write_bytes(original + b'changed')
                self.assertIn('dirty worktree', refreeze(good=False))
                (root / 'src/identity').write_bytes(original)
            with self.subTest(guard='HEAD ahead of origin/cpp'):
                (root / 'ahead').write_text('unlanded')
                commit('unlanded fixture')
                self.assertIn('REFREEZE REFUSED', refreeze(good=False))
                self.assertFalse((root / 'build/tomokv').exists())
                run('git', 'reset', '--hard', first)
            refreeze()
            self.assertEqual(run('git', 'log', '-1', '--format=%s').strip(), 'refreeze on ' + first)
            self.assertFalse(run('git', 'status', '--porcelain').strip())
            saved_head = head()
            saved_manifest = (root / 'build/nullpublish-campaign.sha256').read_bytes()
            saved_freeze = (root / 'build/nullpublish-freeze.json').read_bytes()
            saved_report = (root / REPORT).read_bytes()
            with self.subTest(guard='generated commit is also subject to ancestry'):
                self.assertIn('REFREEZE REFUSED', refreeze(good=False))
                self.assertEqual(head(), saved_head)
            land()
            with self.subTest(guard='idempotent landed rerun'):
                self.assertIn('Already frozen', refreeze())
                self.assertEqual(head(), saved_head)
                self.assertEqual((root / 'build/nullpublish-freeze.json').read_bytes(), saved_freeze)
                self.assertEqual((root / REPORT).read_bytes(), saved_report)

            def preflight(*, good):
                # Exact report prefix; stop BEFORE binary storage, reorder controls,
                # calibration or measurement. There are no workload stubs to fall through.
                text = (root / 'build/nullpublish-campaign.sh').read_text()
                prefix = text[:text.index('# Preflight BEFORE any control')]
                prefix += "printf 'SERVERLESS-PREFLIGHT-COMPLETE\\n'\n"
                result = subprocess.run(['bash'], cwd=root, input=prefix, text=True,
                                        capture_output=True, timeout=60)
                if good:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('SERVERLESS-PREFLIGHT-COMPLETE', result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn('SERVERLESS-PREFLIGHT-COMPLETE', result.stdout)
                return result.stdout + result.stderr

            preflight(good=True)
            (root / 'src/identity').write_text('synthetic server two, never executed\n')
            commit('changed server landed')
            land()
            second = head()
            with self.subTest(guard='old freeze rejects changed source'):
                preflight(good=False)
            refreeze()
            self.assertEqual(run('git', 'log', '-1', '--format=%s').strip(), 'refreeze on ' + second)
            self.assertNotEqual((root / 'build/nullpublish-freeze.json').read_bytes(), saved_freeze)
            preflight(good=True)
            manifest = root / 'build/nullpublish-campaign.sha256'
            current_manifest = manifest.read_bytes()
            with self.subTest(guard='stale manifest after changed-server refreeze'):
                manifest.write_bytes(saved_manifest)
                refused = preflight(good=False)
                self.assertIn('stale artifact manifest', refused)
                self.assertIn('build/tomokv-nullpublish-POST: FAILED', refused)
                manifest.write_bytes(current_manifest)
            with self.subTest(guard='fence byte equality'):
                script = root / 'build/nullpublish-campaign.sh'
                current_script = script.read_bytes()
                script.write_bytes(current_script + b'\n# stale script\n')
                self.assertIn('script differs from report', preflight(good=False))
                script.write_bytes(current_script)
                fence = re.findall(r'```bash\n(.*?)```', (root / REPORT).read_text(), re.S)
                self.assertEqual(fence, [script.read_text()])
            preflight(good=True)
            print('REFREEZE: dirty/unlanded refusal; landed rerun unchanged; changed server rebuilt; '
                  'stale manifest rejected by exact campaign preflight; fence bytes match')


if __name__ == '__main__':
    os.sched_setaffinity(0, set(range(112, 128)))
    unittest.main(verbosity=2)
