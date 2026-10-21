#!/usr/bin/env python3
"""Capture every tlsboot call's argv before/after ntfix5 without opening sockets."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASE = "8ae8e65e5"


def helper(source):
    return source[source.index("tlsboot(){"):].split("\n}", 1)[0] + "\n}\n"


def calls(source):
    lines = source.splitlines()
    result = []
    dynamic = 0
    for i, line in enumerate(lines):
        if line.startswith("tlsboot "):
            statement = line
            j = i
            while statement.rstrip().endswith("\\"):
                j += 1
                statement = statement.rstrip()[:-1] + lines[j].lstrip()
            result.append((f"legacy-{len(result) + 1}", i + 1,
                           statement.split(" ||", 1)[0], False))
        elif line.lstrip().startswith("if ! tlsboot "):
            dynamic += 1
            statement = line.strip()[len("if ! "):].split(" ||", 1)[0]
            for label in (("N2",) if dynamic == 1 else ("N3", "N4")):
                for mode in ("1s", "2s"):
                    for engine in ("uring", "epoll"):
                        shape = "--thread-mode fused --read-local 1" if mode == "1s" else "--thread-mode 2s"
                        invocation = f"engine={engine}; shape=({shape}); {statement}"
                        result.append((f"{label}-{mode}-{engine}", i + 1, invocation, mode == "1s"))
    assert dynamic == 2 and len(result) == 15
    return result


def capture(body, command):
    with tempfile.TemporaryDirectory(dir=ROOT / "build/ntfix5") as directory:
        script = '''
quiet_wait(){ :; }
guard_port(){ :; }
seq(){ :; }
taskset(){ printf '%s\\0' "$@" > "$TMPDIR/argv"; }
CORES=80-87; PORT=22800; TLS_PORT=22801; GATE_RATIO=6:2
CANDIDATE_BINARY="$PWD/build/tomokv"; TLS_DIR="$PWD/build/ntfix5/argv-tls"
''' + body + "\n" + command + '\nwait "$SRV"\n'
        subprocess.run(["bash", "-c", script], cwd=ROOT, check=True, timeout=5,
                       capture_output=True, env=dict(os.environ, TMPDIR=directory))
        return (Path(directory) / "argv").read_bytes()


def main():
    before = subprocess.check_output(["git", "show", f"{BASE}:tests/gate.sh"], cwd=ROOT, text=True)
    after = (ROOT / "tests/gate.sh").read_text()
    # No call, assertion, row, counter, or other gate statement changed.
    assert before.replace(helper(before), "") == after.replace(helper(after), "")
    old_calls, new_calls = calls(before), calls(after)
    rows = []
    listing = ["Serverless argv audit. The taskset command is captured as NUL-delimited bytes.",
               "Both sides use identical fixed paths/ports; no certificate or server is opened.",
               f"BEFORE gate source: {BASE}; AFTER: current tests/gate.sh.", ""]
    for old, new in zip(old_calls, new_calls):
        label, old_line, command, fused = old
        assert (old[0], old[2], old[3]) == (new[0], new[2], new[3])
        pre, post = capture(helper(before), command), capture(helper(after), command)
        pre_argv, post_argv = [data.decode().split("\0")[:-1] for data in (pre, post)]
        expected = pre_argv.copy()
        if fused:
            index = expected.index("--ratio")
            assert expected[index:index + 2] == ["--ratio", "6:2"]
            del expected[index:index + 2]
        assert post_argv == expected
        assert (pre == post) == (not fused)
        rows.append(dict(call=label, before_line=old_line, after_line=new[1],
                         invocation=command, before=["taskset", *pre_argv],
                         after=["taskset", *post_argv], identical_bytes=pre == post,
                         before_nul_sha256=hashlib.sha256(pre).hexdigest(),
                         after_nul_sha256=hashlib.sha256(post).hexdigest()))
        listing += [f"{label} (lines {old_line} -> {new[1]}): " +
                    ("only --ratio 6:2 removed" if fused else "BYTE-IDENTICAL"),
                    "BEFORE " + shlex.join(["taskset", *pre_argv]),
                    "AFTER  " + shlex.join(["taskset", *post_argv]), ""]
    result = dict(baseline=BASE, gate_outside_tlsboot_identical=True,
                  unchanged_calls=9, fused_calls_ratio_pair_removed=6, calls=rows)
    (OUT / "argv-before-after.json").write_text(json.dumps(result, indent=2) + "\n")
    (OUT / "argv-before-after.txt").write_text("\n".join(listing))
    print("PASS: all 15 tlsboot invocations captured; 9 byte-identical; 6 fused calls lose only --ratio 6:2")


if __name__ == "__main__":
    main()
