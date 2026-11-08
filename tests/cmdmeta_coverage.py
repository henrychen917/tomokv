#!/usr/bin/env python3
"""Registry coverage, orphan rejection and offline command metadata drift check.

`command_metadata_init` refuses to build its index when a registered command has no generated row,
and a registry that fails to initialise means the server does not boot AT ALL -- every gate row goes
red at once and none of them says which command is missing. That is exactly how PFDEBUG landed: the
lane that added `src/cmd/pfdebug.cc` had no reason to know `tools/gen_cmdmeta.py` carries a
hand-maintained COMMAND_SOURCES list, so the table silently fell one command behind the registry and
the two only met when the branches merged.

This check is static -- no server or build. The drift check reads pinned Redis 7.4.10 JSON.
"""

import argparse
import ast
import source_tokens as cpp
import difflib
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
GENERATED = REPO / "src/cmd/cmdmeta_generated.inc"
GENERATOR = REPO / "tools/gen_cmdmeta.py"


def registered_commands():
    """Command names from every CommandSpec table in the tree, keyed by the file declaring them."""
    found = {}
    for source in sorted((REPO / "src/cmd").glob("*.cc")):
        text = source.read_text()
        if not cpp.search(r'static const CommandSpec \w+\[\]', text):
            continue
        for name in cpp.command_names(text):
            if name in found:
                raise ValueError('duplicate registered command: ' + name)
            found[name] = source.relative_to(REPO).as_posix()
    if not found:
        raise ValueError('empty command registry')
    return found


def generated_rows():
    text = cpp.compact(cpp.read(GENERATED))
    block = text[text.index("kGeneratedMetadata[]={"):]
    return {name.upper() for name in re.findall(r'\{\s*"([A-Za-z][A-Za-z0-9_|-]*)"', block)}


def generator_sources():
    tree = ast.parse(GENERATOR.read_text())
    values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'COMMAND_SOURCES' for t in node.targets)]
    if len(values) != 1 or not values[0]:
        raise ValueError('missing or ambiguous generator source manifest')
    return set(values[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-root", type=pathlib.Path,
                        default=os.environ.get("REDIS74_ROOT", "/tmp/claude-1000/redis74"))
    args = parser.parse_args()
    registered = registered_commands()
    rows = generated_rows()
    sources = generator_sources()
    failures = []

    missing = sorted(name for name in registered if name not in rows)
    for name in missing:
        failures.append(f"{name} (registered in {registered[name]}) has no cmdmeta_generated.inc row"
                        f" -- the server will refuse to boot")

    for name in sorted(rows):
        if name.split("|", 1)[0] not in registered:
            failures.append(f"{name} has no registered top-level command")

    # The generator only scans files it is told about, so a table it never reads is the upstream
    # cause of the row above. Report it separately: it is the thing an operator has to FIX, whereas
    # the missing row is only the symptom.
    unscanned = sorted({path for path in registered.values() if path not in sources})
    for path in unscanned:
        failures.append(f"{path} declares commands but is absent from COMMAND_SOURCES in"
                        f" tools/gen_cmdmeta.py -- regenerating would drop them")

    sys.path.insert(0, str(REPO / "tools"))
    from gen_cmdmeta import generated_text
    try:
        expected = generated_text(REPO, redis_root=args.redis_root)
        actual = GENERATED.read_text()
        if cpp.tokens(actual) != cpp.tokens(expected):
            failures.append("cmdmeta_generated.inc differs from pinned Redis JSON + registry")
            sys.stderr.writelines(difflib.unified_diff(
                actual.splitlines(True), expected.splitlines(True),
                fromfile=str(GENERATED), tofile="regenerated metadata"))
    except (OSError, ValueError) as error:
        failures.append(f"cannot regenerate metadata: {error}")

    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        for line in failures:
            print(f"  {line}")
        return 1

    print(f"ok: {len(registered)} registered commands, all present in {len(rows)} generated rows;"
          f" {len(sources)} generator sources cover every CommandSpec table;"
          " no orphans; offline regeneration byte-identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
