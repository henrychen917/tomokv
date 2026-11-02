#!/usr/bin/env python3
"""Bounded serverless paths in linked production routines, no rates.

txnfix4: tools/blockfix4_scope.py with the txnfix4 fixture (adds LMPOP and SMOVE).
Count named tomo routines (including inlined code), exclude out-of-scope library
callees and fixture glue. The fixture calls the linked production exec_batch_prefetched entry
point (single-key commands) or the production scatter/EXEC entry points. Slowlog -1,
read-local 0; MSET, EXEC, LMPOP and SMOVE cover atomic 0 and 1.
"""
import argparse
import concurrent.futures
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/txnfix4/instructions"
BUILD = ROOT / "build/txnfix4/commands"
OUT.mkdir(parents=True, exist_ok=True)
BUILD.mkdir(parents=True, exist_ok=True)
ARMS = {"pre": (ROOT / "build/txnfix4/pre-source", ROOT / "build/txnfix4/pre-source/build"),
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
    compile_cmd = flags + ["-c", str(ROOT / "tests/txnfix4_scope.cc"), "-o", str(dest / "probe.o")]
    # main.o supplies the actual split executor instantiation. Keep both main
    # objects in their production link order and rename only the program entry.
    # Put fixture COMDATs last so production definitions keep precedence.
    renamed_main = dest / "original-main.o"
    rename_cmd = ["objcopy", "--redefine-sym", "main=execfair_original_main",
                  str(objects / "db0/src/main.o"), str(renamed_main)]
    link = [str(renamed_main) if arg == str(objects / "db0/src/main.o") else arg
            for arg in link]
    link += [str(dest / "probe.o")]
    link[link.index("-o") + 1] = str(dest / "probe")
    with (OUT / (arm + "-" + ns + "-build.log")).open("w") as log:
        subprocess.run(compile_cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(rename_cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(link, stdout=log, stderr=subprocess.STDOUT, check=True)
    save(OUT / (arm + "-" + ns + "-build.json"), {"compile": compile_cmd, "rename": rename_cmd, "link": link,
         "sha256": hashlib.sha256((dest / "probe").read_bytes()).hexdigest(),
         "server_sha256": hashlib.sha256((objects / "tomokv").read_bytes()).hexdigest()})


def trace(case):
    arm, ns, command, mode, batch, atomic, threshold = case
    binary = BUILD / (arm + "-" + ns) / "probe"
    binary_sha256 = hashlib.sha256(binary.read_bytes()).hexdigest()
    label = "-".join(map(str, case))
    symbols = []
    for line in subprocess.check_output(["nm", "-S", "--defined-only", str(binary)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[2] in ("t", "T", "W", "w"):
            symbols.append([int(fields[0], 16), int(fields[0], 16) + int(fields[1], 16), fields[3]])
    names = subprocess.check_output(["c++filt"], input="\n".join(row[2] for row in symbols), text=True).splitlines()
    prefix = "tomo::" if ns == "normal" else "tomo_db0::"
    callbacks = command.startswith(("EVAL", "EXEC"))
    ranges = [row + [name] for row, name in zip(symbols, names)
              if ((prefix in name or '::' not in name) if callbacks else
                  prefix in name and "CoreConcurrencyTest::" not in name)]
    ranges_file = BUILD / (label + "-ranges.json")
    save(ranges_file, ranges)
    anchor = next(row[0] for row in symbols if row[2] == "_Z11scope_beginv")
    output = OUT / (label + ".json")
    existing_log = OUT / (label + ".log")
    compressed_log = Path(str(existing_log) + ".gz")
    log_text = existing_log.read_text() if existing_log.exists() else (
        gzip.open(compressed_log, "rt").read() if compressed_log.exists() else "")
    if (output.exists() and "COUNT " in log_text and
            json.loads(output.read_text()).get("trace_version", 1) == (2 if callbacks else 1) and
            json.loads(output.read_text()).get("binary_sha256") == binary_sha256):
        row = dict(zip(("arm", "namespace", "command", "mode", "batch", "atomic", "threshold"), case))
        row.update(json.loads(output.read_text()))
        print(label, row["total"], "cached completed trace", flush=True)
        return row
    script = f"""set pagination off
set confirm off
set auto-load off
set print thread-events off
set disable-randomization on
set print frame-arguments none
python
import gdb,json,bisect,re
from collections import Counter
ranges=json.load(open({str(ranges_file)!r}));ranges.sort()
start=gdb.Breakpoint('scope_begin');end=gdb.Breakpoint('scope_end')
gdb.execute('run {command} {mode} {batch} {atomic} {threshold}',to_string=True)
delta=int(gdb.parse_and_eval('(void*)&scope_begin'))-{anchor}
for r in ranges:r[0]+=delta;r[1]+=delta
starts=[r[0] for r in ranges]
def at(pc):
 i=bisect.bisect_right(starts,pc)-1
 return ranges[i] if i>=0 and pc<ranges[i][1] else None
end_pc=int(gdb.parse_and_eval('(void*)&scope_end'))
start.delete();gdb.execute('finish',to_string=True)
counts=Counter();bodies=Counter();excluded=Counter();clocks=0;arch=gdb.selected_frame().architecture()
for step in range(2000000):
 pc=int(gdb.parse_and_eval('$pc'))
 if pc==end_pc:break
 fn=at(pc);ins=arch.disassemble(pc,count=1)[0]['asm']
 if fn and 'CoreConcurrencyTest::bind(' in fn[3]:
  gdb.execute('finish',to_string=True);continue
 if fn and {prefix!r} in fn[3] and 'CoreConcurrencyTest::' not in fn[3]:
  counts[fn[3]]+=1
  bodies[hex(fn[0]-delta)+' '+fn[3]]+=1
 if ins.startswith('call') and 'clock_gettime' in ins:
  import struct
  clocks+=1;ptr=int(gdb.parse_and_eval('$rsi'))
  gdb.selected_inferior().write_memory(ptr,struct.pack('qq',1000,clocks*1000))
  gdb.execute('set $rax = 0',to_string=True)
  length=arch.disassemble(pc,count=2)[1]['addr']-pc
  gdb.execute('set $pc = '+hex(pc+length),to_string=True)
 elif ins.startswith('call'):
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
if {callbacks!r} and {command!r}.startswith('EVAL'):
 assert any('script_execute(' in name for name in counts),'Lua activation was skipped'
 assert any('redis_generic_command' in name or 'redis_call' in name for name in counts),'Lua callback was skipped'
json.dump(dict(total=sum(counts.values()),functions=dict(counts),bodies=dict(bodies),excluded=dict(excluded),clock_calls=clocks,trace_version={2 if callbacks else 1},binary_sha256={binary_sha256!r}),open({str(output)!r},'w'),indent=2)
end.delete();gdb.execute('continue',to_string=True)
assert int(gdb.parse_and_eval('$_exitcode'))==0,'fixture exact-data assertion failed'
print('COUNT',sum(counts.values()))
end
"""
    script_file = BUILD / (label + ".gdb")
    script_file.write_text(script)
    cmd = ["taskset", "-c", "61-73", "gdb", "-nx", "-batch", "-x", str(script_file), str(binary)]
    full_log = BUILD / (label + ".log")
    with full_log.open("w") as log:
        result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    from collections import deque
    with full_log.open() as log:
        tail = "".join(deque(log, maxlen=20))
    with full_log.open("rb") as log:
        digest = hashlib.file_digest(log, "sha256").hexdigest()
    (OUT / (label + ".log")).write_text(
        f"Full bounded GDB trace: {full_log}\nSHA-256: {digest}\nExit: {result.returncode}\n" + tail)
    assert result.returncode == 0 and output.exists(), label
    full_log.unlink()  # Digest and counts are durable; step traces are superseded.
    row = dict(zip(("arm", "namespace", "command", "mode", "batch", "atomic", "threshold"), case))
    row.update(json.loads(output.read_text()))
    print(label, row["total"], flush=True)
    return row


def main():
    p = argparse.ArgumentParser();p.add_argument("--build-only", action="store_true")
    p.add_argument("--trace-only", action="store_true");p.add_argument("--arms", default="pre,post")
    p.add_argument("--batches", default="1,32")
    p.add_argument("--commands", default="GET,SET,INCR,MGET,MSET,EXEC,EXEC-cross,LMPOP,SMOVE")
    p.add_argument("--namespaces", default="normal,db0")
    p.add_argument("--jobs", type=int, default=4, help="parallel bounded gdb traces")
    p.add_argument("--arm", action="append", default=[],
                   help="extra arm NAME=SOURCE_TREE (objects in SOURCE_TREE/build)")
    p.add_argument("--out", type=Path, default=None,
                   help="receipt directory (default docs/txnfix4/instructions)")
    a = p.parse_args();arms=a.arms.split(",")
    global OUT
    if a.out is not None:
        OUT = a.out.resolve();OUT.mkdir(parents=True, exist_ok=True)
    for spec in a.arm:
        name, tree = spec.split("=", 1)
        ARMS[name] = (Path(tree).resolve(), Path(tree).resolve() / "build")
    if not a.trace_only:
        for arm in arms:
            for ns in a.namespaces.split(','):
                build(arm, ns)
    if a.build_only:
        return
    cases = [(arm, ns, command, mode, batch, atomic, -1) for arm in arms
             for ns in a.namespaces.split(',') for command in a.commands.split(',')
             for mode in ("1s", "2s") for batch in map(int, a.batches.split(','))
             for atomic in ((0, 1) if command in ("MSET", "EXEC", "EXEC-cross", "LMPOP", "SMOVE")
                            else (1,))
             if not (command in ("EVAL", "LMPOP", "SMOVE") and batch != 1)]
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as pool:
        rows = list(pool.map(trace, cases))
    save(OUT / ("results-"+a.arms+".json"), rows)
    if "pre" not in arms or len(arms) < 2: return
    pairs=[]
    for row in rows:
        if row["arm"] == "pre":continue
        old=next(r for r in rows if r["arm"]=="pre" and all(r[k]==row[k] for k in ("namespace","command","mode","batch","atomic","threshold")))
        pairs.append({"arm":row["arm"]} | {k:row[k] for k in ("namespace","command","mode","batch","atomic","threshold")} | {
            "pre":old["total"],"post":row["total"],"delta":row["total"]-old["total"],
            "functions_equal":old["functions"]==row["functions"]})
    save(OUT / ("comparison-" + a.arms + ".json" if a.arms != "pre,post" else "comparison.json"), pairs)


if __name__ == "__main__":main()
