#!/usr/bin/env python3
"""Format only the reviewed manifest with the pinned formatter; preserve C/C++ tokens."""
import argparse
from bisect import bisect_left
from importlib.metadata import version
from pathlib import Path
import re
import subprocess
import sys

import source_tokens as cpp

ROOT = Path(__file__).resolve().parents[1]


def literals(text):
    return tuple(m[0] for m in cpp.LEXER.finditer(text) if m.lastgroup in ('raw', 'string'))


def anchors(text):
    """Keep every tool comment at the same boundary in the full token sequence."""
    ends = [t.end for t in cpp.lex(text)]
    return tuple((re.sub(r'\s+', ' ', m[0]).strip(), bisect_left(ends, m.start()))
                 for m in cpp.LEXER.finditer(text)
                 if m.lastgroup == 'comment' and 'TOMO_TOOL_' in m[0])


def preserve(before, after, filename):
    if tuple(t.text for t in cpp.lex(before)) != tuple(t.text for t in cpp.lex(after)):
        raise ValueError(f'{filename}: formatter changed preprocessing tokens')
    if literals(before) != literals(after):
        raise ValueError(f'{filename}: formatter changed literal bytes')
    if anchors(before) != anchors(after):
        raise ValueError(f'{filename}: formatter detached a tool anchor')


def file_list():
    files = (ROOT / 'tools/format-files.txt').read_text().splitlines()
    if not files or files != sorted(set(files)):
        raise ValueError('format-files.txt must be a nonempty sorted unique file list')
    for filename in files:
        path = Path(filename)
        if path.is_absolute() or '..' in path.parts or path.parts[0] not in ('src', 'tests', 'tools'):
            raise ValueError(f'outside formatter scope: {filename}')
        if any(part in path.parts for part in ('third_party', 'archive')):
            raise ValueError(f'vendored or archived source: {filename}')
        header = '\n'.join((ROOT / filename).read_text().splitlines()[:12])
        if re.search(r'(?i)(generated (?:by|from)|auto.generated|do not edit)', header):
            raise ValueError(f'generated file in formatter manifest: {filename}')
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    pin = (ROOT / 'tools/format-requirements.txt').read_text().strip().removeprefix('clang-format==')
    clang = Path(sys.executable).parent / 'clang-format'
    if version('clang-format') != pin or subprocess.check_output([str(clang), '--version'], text=True).strip() != f'clang-format version {pin}':
        raise ValueError(f'expected clang-format {pin}; run make format-setup')
    pending = []
    files = file_list()
    for filename in files:
        path = ROOT / filename
        before = path.read_text()
        after = subprocess.check_output([str(clang), '--Werror', f'--style=file:{ROOT / ".clang-format"}', str(path)], text=True)
        preserve(before, after, filename)
        if before != after:
            pending.append((path, after))
    for path, after in pending:
        print(path.relative_to(ROOT))
        if not args.check:
            path.write_text(after)
    if args.check and pending:
        print(f'{len(pending)} files need formatting; run make format', file=sys.stderr)
        return 1
    # Only the generator writes its protected regions, after its inputs are formatted.
    command = [sys.executable, 'tests/r7shadow_sync.py']
    if not args.check:
        command.append('--write')
    subprocess.run(command, cwd=ROOT, check=True)
    print(f'clang-format {pin}: {len(files)} files {"checked" if args.check else "formatted"}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
