#!/usr/bin/env python3
"""Audit this lane's tokens, literal bytes, tool comments and documentation counts."""
from bisect import bisect_left
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = '9a09e59190'
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp
from format import anchors, literals

OWNED = tuple('src/' + name for name in (
    'core/boot_support.h', 'core/fused_boot_gate.h', 'core/fused_owner_turn.inc',
    'core/genthread.cc', 'core/genthread.h', 'core/genthread_pipeline.h',
    'core/reorder.cc', 'core/reorder.h', 'core/rl2s.cc', 'core/shutdown.cc',
    'core/shutdown_report.h', 'main.cc'))
RENAMES = json.loads((Path(__file__).with_name('renames.json')).read_text())


def digest(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def tool_comments(text):
    return tuple(m[0] for m in cpp.LEXER.finditer(text)
                 if m.lastgroup == 'comment' and 'TOMO_TOOL_' in m[0])


def handwritten(text):
    begin = text.find('// BEGIN R7 GENERATED ENVELOPES')
    if begin < 0:
        return text
    end = text.index('// END R7 GENERATED ENVELOPES', begin)
    end = text.index('\n', end)
    return text[:begin] + text[end:]


def comment_groups(text):
    """Group comments at each token boundary, excluding tool/formatter markers."""
    ends = [t.end for t in cpp.lex(text)]
    groups = {}
    for match in cpp.LEXER.finditer(text):
        if match.lastgroup != 'comment':
            continue
        if 'TOMO_TOOL_' in match[0] or match[0].startswith('// clang-format'):
            continue
        groups.setdefault(bisect_left(ends, match.start()), []).append(match[0])
    return {key: '\n'.join(value) for key, value in groups.items()}


def normalized_tokens(text, path):
    code = cpp.lex(text)
    values = [token.text for token in code]
    occurrences = 0
    for entry in RENAMES:
        if entry['path'] != path:
            continue
        if entry['function'] == 'main':
            start = text.index('    ShutdownReportFinalLine final_shutdown_line;')
            end = len(text)
        else:
            _, start, end = cpp.function_span(text, entry['function'])
        for old, new in entry['names'].items():
            positions = [i for i, token in enumerate(code)
                         if start <= token.start < end and token.text == new]
            assert len(positions) == entry['token_occurrences'][old], (path, old, positions)
            for i in positions:
                values[i] = old
            occurrences += len(positions)
    return tuple(values), occurrences


def main():
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', BASE, '--', 'src'], cwd=ROOT, text=True).splitlines()
    assert set(changed) <= set(OWNED), ('outside lane', set(changed) - set(OWNED))
    rows = []
    for path in OWNED:
        before = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT).decode()
        after = (ROOT / path).read_bytes().decode()
        pre_tokens = tuple(token.text for token in cpp.lex(before))
        post_tokens, renamed = normalized_tokens(after, path)
        assert pre_tokens == post_tokens, ('preprocessing tokens', path)
        assert literals(before) == literals(after), ('literal bytes', path)
        assert tool_comments(before) == tool_comments(after), ('tool comment bytes', path)
        assert anchors(before) == anchors(after), ('tool comment boundaries', path)
        pre_comments = comment_groups(handwritten(before))
        post_comments = comment_groups(handwritten(after))
        rewritten = sum(post_comments.get(key) != value for key, value in pre_comments.items())
        # These three headers move from below the first include(s) to byte zero.
        relocated = set(pre_comments) - set(post_comments)
        expected_moves = int(path in ('src/core/genthread.cc', 'src/core/rl2s.cc', 'src/main.cc'))
        assert len(relocated) == expected_moves, ('unaccounted comment move/deletion', path)
        rows.append(dict(path=path, tokens=len(pre_tokens), literals=len(literals(after)),
                         renamed_token_occurrences=renamed,
                         token_sha256=digest(post_tokens), literal_sha256=digest(literals(after)),
                         rewritten_comment_groups=rewritten,
                         relocated_file_headers=len(relocated),
                         landmarks=handwritten(after).count('// Phase '),
                         file_header=after.startswith('//')))
    result = dict(base=BASE, files=len(rows),
                  tokens=sum(row['tokens'] for row in rows),
                  literals=sum(row['literals'] for row in rows),
                  renamed_token_occurrences=sum(row['renamed_token_occurrences'] for row in rows),
                  rewritten_comment_groups=sum(row['rewritten_comment_groups'] for row in rows),
                  landmarks=sum(row['landmarks'] for row in rows),
                  files_with_headers=sum(row['file_header'] for row in rows), rows=rows)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
