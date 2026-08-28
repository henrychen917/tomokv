#!/usr/bin/env python3
"""Every registered command must have a row in the generated cold metadata table.

`command_metadata_init` refuses to build its index when a registered command has no generated row,
and a registry that fails to initialise means the server does not boot AT ALL -- every gate row goes
red at once and none of them says which command is missing. That is exactly how PFDEBUG landed: the
lane that added `src/cmd/pfdebug.cc` had no reason to know `tools/gen_cmdmeta.py` carries a
hand-maintained COMMAND_SOURCES list, so the table silently fell one command behind the registry and
the two only met when the branches merged.

This check is static -- no server, no Redis oracle, no build -- so it fires the moment a command is
added rather than at the next full gate.
"""

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
        table = re.search(r"static const CommandSpec kTable\[\] = \{(.*?)\n\};", text, re.DOTALL)
        if not table:
            continue
        for name in re.findall(r'^\s*\{"([A-Z][A-Z0-9_-]*)"\s*,', table.group(1), re.MULTILINE):
            found[name] = source.relative_to(REPO).as_posix()
    return found


def generated_rows():
    text = GENERATED.read_text()
    block = text[text.index("kGeneratedMetadata[] = {"):]
    return {name.upper() for name in re.findall(r'\{\s*"([A-Za-z][A-Za-z0-9_|-]*)"', block)}


def generator_sources():
    text = GENERATOR.read_text()
    block = re.search(r"COMMAND_SOURCES = \[(.*?)\]", text, re.DOTALL)
    return set(re.findall(r'"([^"]+)"', block.group(1))) if block else set()


def main():
    registered = registered_commands()
    rows = generated_rows()
    sources = generator_sources()
    failures = []

    missing = sorted(name for name in registered if name not in rows)
    for name in missing:
        failures.append(f"{name} (registered in {registered[name]}) has no cmdmeta_generated.inc row"
                        f" -- the server will refuse to boot")

    # The generator only scans files it is told about, so a table it never reads is the upstream
    # cause of the row above. Report it separately: it is the thing an operator has to FIX, whereas
    # the missing row is only the symptom.
    unscanned = sorted({path for path in registered.values() if path not in sources})
    for path in unscanned:
        failures.append(f"{path} declares commands but is absent from COMMAND_SOURCES in"
                        f" tools/gen_cmdmeta.py -- regenerating would drop them")

    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        for line in failures:
            print(f"  {line}")
        return 1

    print(f"ok: {len(registered)} registered commands, all present in {len(rows)} generated rows;"
          f" {len(sources)} generator sources cover every CommandSpec table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
