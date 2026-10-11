#!/usr/bin/env python3
"""Replay txnfix3's serverless production-object instruction fixtures.

Only named functions are stepped into. These are bounded path checks, not a
throughput measurement or whole-operation instruction counts. No listener or
worker is started. Every child inherits a CPU set within 48-63.
"""
import argparse
import collections
import concurrent.futures
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "docs/txnfix/txnfix3"
OUT = ROOT / "docs/txnorder/paths-final"
BUILD = ROOT / "build/txnorder/paths-final"
FAMILIES = {
    "atomic": (str(ROOT / "docs/txnorder/proof-drivers/probe-atomic.cc"), ["MSET"]),
    "mget": ("probe-matrix.cc", ["missing", "present"]),
    "prepare": ("probe-prepare.cc", "MGET MSET MSETNX DEL UNLINK EXISTS SINTER SUNION SDIFF SINTERCARD SINTERSTORE SUNIONSTORE SDIFFSTORE RENAME RENAMENX COPY SMOVE RPOPLPUSH LMOVE LMPOP ZMPOP ZUNION ZINTER ZDIFF ZINTERCARD ZUNIONSTORE ZINTERSTORE ZDIFFSTORE PFCOUNT PFMERGE BITOP ZRANGESTORE LCS TOUCH SORT SORTDEREF GEORADIUS GEORADIUSBYMEMBER GEOSEARCHSTORE XREAD KEYS RANDOMKEY FLUSHDB FLUSHALL".split()),
    "stream": ("probe-prepare-stream.cc", ["XREADGROUP"]),
    "read": ("probe-read.cc", "MGET MSET DEL UNLINK EXISTS SINTER SUNION SDIFF SINTERCARD ZUNION ZINTER ZDIFF ZINTERCARD PFCOUNT LCS TOUCH XREAD".split()),
    "scan": ("probe-scan.cc", ["KEYS", "RANDOMKEY"]),
}


def scan_helpers():
    """The skipped scan loop is admissible only with exact body identity."""
    sys.path.insert(0, str(ROOT / "tools"))
    from ccfix_audit import audit
    rows = []
    for prefix in ("src", "db0/src"):
        old = audit.Elf(ROOT / "build/txnorder/pre" / prefix / "cmd/xshard.o")
        new = audit.Elf(ROOT / "build" / prefix / "cmd/xshard.o")
        before, after = old.functions(), new.functions()
        symbols = sorted(before.keys() | after.keys())
        names = subprocess.check_output(["c++filt"], input="\n".join(symbols), text=True).splitlines()
        selected = [(s, n) for s, n in zip(symbols, names)
                    if "FlatStore::scan_home<" in n and "xshard_execute" in n]
        assert selected, prefix
        for symbol, name in selected:
            a, b = before.get(symbol), after.get(symbol)
            equal = bool(a and b and old.canonical(a) == new.canonical(b))
            rows.append(dict(object=prefix + "/cmd/xshard.o", symbol=symbol,
                             name=name, equal=equal))
    save(OUT / "identical-skipped-scan-helpers.json", rows)
    assert all(row["equal"] for row in rows), "skipped scan helper changed"


def inputs():
    files = [ROOT / "build/tomokv", ROOT / "build/txnorder/pre/tomokv"]
    for base in (ROOT / "build", ROOT / "build/txnorder/pre"):
        for prefix in ("src", "db0/src"):
            files.extend((base / prefix).rglob("*.o"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def build(case):
    family, arm, ns = case
    folder = BUILD / family / (arm + "-" + ns)
    folder.mkdir(parents=True, exist_ok=True)
    receipt = OUT / family
    receipt.mkdir(parents=True, exist_ok=True)
    include = ROOT / ("build/txnorder/pre-source" if arm == "pre" else ".")
    command = ["taskset", "-c", "48-63", "g++", "-std=c++20", "-O2", "-g",
               "-march=native", "-pthread", "-DTOMO_JEMALLOC", "-I" + str(include)]
    if ns == "db0":
        command += ["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"]
    source = OLD / "scatter-trace" / FAMILIES[family][0]
    command += ["-c", str(source), "-o", str(folder / "probe.o")]
    # Reuse the historical fixture's production-object link order. It includes
    # both namespaces; only the probe TU selects which one it calls.
    recipe = json.loads((OLD / "scatter-trace/build.json").read_text())[1]["link"]
    link = []
    for arg in recipe:
        if arg == "112-127":
            arg = "48-63"
        elif arg.endswith("/probe.o"):
            arg = str(folder / "probe.o")
        elif arg.startswith("build/") and arg.endswith(".o"):
            arg = str(ROOT / ("build/txnorder/pre" if arm == "pre" else "build") / arg[6:])
        link.append(arg)
    link[link.index("-o") + 1] = str(folder / "probe")
    with (receipt / (arm + "-" + ns + "-build.log")).open("w") as log:
        compile_exit = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT).returncode
        link_exit = None if compile_exit else subprocess.run(link, stdout=log, stderr=subprocess.STDOUT).returncode
    row = dict(family=family, arm=arm, namespace=ns, compile=command, compile_exit=compile_exit,
               link=link, link_exit=link_exit, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    save(receipt / (arm + "-" + ns + "-build.json"), row)
    assert compile_exit == link_exit == 0, row
    return row


def trace(case):
    family, arm, ns, mode, values = case
    folder = OUT / family
    label = "-".join(case[1:])
    binary = BUILD / family / (arm + "-" + ns) / "probe"
    records = []
    for line in subprocess.check_output(["nm", "-S", "--defined-only", str(binary)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[2] in ("t", "T", "W", "w"):
            records.append([int(fields[0], 16), int(fields[0], 16) + int(fields[1], 16), fields[3]])
    names = subprocess.check_output(["c++filt"], input="\n".join(r[2] for r in records), text=True).splitlines()
    prefix = "tomo::" if ns == "normal" else "tomo_db0::"
    selected = [[*r, n] for r, n in zip(records, names) if prefix in n and
                any(word in n for word in ("xshard_", "txn_group_", "Scatter", "free_state_", "finish_phase", "assemble_final"))]
    if family == "scan":
        selected = [r for r in selected if "FlatStore::scan_home<" not in r[-1]]
    ranges = folder / (label + "-ranges.json")
    save(ranges, selected)
    trace_file = folder / (label + "-trace.json")
    anchor = next(r[0] for r in records if r[2] == "_Z19scatter_trace_beginv")
    args = mode + " " + values if family == "mget" else values + " " + mode
    script = (Path(__file__).with_name("paths.gdb.in")).read_text()
    for key, value in dict(RANGES_FILE=repr(str(ranges)), TRACE_FILE=repr(str(trace_file)),
                           RUN_COMMAND=repr("run " + args), ANCHOR=str(anchor),
                           STEP_LIMIT="300000" if family == "scan" else "20000").items():
        script = script.replace(key, value)
    path = BUILD / family / (label + ".gdb")
    path.write_text(script)
    command = ["taskset", "-c", "48-55", "gdb", "-batch", "-x", str(path), str(binary)]
    log_path = folder / (label + ".log")
    with log_path.open("w") as log:
        try:
            rc = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=300).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    completed = "PASS linked production" in log_path.read_text()
    counts = collections.Counter(r["function"] for r in json.loads(trace_file.read_text())) if trace_file.exists() else {}
    row = dict(arm=arm, namespace=ns, mode=mode, values=values, command=command,
               exit_code=rc or (0 if completed else 1), fixture_completed=completed,
               binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), counts=dict(counts))
    save(folder / (label + "-result.json"), row)
    # Preserve every instruction, including NOPs, without committing large raw JSON.
    for artifact in (trace_file, ranges):
        if artifact.exists():
            with gzip.open(str(artifact) + ".gz", "wb") as output:
                output.write(artifact.read_bytes())
            artifact.unlink()
    print(family, label, row["exit_code"], sum(counts.values()), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("families", nargs="+", choices=FAMILIES)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    before = inputs()
    if "scan" in args.families:
        scan_helpers()
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        list(pool.map(build, [(f, a, n) for f in args.families for a in ("pre", "post") for n in ("normal", "db0")]))
    for family in args.families:
        cases = [(family, a, n, m, v) for a in ("pre", "post") for n in ("normal", "db0")
                 for m in ("2s", "1s") for v in FAMILIES[family][1]]
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            rows = list(pool.map(trace, cases))
        save(OUT / family / "runs.json", rows)
        assert all(r["exit_code"] == 0 for r in rows), "fixture failure retained in runs.json"
    after = inputs()
    save(OUT / "inputs.json", dict(sha256=before, stable=before == after))
    assert before == after, "production input changed while tracing"


if __name__ == "__main__":
    main()
