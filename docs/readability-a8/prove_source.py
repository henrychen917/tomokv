#!/usr/bin/env python3
"""Reproduce A8's lexical identity and comment census without compiling or booting."""
from bisect import bisect_left
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = '7595a6705'
RELEASE = '5c36312818'
OWNED = tuple('src/store/' + name for name in (
    'flatstore.h', 'flatstore_atomic.inc', 'flatstore_flush.inc', 'flatstore_random.inc'))
RENAMES = json.loads(Path(__file__).with_name('renames.json').read_text())
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp
from format import anchors, literals


def digest(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def comments(text):
    ends = [t.end for t in cpp.lex(text)]
    groups = {}
    for match in cpp.LEXER.finditer(text):
        if match.lastgroup == 'comment' and 'TOMO_TOOL_' not in match[0]:
            groups.setdefault(bisect_left(ends, match.start()), []).append(match[0])
    return {key: '\n'.join(value) for key, value in groups.items()}


def normalize(text, path):
    code = cpp.lex(text)
    values = [t.text for t in code]
    occurrences = {}
    for entry in RENAMES:
        if entry['file'] != path:
            continue
        _, start, end = cpp.function_span(text, entry['function'])
        for old, new in entry['mapping'].items():
            positions = [i for i, token in enumerate(code)
                         if start <= token.start < end and token.text == new]
            assert positions and all(t.text != old for t in code if start <= t.start < end)
            occurrences[entry['function'] + ':' + old] = len(positions)
            for i in positions:
                values[i] = old
    return tuple(values), occurrences


def functions(text):
    """Count token-bearing physical lines, including signature continuations and lambdas."""
    code = cpp.lex(text)
    values = [t.text for t in code]
    pairs, stack = {}, []
    for i, value in enumerate(values):
        if value == '(':
            stack.append(i)
        elif value == ')' and stack:
            pairs[stack.pop()] = i
    result = []
    for i, close in pairs.items():
        name = values[i - 1]
        if not re.fullmatch(r'\w+', name) or name in (
                'if', 'while', 'for', 'switch', 'catch', 'sizeof', 'alignof', 'decltype'):
            continue
        opening = close + 1
        while opening < len(code) and values[opening] in ('const', 'noexcept', 'override', 'final'):
            opening += 1
        if opening >= len(code) or values[opening] != '{':
            continue
        end, depth = opening, 1
        while depth:
            end += 1
            depth += (values[end] == '{') - (values[end] == '}')
        nloc = len({text.count('\n', 0, t.start) for t in code[i-1:end+1]})
        physical = text.count('\n', code[i-1].start, code[end].end) + 1
        if nloc > 50 or physical > 150:
            result.append(dict(name=name, line=text.count('\n', 0, code[i-1].start) + 1,
                               nloc=nloc, physical=physical))
    return result


def main():
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE, '--', 'src'],
                                      cwd=ROOT, text=True).splitlines()
    assert set(changed) <= set(OWNED), ('outside lane', set(changed) - set(OWNED))
    rows = []
    for path in OWNED:
        before = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT).decode()
        release = subprocess.check_output(['git', 'show', f'{RELEASE}:{path}'], cwd=ROOT).decode()
        after = (ROOT / path).read_bytes().decode()
        post, renamed = normalize(after, path)
        assert tuple(t.text for t in cpp.lex(before)) == post, ('base tokens', path)
        assert tuple(t.text for t in cpp.lex(release)) == post, ('release tokens', path)
        assert literals(before) == literals(release) == literals(after), ('literal bytes', path)
        assert anchors(before) == anchors(after), ('tool comment boundaries', path)
        tool = lambda s: tuple(m[0] for m in cpp.LEXER.finditer(s)
                               if m.lastgroup == 'comment' and 'TOMO_TOOL_' in m[0])
        assert tool(before) == tool(after), ('tool comment bytes', path)
        pre_comments, post_comments = comments(before), comments(after)
        rows.append(dict(file=path, tokens=len(post), literal_tokens=len(literals(after)),
                         token_sha256=digest(post), literal_sha256=digest(literals(after)),
                         renamed_token_occurrences=renamed,
                         rewritten_comment_groups=sum(post_comments.get(k) != v
                                                      for k, v in pre_comments.items()),
                         new_comment_boundaries=len(set(post_comments) - set(pre_comments)),
                         landmarks=len(re.findall(r'// Phase \d+:', after)),
                         header=after.startswith('//'), long_functions=functions(after)))
    print(json.dumps(dict(base=BASE, release=RELEASE, rows=rows,
                          totals=dict(tokens=sum(r['tokens'] for r in rows),
                                      literal_tokens=sum(r['literal_tokens'] for r in rows),
                                      rewritten_comment_groups=sum(r['rewritten_comment_groups'] for r in rows),
                                      landmarks=sum(r['landmarks'] for r in rows),
                                      file_headers=sum(r['header'] for r in rows),
                                      renamed_bindings=sum(r['bindings'] for r in RENAMES))), indent=2))


if __name__ == '__main__':
    main()
