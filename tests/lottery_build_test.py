#!/usr/bin/env python3
"""Check all lottery insertion sites and reject a missing or duplicate seam."""
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import lottery_build


def main():
    (ROOT / 'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lottery-source-check-', dir=ROOT / 'build') as directory:
        root = Path(directory)
        for name in ('src', 'third_party'):
            shutil.copytree(ROOT / name, root / name)
        for name in ('Makefile', 'tests/lottery_hooks.h', 'tools/assert_map.py'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        saved = lottery_build.ROOT
        lottery_build.ROOT = root
        try:
            changes, _ = lottery_build.prepare(root / 'build/positive')
            assert len(changes) == 62, 'lottery insertion inventory changed'
            path = root / 'src/cmd/scatter_engine.inc'
            original = path.read_text()
            anchor = '/* TOMO_TOOL_ANCHOR lottery-read-fragment */'
            assert original.count(anchor) == 1
            for replacement in ('/* absent lottery anchor */', anchor + anchor):
                path.write_text(original.replace(anchor, replacement))
                try:
                    lottery_build.prepare(root / 'build/negative')
                except ValueError as error:
                    assert 'anchors' in str(error), error
                else:
                    raise AssertionError('broken lottery source anchor passed')
            print('PASS lottery: 62 insertion sites; missing and duplicate seam rejected')
        finally:
            lottery_build.ROOT = saved


if __name__ == '__main__':
    main()
