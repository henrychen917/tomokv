#!/usr/bin/env python3
"""TEMPORARY diagnostic instrumentation: give every std::abort() in the atomic engine a printed
tag naming its REAL file and line.

scatter_engine.inc carries `#line 34 "src/cmd/xshard.cc"`, so __FILE__/__LINE__ (and every gdb
frame) inside it are remapped into a 60-line file. The tag is computed here, from the real file, and
baked in as a string literal, so it survives the remap.

Usage: tag_aborts.py apply   |   tag_aborts.py revert
"""
import os
import re
import subprocess
import sys

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
FILES = ["src/store/flatstore_atomic.inc", "src/cmd/atomics_glue.inc",
         "src/cmd/scatter_engine.inc", "src/cmd/multi.inc"]
HEADER = "src/store/tomo_abort_tag.h"
SHIM = """// TOMO-ABORT-TAG (temporary diagnostic instrumentation, scratchpad/execfix/tag_aborts.py)
#pragma once
#include <cstdio>
#include <cstdlib>
[[noreturn]] inline void tomo_abort_tag(const char* where) {
    std::fprintf(stderr, "TOMO-ABORT %s\\n", where);
    std::fflush(stderr);
    std::abort();
}
"""
INCLUDERS = ["src/store/flatstore.h", "src/cmd/xshard.cc"]


def apply():
    with open(os.path.join(ROOT, HEADER), "w") as fh:
        fh.write(SHIM)
    for rel in INCLUDERS:
        path = os.path.join(ROOT, rel)
        text = open(path).read()
        if "tomo_abort_tag.h" not in text:
            marker = "#pragma once\n"
            if text.startswith("//") and marker in text:
                text = text.replace(marker, marker + '#include "src/store/tomo_abort_tag.h"\n', 1)
            else:
                text = '#include "src/store/tomo_abort_tag.h"\n' + text
            open(path, "w").write(text)
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        with open(path) as fh:
            lines = fh.readlines()
        out = []
        for i, line in enumerate(lines, 1):
            out.append(line.replace("std::abort()", 'tomo_abort_tag("%s:%d")' % (rel, i)))
        # shim goes after the last leading comment/#line/#pragma block, i.e. just prepend it
        with open(path, "w") as fh:
            fh.writelines(out)
        print("tagged %s" % rel)


def revert():
    subprocess.check_call(["git", "-C", ROOT, "checkout", "--"] + FILES + INCLUDERS)
    try:
        os.unlink(os.path.join(ROOT, HEADER))
    except FileNotFoundError:
        pass
    print("reverted")


if len(sys.argv) < 2 or sys.argv[1] not in ("apply", "revert"):
    print(__doc__)
    sys.exit(2)
(apply if sys.argv[1] == "apply" else revert)()
