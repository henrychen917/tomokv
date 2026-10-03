#!/usr/bin/env python3
"""Compare CONFIGURATION.md's knob rows with the boot parser, without a server.

Every documented spelling occupies its own row starting with | `name` |.
The source set includes CLI directives and all EncodingConfig aliases. --help is
an action, not a setting; the file-only `pin` translation is documented in prose.
This checks names, not defaults, grammar, mutability, INFO, or runtime behavior.
"""

import argparse
from collections import Counter
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ASSERTION = "knob set matches parser"


def without_comments(source):
    # Preserve quoted C++ strings/characters; help text and comments are not a
    # substitute for a branch that actually recognizes a flag.
    tokens = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/'
    return re.sub(tokens, lambda m: " " if m[0].startswith(("//", "/*")) else m[0],
                  source, flags=re.S)


def between(text, start, end):
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError(f"source shape changed: expected unique {start!r} and {end!r}")
    return text.split(start, 1)[1].split(end, 1)[0]


def parser_knobs(source):
    source = without_comments(source)
    parser = between(source, "inline int parse_config_args(", "inline int validate_config(")
    flags = set(re.findall(r'std::strcmp\s*\(\s*a\s*,\s*"--([a-z0-9-]+)"\s*\)', parser))
    if "help" not in flags or "EncodingConfig::find" not in parser:
        raise ValueError("source shape changed: missing help branch or encoding dispatch")
    flags.remove("help")
    table = between(source, "static constexpr Setting settings[Count] = {", "int64_t values[Count]")
    spelling = r'("[a-z0-9-]+"|nullptr)'
    rows = re.findall(r'\{\s*"([a-z0-9-]+)"\s*,\s*' + spelling +
                      r'\s*,\s*(?:true|false)\s*,\s*' + spelling + r'\s*\}', table)
    if not flags or not rows or len(rows) != table.count("{"):
        raise ValueError("source shape changed: empty or unrecognized knob table")
    for canonical, alias, legacy in rows:
        flags.add(canonical)
        flags.update(name.strip('"') for name in (alias, legacy) if name != "nullptr")
    return flags


def documented_knobs(document):
    names = re.findall(r'^\|\s*`([a-z0-9-]+)`\s*\|', document, re.M)
    if not names:
        raise ValueError("no documented knob rows")
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise ValueError("duplicate documented knobs: " + ", ".join(duplicates))
    return set(names)


def check(header, document):
    parsed = parser_knobs(header.read_text())
    documented = documented_knobs(document.read_text())
    errors = []
    if parsed - documented:
        errors.append("parsed but undocumented: " + ", ".join(sorted(parsed - documented)))
    if documented - parsed:
        errors.append("documented but not parsed: " + ", ".join(sorted(documented - parsed)))
    if errors:
        raise ValueError("; ".join(errors))
    return len(parsed)


def self_test(header, document):
    """Exercise the CLI against throwaway copies; never modify the checkout."""
    source, markdown = header.read_text(), document.read_text()
    with tempfile.TemporaryDirectory(prefix="tomokv-docs-drift-") as directory:
        copy_header = Path(directory) / "config.h"
        copy_document = Path(directory) / "CONFIGURATION.md"
        cases = [
            ("positive copy", source, markdown, None),
            ("fake documented knob", source,
             markdown + "\n| `docs-drift-fake-knob` | T | 0 or 1 | 0 | boot | — | negative control |\n",
             "documented but not parsed: docs-drift-fake-knob"),
            ("missing canonical knob", source,
             re.sub(r'^\| `databases` \|.*\n', '', markdown, flags=re.M),
             "parsed but undocumented: databases"),
            ("missing alias", source,
             re.sub(r'^\| `hash-max-ziplist-entries` \|.*\n', '', markdown, flags=re.M),
             "parsed but undocumented: hash-max-ziplist-entries"),
            ("new parser knob", source.replace('else if (!std::strcmp(a, "--help"))',
             'else if (!std::strcmp(a, "--docs-drift-source-knob")) {}\n'
             '        else if (!std::strcmp(a, "--help"))'), markdown,
             "parsed but undocumented: docs-drift-source-knob"),
            ("duplicate row", source, markdown + "\n| `databases` | duplicate |\n",
             "duplicate documented knobs: databases"),
            ("comment is not a knob", source + '\n// std::strcmp(a, "--comment-only")\n',
             markdown, None),
            ("empty document", source, "", "no documented knob rows"),
        ]
        for name, candidate, doc, failure in cases:
            copy_header.write_text(candidate)
            copy_document.write_text(doc)
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "--config-header", str(copy_header), "--document", str(copy_document)],
                capture_output=True, text=True, check=False)
            if failure is None:
                if result.returncode != 0:
                    raise ValueError(f"self-test {name}: {result.stderr.strip()}")
            elif result.returncode != 1 or f"FAIL {ASSERTION}:" not in result.stderr or failure not in result.stderr:
                raise ValueError(f"self-test {name}: expected named failure {failure!r}, got {result}")
            print(f"PASS self-test {name}" + (f": {result.stderr.strip()}" if failure else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-header", type=Path, default=ROOT / "src/core/config.h")
    parser.add_argument("--document", type=Path, default=ROOT / "docs/CONFIGURATION.md")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        count = check(args.config_header, args.document)
        print(f"PASS {ASSERTION}: {count} spellings")
        if args.self_test:
            self_test(args.config_header, args.document)
    except (OSError, ValueError) as error:
        print(f"FAIL {ASSERTION}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
