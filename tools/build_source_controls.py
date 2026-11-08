#!/usr/bin/env python3
"""Checked source readers for the Makefile's two small control builds."""
import argparse
from pathlib import Path
import re

import source_tokens as cpp


def climon_mask(source):
    start, opening, end = cpp.function_span(source, 'climon-mask-word')
    signature = cpp.tokens(source[start:opening])
    body = cpp.tokens(source[opening:end])
    if (len(body) != 7 or body[:2] != ('{', 'return') or
            body[3:] != ('>>', '6', ';', '}') or
            signature[-3:] != ('uint32_t', body[2], ')')):
        raise ValueError('climon-mask-word: expected one parameter returned at shift 6')
    # Preserve the marked declaration and its identifier bindings. Only this
    # unique function body implements the deliberately broken one-word mask.
    return source[:opening] + '{ return 0; }' + source[end:]


def prebuild_threshold(source):
    markers = list(re.finditer(r'/\*\s*TOMO_TOOL_ANCHOR\s+l4-prebuild-threshold\s*\*/', source))
    if len(markers) != 1:
        raise ValueError('expected one l4-prebuild-threshold marker')
    code = cpp.tokens(source[markers[0].end():])
    if (len(code) < 6 or code[:2] != ('#', 'define') or
            not re.fullmatch(r'[A-Za-z_]\w*', code[2]) or
            not re.fullmatch(r'[0-9]+', code[3]) or code[4:6] != ('#', 'endif')):
        raise ValueError('l4-prebuild-threshold: expected one integer macro in its guard')
    return code[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('control', choices=('climon-mask', 'prebuild-threshold'))
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    args = parser.parse_args()
    source = cpp.read(args.source)
    if args.control == 'climon-mask':
        if args.output is None or args.output.resolve() == args.source.resolve():
            parser.error('climon-mask requires a separate output path')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(climon_mask(source))
    else:
        if args.output is not None:
            parser.error('prebuild-threshold prints its value')
        print(prebuild_threshold(source))


if __name__ == '__main__':
    main()
