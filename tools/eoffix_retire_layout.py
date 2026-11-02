#!/usr/bin/env python3
"""Retain the verified layout twins and retire their reproducible link objects."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/eoffix'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    arms = {row['arm']: row for row in json.loads((DOC / 'arms-final.json').read_text())}
    for name in ('POST-layout', 'PAD-A'):
        assert digest(ROOT / arms[name]['path']) == arms[name]['sha256']
    directory = (ROOT / arms['PAD-A']['path']).parent / 'pad-objects'
    receipt = DOC / ('retired-' + directory.parent.name + '-objects.json')
    if not directory.exists():
        assert receipt.exists(), 'missing objects without a retirement receipt'
        return
    assert not receipt.exists(), 'do not overwrite a previous inventory'
    rows = [dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size,
                 sha256=digest(path)) for path in sorted(directory.rglob('*')) if path.is_file()]
    assert rows
    receipt.write_text(json.dumps(rows, indent=2) + '\n')
    shutil.rmtree(directory)
    print('Retired', len(rows), 'derived files;', sum(row['bytes'] for row in rows),
          'bytes. Both frozen layout binaries and their construction proof remain.')


if __name__ == '__main__':
    main()
