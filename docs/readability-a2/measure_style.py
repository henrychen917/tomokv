#!/usr/bin/env python3
"""Measure the frozen first-party C/C++ style without modifying source files."""
import collections
import json
import math
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp

BASE = '52dbad6c9e470b42725b015303de6ce86ca1a57a'
SUFFIXES = {'.c', '.cc', '.cpp', '.h', '.hpp', '.inc', '.def'}
GENERATED = {
    'src/cmd/acl_categories_generated.h',
    'src/cmd/cmddocs_generated.inc',
    'src/cmd/cmdmeta_generated.inc',
}


def paths():
    tracked = subprocess.check_output(
        ['git', 'ls-tree', '-r', '--name-only', BASE, 'src', 'tests', 'tools'],
        cwd=ROOT, text=True).splitlines()
    return [p for p in tracked if Path(p).suffix in SUFFIXES and p not in GENERATED
            and not any(x in Path(p).parts for x in ('archive', 'third_party'))]


def original(path):
    return subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT).decode()


def handwritten(text):
    return re.sub(r'(?m)^.*// BEGIN R7 GENERATED ENVELOPES\n[\s\S]*?^.*// END R7 GENERATED ENVELOPES\n', '', text)


def measure(files):
    lengths, nonblank = [], []
    indents, deltas, braces, pointers, access, namespaces = [collections.Counter() for _ in range(6)]
    for path in files:
        text = handwritten(original(path))
        lines = text.splitlines()
        lengths.extend(len(s.expandtabs(4)) for s in lines)
        nonblank.extend(len(s.expandtabs(4)) for s in lines if s.strip())
        # Keep token positions, but blank comments and literals for style heuristics.
        code = list(text)
        for match in cpp.LEXER.finditer(text):
            if match.lastgroup in ('comment', 'raw', 'string'):
                code[match.start():match.end()] = ['\n' if c == '\n' else ' ' for c in match[0]]
        code = ''.join(code)
        code_lines = code.splitlines()
        indentation = lambda s: len(s) - len(s.lstrip(' '))
        for i, line in enumerate(code_lines):
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            indents[indentation(line)] += 1
            if i and code_lines[i-1].rstrip().endswith('{'):
                delta = indentation(line) - indentation(code_lines[i-1])
                if delta > 0:
                    deltas[delta] += 1
        tokens = cpp.lex(code)
        stack = []
        for i, token in enumerate(tokens):
            if token.text == '{':
                before = tokens[i-1] if i else token
                if before.text in (')', 'else', 'try', 'do', 'const', 'noexcept', 'override'):
                    braces['next_line' if '\n' in code[before.end:token.start] else 'attached'] += 1
                start = code.rfind('\n', 0, token.start) + 1
                stack.append(indentation(code[start:token.start]))
            elif token.text == '}' and stack:
                stack.pop()
            elif token.text in ('public', 'private', 'protected') and stack and tokens[i+1].text == ':':
                start = code.rfind('\n', 0, token.start) + 1
                access[token.start - start - stack[-1]] += 1
        pointer = r'\b(?:auto|char|void|bool|int|unsigned|size_t|[a-z0-9_]+_t|[A-Z]\w*)(\s*)(\*+)(\s*)(?=[a-zA-Z_]\w*)'
        for m in re.finditer(pointer, code):
            pointers['left' if not m[1] and m[3] else 'right' if m[1] and not m[3] else 'middle' if m[1] and m[3] else 'neither'] += 1
        for m in re.finditer(r'(?m)^( *)namespace\b[^\n{]*\{[^\n]*\n(?:\s*\n)*([ ]*)(?=\S)', code):
            namespaces[len(m[2]) - len(m[1])] += 1
    percentile = lambda xs: sorted(xs)[math.ceil(len(xs) * .95) - 1]
    return dict(files=len(files), physical_lines=len(lengths), nonblank_lines=len(nonblank),
                line_length_p95=percentile(lengths), nonblank_line_length_p95=percentile(nonblank),
                indent_columns=dict(sorted(indents.items())), block_indent_increases=dict(deltas.most_common()),
                braces=dict(braces), pointers=dict(pointers), access_offset_from_class=dict(access),
                namespace_indent=dict(namespaces))


if __name__ == '__main__':
    selected = paths()
    result = dict(base=BASE, scope=measure(selected), production=measure([p for p in selected if p.startswith('src/')]))
    out = ROOT / 'build/readability-a2'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'style.json').write_text(json.dumps(result, indent=2) + '\n')
    (out / 'format-files.txt').write_text('\n'.join(selected) + '\n')
    print(json.dumps(result, indent=2))
