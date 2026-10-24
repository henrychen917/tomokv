#!/usr/bin/env python3
"""Bounded serverless paths in linked production routines, no rates.

Count named tomo routines (including inlined code), exclude out-of-scope library
callees and fixture glue. EMPTY instantiates the real sweep from each arm header.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/execfair/instructions"
BUILD = ROOT / "build/execfair-instructions"
OUT.mkdir(exist_ok=True)
BUILD.mkdir(exist_ok=True)
ARMS = {"pre": (ROOT / "build/pre-source", ROOT / "build/pre"),
        "post": (ROOT, ROOT / "build")}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def build(arm, ns):
    source, objects = ARMS[arm]
    dest = BUILD / (arm + "-" + ns)
    dest.mkdir(exist_ok=True)
    recipe = subprocess.check_output(["make", "-C", str(source), "BUILD_ROOT=" + str(objects),
                                     "-n", "-W", str(objects / "src/main.o"), "all"], text=True)
    link = shlex.split(next(line for line in recipe.splitlines() if " -o " + str(objects / "tomokv") + " " in line))
    flags = ["g++", "-std=c++20", "-O2", "-g", "-march=native", "-pthread", "-DTOMO_JEMALLOC", "-I" + str(source)]
    if ns == "db0":
        flags += ["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"]
    compile_cmd = flags + ["-c", str(Path(__file__).with_name("probe.cc")), "-o", str(dest / "probe.o")]
    link = [str(dest / "probe.o") if arg == str(objects / "src/main.o") else arg
            for arg in link if arg != str(objects / "db0/src/main.o")]
    link[link.index("-o") + 1] = str(dest / "probe")
    with (OUT / (arm + "-" + ns + "-build.log")).open("w") as log:
        subprocess.run(compile_cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(link, stdout=log, stderr=subprocess.STDOUT, check=True)
    save(OUT / (arm + "-" + ns + "-build.json"), {"compile": compile_cmd, "link": link,
         "sha256": hashlib.sha256((dest / "probe").read_bytes()).hexdigest()})


def trace(case):
    arm, ns, command, mode, batch = case
    binary = BUILD / (arm + "-" + ns) / "probe"
    label = "-".join(map(str, case))
    symbols = []
    for line in subprocess.check_output(["nm", "-S", "--defined-only", str(binary)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[2] in ("t", "T", "W", "w"):
            symbols.append([int(fields[0], 16), int(fields[0], 16) + int(fields[1], 16), fields[3]])
    names = subprocess.check_output(["c++filt"], input="\n".join(row[2] for row in symbols), text=True).splitlines()
    prefix = "tomo::" if ns == "normal" else "tomo_db0::"
    ranges = [row + [name] for row, name in zip(symbols, names) if prefix in name]
    ranges_file = BUILD / (label + "-ranges.json")
    save(ranges_file, ranges)
    anchor = next(row[0] for row in symbols if row[2] == "_Z20execfair_trace_beginv")
    output = OUT / (label + ".json")
    script = f"""set pagination off
set confirm off
set auto-load off
set print thread-events off
set disable-randomization on
python
import gdb,json,bisect,re
from collections import Counter
ranges=json.load(open({str(ranges_file)!r}));ranges.sort()
start=gdb.Breakpoint('execfair_trace_begin');end=gdb.Breakpoint('execfair_trace_end')
gdb.execute('run {command} {mode} {batch}',to_string=True)
delta=int(gdb.parse_and_eval('(void*)&execfair_trace_begin'))-{anchor}
for r in ranges:r[0]+=delta;r[1]+=delta
starts=[r[0] for r in ranges]
def at(pc):
 i=bisect.bisect_right(starts,pc)-1
 return ranges[i] if i>=0 and pc<ranges[i][1] else None
end_pc=int(gdb.parse_and_eval('(void*)&execfair_trace_end'))
start.delete();gdb.execute('finish',to_string=True)
counts=Counter();excluded=Counter();arch=gdb.selected_frame().architecture()
for step in range(1000000):
 pc=int(gdb.parse_and_eval('$pc'))
 if pc==end_pc:break
 fn=at(pc);ins=arch.disassemble(pc,count=1)[0]['asm']
 if fn:counts[fn[3]]+=1
 if ins.startswith('call'):
  direct=re.search(r'0x[0-9a-f]+',ins) if '*' not in ins else None
  if direct and not at(int(direct[0],16)):
   if fn:excluded[ins.split('<')[-1].rstrip('>')]+=1
   gdb.execute('nexti',to_string=True)
  else:
   gdb.execute('stepi',to_string=True)
   target=int(gdb.parse_and_eval('$pc'))
   if not at(target):
    if fn:excluded[gdb.execute('info symbol '+hex(target),to_string=True).strip()]+=1
    gdb.execute('finish',to_string=True)
 else:gdb.execute('stepi',to_string=True)
else:raise RuntimeError('bounded instruction trace exhausted')
assert sum(counts.values()) > 0, 'named production scope did not fire'
json.dump(dict(total=sum(counts.values()),functions=dict(counts),excluded=dict(excluded)),open({str(output)!r},'w'),indent=2)
end.delete();gdb.execute('continue',to_string=True)
assert int(gdb.parse_and_eval('$_exitcode'))==0,'fixture exact-data assertion failed'
print('COUNT',sum(counts.values()))
end
"""
    script_file = BUILD / (label + ".gdb")
    script_file.write_text(script)
    cmd = ["taskset", "-c", "72-79", "gdb", "-nx", "-batch", "-x", str(script_file), str(binary)]
    with (OUT / (label + ".log")).open("w") as log:
        result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=300)
    assert result.returncode == 0 and output.exists(), label
    row = dict(zip(("arm", "namespace", "command", "mode", "batch"), case))
    row.update(json.loads(output.read_text()))
    print(label, row["total"], flush=True)
    return row


def main():
    p = argparse.ArgumentParser();p.add_argument("--build-only", action="store_true")
    p.add_argument("--trace-only", action="store_true");p.add_argument("--arms", default="pre,post")
    a = p.parse_args();arms=a.arms.split(",")
    if not a.trace_only:
        for arm in arms:
            for ns in ("normal", "db0"):
                build(arm, ns)
    if a.build_only:
        return
    cases = [(arm, ns, command, mode, batch) for arm in arms for ns in ("normal", "db0")
             for command in ("GET", "SET", "INCR", "EMPTY") for mode in ("1s", "2s")
             for batch in ((1,) if command == "EMPTY" else (1, 32))]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(trace, cases))
    save(OUT / "results.json", rows)
    pairs=[]
    for row in rows:
        if row["arm"] != "post":continue
        old=next(r for r in rows if r["arm"]=="pre" and all(r[k]==row[k] for k in ("namespace","command","mode","batch")))
        pairs.append({k:row[k] for k in ("namespace","command","mode","batch")} | {
            "pre":old["total"],"post":row["total"],"delta":row["total"]-old["total"],
            "functions_equal":old["functions"]==row["functions"]})
    save(OUT / "comparison.json", pairs)


if __name__ == "__main__":main()
