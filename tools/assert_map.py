#!/usr/bin/env python3
"""Map stable assertion ids to physical source locations; never obey #line.

The lexer implements line splicing, comments, ordinary/raw literals and C++ digit
separators. Macro definitions are not sites. Salt/pin arguments must be integer
literals, so the map and compiler cannot silently disagree about their value.
"""
import argparse
from bisect import bisect_right
import csv
from dataclasses import dataclass
import io
from pathlib import Path
import re
import shlex
import subprocess
import sys

SPACE = ' \t\n\r\f\v'
MACROS = {'TOMO_ASSERT': 1, 'TOMO_ASSERT_SALT': 2, 'TOMO_ASSERT_ID': 2}


@dataclass(frozen=True)
class Token:
    text: str
    line: int
    kind: str = 'code'
    logical_line: int = 0


def lex(source):
    # Translation phase 2 precedes comments and tokenization. Track removed
    # newlines separately so diagnostics still use physical source positions.
    splices, removed = [], 0
    for match in re.finditer(r'\\\r?\n', source):
        splices.append(match.start() - removed)
        removed += len(match[0])
    text = re.sub(r'\\\r?\n', '', source)
    pattern = re.compile(
        r'(?P<space>\s+)|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|'
        r'(?P<raw>(?:u8|u|U|L)?R"(?P<delimiter>[^ ()\\\t\n]{0,16})\([\s\S]*?\)(?P=delimiter)")|'
        r'(?P<string>(?:u8|u|U|L)?"(?:\\[\s\S]|[^"\\])*"|(?:u8|u|U|L)?\'(?:\\[\s\S]|[^\'\\])*\')|'
        r'(?P<number>[0-9][a-zA-Z0-9_\'.]*)|(?P<word>[a-zA-Z_$][a-zA-Z0-9_$]*)|'
        r'(?P<punct>%:%:|%:|##|::|&&|\|\||<=|>=|==|!=|->|<<|>>|\.\.\.|.)')
    logical_line = 1
    for match in pattern.finditer(text):
        physical_line = logical_line + bisect_right(splices, match.start())
        token_line = logical_line
        logical_line += match[0].count('\n')
        kind = match.lastgroup
        if kind in ('space', 'comment'):
            continue
        # The raw-string delimiter group is nested; the enclosing group wins.
        value = {'%:': '#', '%:%:': '##'}.get(match[0], match[0])
        yield Token(value, physical_line,
                    'literal' if kind in ('raw', 'string') else 'code', token_line)


def directives(source):
    """Real directives only: comments and raw-string contents are not syntax."""
    group, previous = [], 0
    for token in lex(source):
        if token.logical_line != previous:
            if group:
                yield group[0].line, max(t.line + t.text.count('\n') for t in group), spelling(group)
            group = [token] if token.text == '#' and token.kind != 'literal' else []
            previous = token.logical_line
        elif group:
            group.append(token)
    if group:
        yield group[0].line, max(t.line + t.text.count('\n') for t in group), spelling(group)


def fnv(condition, salt=0):
    value = 2166136261 ^ salt
    for byte in condition.encode('utf-8'):
        if byte not in b' \t\n\r\f\v':
            value = ((value ^ byte) * 16777619) & 0xffffffff
    return value | 0x80000000


def spelling(tokens):
    # Whitespace between preprocessing tokens is immaterial to the hash. Keep
    # the original spelling of literals (including escapes) for stringification.
    return ' '.join(t.text for t in tokens)


def integer(tokens):
    value = ''.join(t.text for t in tokens)
    if not re.fullmatch(r'(?:0[xX][0-9a-fA-F\']+|0[bB][01\']+|[0-9][0-9\']*)[uUlL]*', value):
        raise ValueError('salt/pin must be an unsigned integer literal')
    value = re.sub(r'[uUlL]+$', '', value).replace("'", '')
    result = int(value, 0) if len(value) > 1 and value[0] == '0' else int(value)
    if not 0 <= result <= 0xffffffff:
        raise ValueError('salt/pin must fit uint32_t')
    return result


def enclosing(tokens, stop):
    """Track namespace/class/function braces; controls keep their parent's name.

    Fail closed for a site whose function cannot be found. This is a source map,
    not a C++ parser: unusual declarators can be given a better parser later,
    but must never be silently mapped to an invented function.
    """
    stack, begin = [], 0
    control = {'if', 'constexpr', 'for', 'while', 'switch', 'catch', 'sizeof', 'alignof', 'decltype',
               'noexcept', 'static_cast', 'reinterpret_cast', 'const_cast', 'dynamic_cast'}
    for index, token in enumerate(tokens[:stop]):
        if token.text == '{':
            head = tokens[begin:index]
            words = [t.text for t in head]
            scope, kind = '', 'block'
            if words and words[0] in ('namespace', 'class', 'struct', 'union'):
                kind = 'scope'
                scope = words[1] if len(words) > 1 else '(anonymous)'
                if words[0] == 'namespace':
                    scope = ''.join(words[1:]) or '(anonymous)'
            else:
                depth = 0
                for j, word in enumerate(words):
                    if word == '(':
                        if depth == 0 and j:
                            first = j - 1
                            # Assignment operators and destructors occur in the
                            # intrusive claim nodes; retain their exact names.
                            if j >= 2 and words[j - 2:j] == ['operator', '=']:
                                first = j - 2
                            elif re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', words[j - 1]) and words[j - 1] not in control:
                                if first and words[first - 1] == '~':
                                    first -= 1
                            else:
                                depth += 1
                                continue
                            while first >= 2 and words[first - 1] == '::':
                                first -= 2
                            scope, kind = ''.join(words[first:j]), 'function'
                            break
                        depth += 1
                    elif word == ')':
                        depth -= 1
            stack.append((scope, kind))
            begin = index + 1
        elif token.text == '}':
            if stack:
                stack.pop()
            begin = index + 1
        elif token.text == ';':
            begin = index + 1
    if not any(kind == 'function' for _, kind in stack):
        raise ValueError('assertion is not inside a recognized function')
    return '::'.join(name for name, _ in stack if name)


@dataclass(frozen=True)
class Site:
    id: int
    location: str
    function: str
    condition: str
    mode: str
    value: int


def scan_file(path, root):
    source = path.read_text()
    if path.relative_to(root).as_posix() not in ('src/base/tomo_assert.h', 'src/base/tomo_assert_c.h'):
        for start, _, directive in directives(source):
            if any(t.kind != 'literal' and t.text in MACROS for t in lex(directive)):
                raise ValueError(f'{path.relative_to(root)}:{start}: assertion wrappers hide source sites; call TOMO_ASSERT directly')
    excluded = {line for start, end, _ in directives(source) for line in range(start, end + 1)}
    tokens = [t for t in lex(source) if t.line not in excluded]
    sites = []
    for i, token in enumerate(tokens):
        if token.kind == 'literal' or token.text not in MACROS:
            continue
        location = f'{path.relative_to(root)}:{token.line}'
        try:
            if i + 1 == len(tokens) or tokens[i + 1].text != '(':
                raise ValueError('assertion macro must be called directly')
            args, current, depth = [], [], 0
            for item in tokens[i + 2:]:
                if item.text == ')' and depth == 0:
                    args.append(current)
                    break
                if item.text == ',' and depth == 0:
                    args.append(current)
                    current = []
                    continue
                if item.kind != 'literal':
                    depth += item.text in ('(', '[', '{')
                    depth -= item.text in (')', ']', '}')
                current.append(item)
            else:
                raise ValueError('unterminated assertion')
            if len(args) != MACROS[token.text] or any(not arg for arg in args):
                raise ValueError('wrong assertion argument count')
            condition = spelling(args[0])
            value = integer(args[1]) if len(args) == 2 else 0
            mode = 'pin' if token.text == 'TOMO_ASSERT_ID' else 'salt'
            site_id = value if mode == 'pin' else fnv(condition, value)
            if not 0x80000000 <= site_id <= 0xffffffff:
                raise ValueError('id must have its top bit set (including explicit pins)')
            sites.append(Site(site_id, location, enclosing(tokens, i), condition, mode, value))
        except ValueError as error:
            raise ValueError(f'{location}: {error}') from error
    return sites


def production_paths(root):
    # The six separately compiled helper C files are production code too. The
    # pre-existing upstream Lua VM keeps its original vendored boundary.
    for directory in (root / 'src', root / 'third_party/lua/helpers'):
        for path in sorted(directory.rglob('*')):
            if path.suffix in ('.h', '.cc', '.inc', '.c', '.def'):
                yield path


def scan(root):
    sites, seen = [], {}
    for path in production_paths(root):
        for site in scan_file(path, root):
            if site.id in seen:
                raise ValueError(f'duplicate id {site.id} (0x{site.id:08x}): '
                                 f'{seen[site.id]} and {site.location}; use TOMO_ASSERT_SALT')
            seen[site.id] = site.location
            sites.append(site)
    return sites


def verify(sites, root, cxx):
    # Stringify exactly as TOMO_ASSERT does, not as a Python approximation of
    # C++ string escaping. Each condition is unevaluated preprocessing input.
    source = ['#include "src/base/tomo_assert.h"',
              '#define HASH_CHECK(expected, salt, ...) static_assert('
              '::tomo::detail::assert_site_id(#__VA_ARGS__, salt) == expected)']
    for site in sites:
        if site.mode != 'pin':
            source.append(f'HASH_CHECK({site.id}u, {site.value}u, {site.condition});')
    subprocess.run(shlex.split(cxx) + ['-std=c++20', '-I', str(root), '-x', 'c++',
                                     '-fsyntax-only', '-'], input='\n'.join(source),
                   text=True, check=True)


def tsv(sites):
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    writer.writerow(('id_decimal', 'id_hex', 'file:line', 'function', 'condition', 'salt_or_pin'))
    for site in sites:
        writer.writerow((site.id, f'0x{site.id:08x}', site.location, site.function,
                         site.condition, f'{site.mode}={site.value}'))
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, default=Path('build/tomokv.asserts.tsv'))
    parser.add_argument('--pin', metavar='FILE:LINE', help='print the stable id for a condition rename')
    parser.add_argument('--cxx', default='g++', help='compiler used for Python/C++ hash agreement')
    args = parser.parse_args()
    try:
        sites = scan(args.root.resolve())
        if args.pin:
            selected = [site for site in sites if site.location == args.pin]
            if len(selected) != 1:
                raise ValueError(f'expected one assertion at {args.pin}, found {len(selected)}')
            print(f'0x{selected[0].id:08x}u')
            return
        verify(sites, args.root.resolve(), args.cxx)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + '.tmp')
        temporary.write_text(tsv(sites))
        temporary.replace(args.output)
        print(f'assert map: {len(sites)} unique sites -> {args.output}')
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'assert map: {error}\n')


if __name__ == '__main__':
    main()
