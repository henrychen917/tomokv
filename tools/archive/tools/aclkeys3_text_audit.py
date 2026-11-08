#!/usr/bin/env python3
"""Grep tests for changed literal text and repository encodings; no server execution."""
import argparse
import ast
import gzip
import json
from pathlib import Path
import re
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('base')
    p.add_argument('output', type=Path)
    args = p.parse_args()
    terms = set()
    diff = subprocess.check_output(['git', 'diff', args.base, '--', 'src/', 'tests/'], text=True)
    for line in diff.splitlines():
        if not line.startswith(('+', '-')) or line.startswith(('+++', '---')):
            continue
        for quoted in re.findall(r'"(?:\\.|[^"\\])*"', line[1:]):
            try:
                text = ast.literal_eval(quoted)
            except (ValueError, SyntaxError):
                continue
            if text:
                terms.add(text)
    patterns = set()
    for text in terms:
        for spelling in (text, text.lower(), text.upper()):
            patterns.update(part for part in spelling.splitlines() if part)
            escaped = repr(spelling)[1:-1]
            patterns.update((escaped, escaped.replace('\\', '\\\\'),
                             json.dumps(spelling)[1:-1],
                             ''.join('\\x%02x' % byte for byte in spelling.encode()),
                             ''.join('\\%03o' % byte for byte in spelling.encode())))
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / 'text-patterns.txt'
    path.write_text('\n'.join(sorted(patterns)) + '\n')
    command = ['grep', '-R', '-I', '-n', '-F', '-f', str(path),
               '--exclude-dir=__pycache__', 'tests/']
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode in (0, 1), result.stderr
    with gzip.open(args.output / 'text-audit.txt.gz', 'wt') as stream:
        stream.write(result.stdout)
    report = dict(base=args.base, command=command, terms=sorted(terms), patterns=len(patterns),
                  matched_lines=len(result.stdout.splitlines()),
                  encodings=['literal lines', 'lowercase', 'uppercase', 'Python escaped',
                             'double escaped', 'JSON escaped', 'hexadecimal bytes', 'octal bytes'],
                  production_existing_reply_text_changed=False)
    (args.output / 'text-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(len(terms), 'literals;', len(patterns), 'encodings;', report['matched_lines'], 'matched lines')


if __name__ == '__main__':
    main()
