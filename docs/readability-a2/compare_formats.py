#!/usr/bin/env python3
"""Compare three pinned formatter presets on identical frozen inputs."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

from measure_style import BASE, ROOT, original, paths
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp

WORK = ROOT / 'build/readability-a2/candidates'
CLANG = ROOT / 'build/clang-format-18.1.8/bin/clang-format'
COMMON = '''IndentWidth: 4
ContinuationIndentWidth: 4
ColumnLimit: 100
BreakBeforeBraces: Attach
PointerAlignment: Left
DerivePointerAlignment: false
AccessModifierOffset: -4
NamespaceIndentation: None
SortIncludes: Never
SortUsingDeclarations: Never
BreakStringLiterals: false
InsertBraces: false
QualifierAlignment: Leave
ReflowComments: false
FixNamespaceComments: false
RawStringFormats: []
'''


def protect(text):
    return text.replace('// BEGIN R7 GENERATED ENVELOPES', '// clang-format off\n// BEGIN R7 GENERATED ENVELOPES').replace(
        '// END R7 GENERATED ENVELOPES', '// END R7 GENERATED ENVELOPES\n// clang-format on')


def literal_tokens(text):
    # Raw spelling, including literal-internal backslash/newline, is significant.
    return tuple(m[0] for m in cpp.LEXER.finditer(text) if m.lastgroup in ('raw', 'string'))


def main():
    selected = paths()
    for path in selected:
        dest = WORK / 'pre' / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(protect(original(path)))
    results = []
    for preset in ('LLVM', 'Google', 'WebKit'):
        root = WORK / preset
        root.mkdir(parents=True, exist_ok=True)
        config = root / '.clang-format'
        config.write_text(f'BasedOnStyle: {preset}\n' + COMMON)
        def render(path):
            before = (WORK / 'pre' / path).read_text()
            result = subprocess.run([str(CLANG), '--Werror',
                                     f'--style=file:{config}', f'--assume-filename={path}'],
                                    input=before, text=True, capture_output=True, check=True)
            after = result.stdout
            dest = root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(after)
            return dict(path=path, changed=before != after,
                        tokens_equal=tuple(t.text for t in cpp.lex(before)) == tuple(t.text for t in cpp.lex(after)),
                        literals_equal=literal_tokens(before) == literal_tokens(after))
        with ThreadPoolExecutor(max_workers=8) as pool:
            checks = list(pool.map(render, selected))
        diff = subprocess.run(['git', 'diff', '--no-index', '--numstat', str(WORK / 'pre'), str(root)],
                              text=True, capture_output=True)
        assert diff.returncode in (0, 1), diff.stderr
        stats = [line.split('\t') for line in diff.stdout.splitlines() if not line.endswith('.clang-format')]
        row = dict(preset=preset, changed_files=sum(c['changed'] for c in checks),
                   added=sum(int(s[0]) for s in stats), deleted=sum(int(s[1]) for s in stats),
                   exceptions=[c for c in checks if not c['tokens_equal'] or not c['literals_equal']])
        results.append(row)
        (WORK / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
