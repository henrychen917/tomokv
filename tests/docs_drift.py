#!/usr/bin/env python3
"""Compare CONFIGURATION.md's knob rows with the boot parser, without a server.

Every documented spelling occupies its own row starting with | `name` |.
The source set includes CLI directives and all EncodingConfig aliases. --help is
an action, not a setting; the file-only `pin` translation is documented in prose.
This checks names and generated encoding rows/defaults; runtime behavior is separate.
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


def regenerate_writeback(source, document):
    rule = (ROOT / "src/core/wb_rule.h").read_text()
    rows = []
    for name, field, constant, maximum, zero in (
            ("wb-small-pipe", "wb_small_pipe", "kSmallPipe", "64", "half rule, no completion"),
            ("wb-complete-visits", "wb_complete_visits", "kCompleteVisits", "255", "unbounded completion")):
        initial = re.search(r'uint32_t ' + field + r' = ([^;]+);', source)[1]
        default = re.search(r'unsigned ' + constant + r' = (\d+);', rule)[1] if initial == 'wb_rule::' + constant else initial
        line = source[:source.index('uint32_t ' + field)].count('\n') + 1
        rows.append(f"| `{name}` | T | Canonical decimal 0..{maximum} | `{default}` | Boot/GET | `{field}` (Writeback) | 0 = {zero}; measured default, ledger addendum 12; `src/core/config.h:{line}`. |")
        document = re.sub(r'^\| `' + name + r'` \|.*\n', '', document, flags=re.M)
    return re.sub(r'(^\| `wb-policy` \|.*\n)', lambda m: m[1] + '\n'.join(rows) + '\n', document, flags=re.M)


def regenerate_encodings(source, document):
    """Regenerate the encoding rows/defaults/anchors from EncodingConfig, not prose edits."""
    start = source.index("static constexpr Setting settings[Count] = {")
    end = source.index("int64_t values[Count]", start)
    settings = re.findall(r'\{"([a-z0-9-]+)", ("[a-z0-9-]+"|nullptr), (true|false), '
                          r'("[a-z0-9-]+"|nullptr)\}', source[start:end])
    defaults = re.search(r'int64_t values\[Count\] = \{([^}]+)\}', source).group(1).split(",")
    assert len(settings) == len(defaults)
    descriptions = {
        "hash-max-listpack-entries": "Compact hash entry ceiling",
        "hash-max-listpack-value": "Compact hash field/value byte ceiling",
        "list-max-listpack-size": "-1..-5: 4/8/16/32/64 KiB; smaller negatives clamp to 64 KiB; nonnegative count with 8 KiB ceiling, 0 allows one element",
        "set-max-listpack-entries": "Compact string-set entry ceiling",
        "set-max-listpack-value": "Compact string-set element byte ceiling",
        "set-max-intset-entries": "Integer-set entry ceiling; 0 disables intsets; internal cap 1073741824",
        "zset-max-listpack-entries": "Compact sorted-set entry ceiling",
        "zset-max-listpack-value": "Compact sorted-set member byte ceiling",
    }
    rows = []
    for spelling_index in (0, 1, 3):
        for setting, default in zip(settings, defaults):
            name, alias, memory, legacy = setting
            spelling = setting[spelling_index].strip('"')
            if spelling == "nullptr": continue
            is_legacy = spelling_index == 3
            grammar = ("u32 decimal bytes" if memory == "true" else "u32 decimal") if is_legacy else (
                "Canonical signed 32-bit decimal" if name == "list-max-listpack-size" else
                "Memory ≤9223372036854775807" if memory == "true" else
                "Count64, no memory suffix" if name == "set-max-listpack-value" else "Count64")
            description = descriptions[name] if spelling_index == 0 else (
                ("Legacy alias of " if is_legacy else "Alias of ") + name)
            line = source[:source.index('{"' + name + '"', start)].count("\n") + 1
            rows.append(f"| `{spelling}` | {'T' if is_legacy else 'R'} | {grammar} | `{default.strip()}` | Live | — | {description}; `src/core/config.h:{line}`. |")
    first = document.index("| `hash-max-listpack-entries` |"); last = document.index("| `hll-sparse-max-bytes` |", first)
    document = document[:first] + "\n".join(rows) + "\n" + document[last:]
    first = document.index("The seven canonical rows") if "The seven canonical rows" in document else document.index("The encoding rows")
    last = document.index("**Count64**", first)
    document = document[:first] + ("The encoding rows, aliases, defaults, and source anchors below are generated from\n"
        "`EncodingConfig` by `python3 tests/docs_drift.py --write`. The drift guard checks\n"
        "their exact agreement with the source.\n") + document[last:]
    first = document.index("Aliases share canonical CONFIG storage")
    last = document.index("\n## Security,", first)
    document = document[:first] + ("Aliases share canonical CONFIG storage. Integer sets have an independent\n"
        "`set-max-intset-entries` limit. Fresh sets prefer intset, then listpack, then\n"
        "hashtable according to the first member and size hint. An existing intset\n"
        "exceeding its integer ceiling goes directly to hashtable; a non-integer\n"
        "insertion can instead select listpack when both listpack limits fit. Removal\n"
        "does not demote an encoding. All eight defaults match the pinned Redis 7.4.10\n"
        "oracle; its hash entry default is **512**, not 128.\n") + document[last:]
    return regenerate_writeback(source, document)


def check(header, document):
    parsed = parser_knobs(header.read_text())
    documented = documented_knobs(document.read_text())
    errors = []
    if parsed - documented:
        errors.append("parsed but undocumented: " + ", ".join(sorted(parsed - documented)))
    if documented - parsed:
        errors.append("documented but not parsed: " + ", ".join(sorted(documented - parsed)))
    if not errors and regenerate_encodings(header.read_text(), document.read_text()) != document.read_text():
        errors.append("encoding rows/defaults drifted: run python3 tests/docs_drift.py --write")
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
            ("encoding default drift", source,
             re.sub(r'(^\| `set-max-intset-entries` \|.*?)`512`', r'\g<1>`128`', markdown, flags=re.M),
             "encoding rows/defaults drifted"),
            ("writeback default drift", source,
             re.sub(r'(^\| `wb-small-pipe` \|.*?)`16`', r'\g<1>`8`', markdown, flags=re.M),
             "encoding rows/defaults drifted"),
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
    parser.add_argument("--write", action="store_true", help="regenerate encoding and writeback rows from source")
    args = parser.parse_args()
    try:
        if args.write:
            args.document.write_text(regenerate_encodings(args.config_header.read_text(), args.document.read_text()))
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
