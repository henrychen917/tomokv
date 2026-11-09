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
IMPL = 'src/store/flatstore_impl.h'
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


def member_definitions(text):
    code = cpp.lex(text)
    values = [t.text for t in code]
    pos, result = 0, []
    if values[:3] == ['#', 'pragma', 'once']:
        pos = 3
    while pos < len(code):
        opening = next(i for i in range(pos, len(code)) if values[i] == '{')
        depth, end = 1, opening
        while depth:
            end += 1
            depth += (values[end] == '{') - (values[end] == '}')
        result.append((text[code[pos].start:code[opening].start],
                       text[code[opening].start:code[end].end]))
        pos = end + 1
    return result


def definition_signature(signature):
    """The permitted in-class -> inline out-of-class declaration transformation."""
    source = [t.text for t in cpp.lex(signature)]
    values, i = [], 0
    while i < len(source):
        token = source[i]
        if token == 'static':
            i += 1
        elif token == '=':
            i += 1
            depth = 0
            while i < len(source) and not (depth == 0 and source[i] in (',', ')', '>')):
                depth += (source[i] in ('(', '[', '{')) - (source[i] in (')', ']', '}'))
                i += 1
        else:
            values.append(token)
            i += 1
    # This suffix has two standard attributes and no GNU attribute parameter lists.
    opening = values.index('(')
    name_index = opening - 1
    member_name = values[name_index]
    for i in range(name_index - 1, -1, -1):
        if values[i] in ('TtlResult', 'InsertResult', 'OverwriteResult', 'SnapshotWriteResult'):
            values[i:i] = ['FlatStore', '::']
            name_index += 2
    values[name_index:name_index] = ['FlatStore', '::']
    prefix = values.index('>') + 1 if values[0] == 'template' else 0
    if values[prefix:prefix+2] == ['[', '[']:
        prefix = next(i + 2 for i in range(prefix, len(values) - 1)
                      if values[i:i+2] == [']', ']'])
    if member_name == 'expire_found':
        # Keep both noinline and inline on the first declaration. Repeating either
        # at the definition produces GCC's contradictory-attribute warning.
        assert values[:prefix] == ['[', '[', 'gnu', '::', 'noinline', ']', ']']
        values = values[prefix:]
    else:
        values.insert(prefix, 'inline')
    return tuple(values)


def restore_split(text):
    """Verify every moved definition/signature, then reconstruct the original file shape."""
    before = subprocess.check_output(['git', 'show', f'{BASE}:src/store/flatstore.h'],
                                     cwd=ROOT).decode()
    begin = before.index('    [[gnu::noinline]] KvObj* expire_found')
    end = before.index('    friend struct FlatStoreLayoutLock;', begin)
    originals = member_definitions(before[begin:end])
    implementation = (ROOT / IMPL).read_bytes().decode()
    moved = member_definitions(implementation)
    assert len(originals) == len(moved) == 60, 'split inventory'
    replacements = []
    body_tokens = 0
    for (signature, _), (definition, body) in zip(originals, moved):
        assert tuple(t.text for t in cpp.lex(definition)) == definition_signature(signature), definition
        declaration = signature
        if 'expire_found' in [t.text for t in cpp.lex(signature)]:
            declaration = signature.replace(']] KvObj*', ']] inline KvObj*')
        hits = cpp.Source(text).spans(declaration + ';')
        assert len(hits) == 1, ('member declaration', signature, hits)
        first, last = hits[0]
        replacements.append((first, last, signature + body))
        body_tokens += len(cpp.lex(body))
    for first, last, replacement in sorted(replacements, reverse=True):
        text = text[:first] + replacement + text[last:]
    seam = '};\n\n#include "flatstore_impl.h"'
    assert text.count(seam) == 1, 'immediate post-class include'
    text = text.replace(seam, '};')
    return text, dict(file=IMPL, definitions=len(moved), body_tokens=body_tokens,
                      header=implementation.startswith('//'),
                      long_functions=functions(implementation))


def main():
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE, '--', 'src'],
                                      cwd=ROOT, text=True).splitlines()
    assert set(changed) <= set(OWNED) | {IMPL}, ('outside lane', set(changed) - set(OWNED) - {IMPL})
    rows = []
    split = None
    for path in OWNED:
        before = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT).decode()
        release = subprocess.check_output(['git', 'show', f'{RELEASE}:{path}'], cwd=ROOT).decode()
        after = (ROOT / path).read_bytes().decode()
        actual = after
        if path == 'src/store/flatstore.h':
            after, split = restore_split(after)
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
                         header=after.startswith('//'), long_functions=functions(actual)))
    print(json.dumps(dict(base=BASE, release=RELEASE, rows=rows, split=split,
                          totals=dict(tokens=sum(r['tokens'] for r in rows),
                                      literal_tokens=sum(r['literal_tokens'] for r in rows),
                                      rewritten_comment_groups=sum(r['rewritten_comment_groups'] for r in rows),
                                      landmarks=sum(r['landmarks'] for r in rows),
                                      file_headers=sum(r['header'] for r in rows) + int(split['header']),
                                      renamed_bindings=sum(r['bindings'] for r in RENAMES))), indent=2))


if __name__ == '__main__':
    main()
