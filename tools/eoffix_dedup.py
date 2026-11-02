#!/usr/bin/env python3
"""Share byte-identical Redis tools in completed, private Tcl checkouts."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    assert os.sched_getaffinity(0) <= set(range(8))
    cache = ROOT / 'build/eoffix/oracle-tools'
    cache.mkdir(exist_ok=True)
    receipt = ROOT / 'docs/eoffix/deduplicated-tools.json'
    rows = json.loads(receipt.read_text()) if receipt.exists() else []
    for job in sorted((ROOT/'build').glob('gate-run.*/jobs/redis_tcl')):
        if not (job/'done').exists():
            continue
        for path in sorted(job.glob('*/checkout/src/redis-*')):
            if path.is_symlink() or not path.is_file() or path.stat().st_size < 1024*1024:
                continue
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            shared = cache / digest
            if not shared.exists():
                os.link(path, shared)
            if path.samefile(shared):
                continue
            temporary = path.with_suffix('.eoffix-link')
            os.link(shared, temporary)
            os.replace(temporary, path)
            rows.append(dict(path=str(path.relative_to(ROOT)), sha256=digest,
                             shared=str(shared.relative_to(ROOT)), bytes=path.stat().st_size))
    receipt.write_text(json.dumps(rows, indent=2)+'\n')
    print('identical private tool copies shared:', len(rows))


if __name__ == '__main__':
    main()
