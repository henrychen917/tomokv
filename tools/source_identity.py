#!/usr/bin/env python3
"""Reject source identity in production code, including macro indirection.

The source pass conservatively checks all non-trace branches. A compiler pass
also expands each production TU in both database variants: built-in macros use
sentinels so token pasting/aliases cannot hide them by expanding to a literal.
System headers are excluded by preprocessor line markers; their expansions at
an in-tree call site are checked. Ordinary literals and comments are harmless.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import shlex
import subprocess
import sys

from assert_map import directives, lex, production_paths

FORBIDDEN = {'assert', '__FILE__', '__BASE_FILE__', '__FILE_NAME__', '__LINE__', '__func__', '__FUNCTION__',
             '__PRETTY_FUNCTION__', 'source_location', '__builtin_FILE',
             '__builtin_LINE', '__builtin_FUNCTION', '__DATE__', '__TIME__',
             '__TIMESTAMP__', '__COUNTER__', '__builtin_source_location'}
BUILTINS = ('__FILE__', '__BASE_FILE__', '__FILE_NAME__', '__LINE__', '__DATE__', '__TIME__', '__TIMESTAMP__', '__COUNTER__')
SENTINEL = 'TOMO_SOURCE_IDENTITY_FORBIDDEN_'
TRACE = re.compile(r'TOMO_\w+_TRACE\Z')


def trace_lines(source):
    """Exclude only branches requiring a trace define; never exclude its else."""
    skipped, stack, active, cursor = set(), [], True, 1
    for start, end, directive in directives(source):
        if not active:
            skipped.update(range(cursor, start))
        words = [t.text for t in lex(directive)]
        kind, args = (words[1], words[2:]) if len(words) > 1 else ('', [])
        if kind in ('if', 'ifdef', 'ifndef'):
            trace = len(args) == 1 and bool(TRACE.fullmatch(args[0]))
            if kind == 'if':
                expression = ''.join(args)
                trace = bool(re.fullmatch(r'defined\(?TOMO_\w+_TRACE\)?', expression))
            false_in_production = trace and kind != 'ifndef'
            true_in_production = trace and kind == 'ifndef'
            stack.append((active, false_in_production, true_in_production))
            active = active and not false_in_production
        elif kind in ('else', 'elif') and stack:
            parent, false_branch, true_branch = stack[-1]
            active = parent and not true_branch
            # Only a plain else is guaranteed to require a negated trace flag.
            if kind == 'elif':
                stack[-1] = (parent, False, true_branch)
        elif kind == 'endif' and stack:
            active = stack.pop()[0]
        if not active:
            skipped.update(range(start, end + 1))
        cursor = end + 1
    if not active:
        skipped.update(range(cursor, len(source.splitlines()) + 1))
    return skipped


def lint_source(source, path):
    skipped = trace_lines(source)
    # A literal header name is a preprocessing token, not an identifier use.
    # Macro-valued includes still pass through the identifier checks below.
    for start, end, directive in directives(source):
        words = [t.text for t in lex(directive)]
        if words[:3] == ['#', 'include', '<'] and words[-1:] == ['>']:
            skipped.update(range(start, end + 1))
    tokens = [t for t in lex(source) if t.line not in skipped]
    errors = []
    for token in tokens:
        if token.kind != 'literal' and (token.text in FORBIDDEN or token.text.startswith(SENTINEL)):
            errors.append(f'{path}:{token.line}: forbidden {token.text}')
    for start, end, directive in directives(source):
        if start in skipped:
            continue
        words = [t.text for t in lex(directive)]
        if len(words) < 2:
            continue
        if words[1] == 'line' or words[1].isdigit():
            errors.append(f'{path}:{start}: forbidden #line')
        if words[1] != 'define':
            continue
        # Condition stringification is compile-time input to the stable hash.
        # Assembly operand labels are source names but never emitted as text.
        if words[2:3] in (['TOMO_ASSERT'], ['TOMO_ASSERT_SALT']) and str(path).endswith('src/base/tomo_assert.h'):
            continue
        depth, asm_depth = 0, None
        previous = ''
        for word in words[3:]:
            if word == '(':
                depth += 1
                if previous in ('asm', '__asm__', 'goto', 'volatile') and any(w in words for w in ('asm', '__asm__')):
                    asm_depth = depth
            elif word == ')':
                if depth == asm_depth:
                    asm_depth = None
                depth -= 1
            elif word in ('#', '%:') and asm_depth is None:
                errors.append(f'{path}:{start}: identifier stringification outside an asm template')
            previous = word
    return errors


def source_check(root):
    errors = []
    for path in production_paths(root):
        errors.extend(lint_source(path.read_text(), path.relative_to(root)))
    return errors


def expanded_check(root, source, cxx, flags, db0):
    defines = [f'-D{name}={SENTINEL}{name.strip("_")}' for name in BUILTINS]
    variant = ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else []
    command = shlex.split(cxx) + shlex.split(flags) + ['-I.', '-E', '-Wno-builtin-macro-redefined'] + defines + variant + [source]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True)
    if result.returncode:
        return [f'{source} (db0={db0}): preprocessor failed\n{result.stderr}']
    # Tokens may wrap lines. Gather contiguous in-tree output so source_location
    # and split constructs receive the same lexer treatment as source code.
    errors, current, number, block, block_start = [], '', 1, [], 1
    local = False

    def flush():
        if not block:
            return
        for token in lex('\n'.join(block)):
            if token.kind != 'literal' and (token.text in FORBIDDEN or token.text.startswith(SENTINEL)):
                errors.append(f'{current}:{block_start + token.line - 1}: expanded forbidden {token.text} (db0={db0})')
        block.clear()

    for line in result.stdout.splitlines():
        marker = re.match(r'^# (\d+) "([^"]+)"', line)
        if marker:
            flush()
            number, current = int(marker[1]), marker[2]
            local = not current.startswith('<') and any(
                (root / current).resolve().is_relative_to(root / directory)
                for directory in ('src', 'third_party/lua/helpers'))
            continue
        if local:
            if not block:
                block_start = number
            block.append(line)
        number += 1
    flush()
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--cxx', default='g++')
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--flags', default='-std=c++20 -O2')
    parser.add_argument('--sources', nargs='*', default=[])
    parser.add_argument('--c-sources', nargs='*', default=[])
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args()
    root = args.root.resolve()
    errors = source_check(root)
    if (args.sources or args.c_sources) and not errors:
        tasks = [(source, args.cxx, args.flags, db0) for source in args.sources for db0 in (False, True)]
        cflags = shlex.join([f for f in shlex.split(args.flags) if not f.startswith('-std=')]
                           + ['-std=c11', '-DENABLE_CJSON_GLOBAL', '-Ithird_party/lua'])
        tasks += [(source, args.cc, cflags, False) for source in args.c_sources]
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            results = pool.map(lambda task: expanded_check(root, *task), tasks)
            for result in results:
                errors.extend(result)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'PASS source identity lint ({len(args.sources)} C++ TUs, both database variants; {len(args.c_sources)} shared C TUs)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
