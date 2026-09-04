#!/usr/bin/env python3
"""Read one value from tomokv's schema-1 final shutdown_report line.

Usage: shutdown_report.py LOG present|clean|get PATH
PATH is dot-separated (for example `wb.direct` or `work.dispatched`).  The parser insists the
record is the log's last line, so an early/cached summary or output after teardown cannot pass.
"""

import json
import sys


def fail(message):
    raise SystemExit("shutdown report: " + message)


if len(sys.argv) < 3:
    fail("usage: LOG present|clean|get [PATH]")

path, action = sys.argv[1], sys.argv[2]
with open(path, "rb") as stream:
    lines = stream.read().splitlines()
if not lines:
    fail("empty log")
prefix = b"shutdown_report "
last = lines[-1]
if not last.startswith(prefix):
    fail("last line is not shutdown_report: %r" % last[:160])
try:
    report = json.loads(last[len(prefix):])
except (UnicodeDecodeError, json.JSONDecodeError) as error:
    fail("invalid JSON: %s" % error)
if report.get("schema") != 1:
    fail("unsupported schema %r" % report.get("schema"))

if action == "present":
    raise SystemExit(0)
if action == "clean":
    stuck = report.get("stuck", {})
    wanted = ("live_conns", "rob_not_quiesced", "unsent_bytes_pending")
    dirty = {name: stuck.get(name) for name in wanted if stuck.get(name) != 0}
    if dirty:
        fail("dirty shutdown: %r" % dirty)
    raise SystemExit(0)
if action != "get" or len(sys.argv) != 4:
    fail("usage: LOG present|clean|get [PATH]")

value = report
for component in sys.argv[3].split("."):
    if not isinstance(value, dict) or component not in value:
        fail("missing field %s" % sys.argv[3])
    value = value[component]
if isinstance(value, bool):
    print("1" if value else "0")
elif isinstance(value, (int, float, str)):
    print(value)
else:
    fail("field %s is not scalar" % sys.argv[3])
