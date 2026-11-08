#!/usr/bin/env python3
"""Freeze release arms and an exact-layout type-A PRE behaviour control."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import exec1s_pad
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/netfix2'
DOC = ROOT / 'docs/netfix2'


def main():
    assert os.sched_getaffinity(0) <= set(range(8, 16))
    subprocess.run(['make', '-q', 'all'], check=True)
    shutil.copy2(ROOT / 'build/tomokv', OUT / 'POST')
    exec1s_pad.build(OUT / 'pre-source', ROOT, OUT, DOC / 'pad-a.json')
    rows = []
    for name in ('PRE', 'POST', 'POST-layout', 'PAD-A'):
        path = OUT / name
        elf = Elf(path)
        body = elf.section_data(elf.names.index('.text'))
        rows.append(dict(arm=name, path=str(path.relative_to(ROOT)),
                         sha256=hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
                         text_bytes=len(body), text_sha256=hashlib.sha256(body).hexdigest()))
    (DOC / 'arms.json').write_text(json.dumps(rows, indent=2) + '\n')
    (DOC / 'SHA256SUMS').write_text(''.join(r['sha256'] + '  ' + r['path'] + '\n' for r in rows))
    # The symbol map and link receipt suffice to regenerate these copies.
    shutil.rmtree(OUT / 'pad-objects')
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
