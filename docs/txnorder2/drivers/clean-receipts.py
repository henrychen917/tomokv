#!/usr/bin/env python3
"""Hash and remove only disallowed generated artifacts below docs/txnorder2.

Executable merit arms remain in ignored build/. Small textual receipts and
source recipes remain in docs/. This is deliberately limited to this lane's
receipt tree; it never cleans another lane, a build tree, or external data.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / 'docs/txnorder2'
OUT = DOCS / 'discarded-artifacts'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delete', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    rows = []
    for path in sorted(DOCS.rglob('*')):
        if not path.is_file() or path.is_symlink() or OUT in path.parents:
            continue
        relative = path.relative_to(DOCS)
        size = path.stat().st_size
        with path.open('rb') as f:
            prefix = f.read(min(size, 8192))
        reason = None
        if path.suffix in ('.gz', '.o', '.so', '.a', '.pyc', '.rdb', '.tomo', '.core'):
            reason = 'binary or compressed generated artifact'
        elif path.suffix in ('.asm', '.objdump') or (
                relative.parts[0].startswith('r7-') and '.diff' in path.name):
            reason = 'raw disassembly or disassembly diff'
        elif path.suffix == '.log' and b'scatter_trace_begin' in prefix:
            reason = 'raw debugger instruction trace; named counts retained separately'
        elif size > 1_000_000:
            reason = 'larger than 1 MB'
        elif b'\0' in prefix:
            reason = 'binary content'
        if reason is None:
            data = path.read_bytes()
            try:
                data.decode('utf-8')
                if b'\0' in data:
                    reason = 'binary content'
            except UnicodeDecodeError:
                reason = 'binary content'
        if not reason:
            continue
        h = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''):
                h.update(block)
        row = dict(path=str(relative), bytes=size, sha256=h.hexdigest(), reason=reason)
        if path.suffix == '.log' and b'\0' not in prefix:
            with path.open('rb') as f:
                head = f.read(4096)
                f.seek(max(0, size - 4096))
                tail = f.read(4096)
            row['head'] = head.decode('utf-8', errors='replace').splitlines()[:8]
            row['tail'] = tail.decode('utf-8', errors='replace').splitlines()[-12:]
        rows.append(row)
    # Never overwrite an earlier deletion inventory on a later cleanup pass.
    batch = 1 + len(list(OUT.glob('index-*.json')))
    parts = []
    for index in range(0, len(rows), 100):
        target = OUT / f'batch-{batch:02d}-{index // 100:03d}.json'
        target.write_text(json.dumps(rows[index:index + 100], indent=2) + '\n')
        assert target.stat().st_size <= 1_000_000
        parts.append(str(target.relative_to(DOCS)))
    summary = dict(files=len(rows), bytes=sum(r['bytes'] for r in rows),
                   deleted=args.delete, parts=parts,
                   retained='Small run/result JSON, named/function counts, build recipes, '
                            'identity inventories and logs; merit binaries remain in build/.')
    (OUT / f'index-{batch:02d}.json').write_text(json.dumps(summary, indent=2) + '\n')
    if args.delete:
        for row in rows:
            path = DOCS / row['path']
            assert path.is_file() and not path.is_symlink()
            path.unlink()
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
