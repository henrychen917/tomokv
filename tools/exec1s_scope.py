#!/usr/bin/env python3
"""Bounded serverless paths in linked production routines, no rates.

Derived from docs/wave6/commands.py, using the wave7 production scope.
Count named tomo routines (including inlined code), exclude out-of-scope library
callees and fixture glue. The fixture calls the linked production exec_batch_prefetched entry point. Atomic 1, slowlog -1, read-local 0.
"""
import argparse
import concurrent.futures
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/exec1s-evidence/instructions"
BUILD = ROOT / "build/exec1s-scopes"
OUT.mkdir(exist_ok=True, parents=True)
BUILD.mkdir(exist_ok=True, parents=True)
ARMS = {arm: (ROOT, ROOT / "build") for arm in ("X5", "POST")}
for _arm in ("PRE", "X0", "X1", "X2", "X3", "X4"):
    _source = ROOT / "build/exec1s" / ("pre-source" if _arm == "PRE" else _arm.lower() + "-current-source")
    ARMS[_arm] = (_source, _source / "build")
# PAD scopes are constructed by exec1s_pad_scope.py from symbol-isolated PRE.
SYMBOL_PREFIXES = {"PAD-A": "exec1s_pre_"}

# Compile-only controls may replace selected production objects before linking.
OBJECT_OVERRIDES = {}
FIXTURE = ROOT / "tests/txnorder_command_scope.cc"

def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def archive_probe(arm, ns):
    dest=BUILD / (arm + "-" + ns)
    if not (dest / "probe").exists():return
    digest=hashlib.sha256((dest / "probe").read_bytes()).hexdigest()
    archived=OUT / ("superseded-" + arm + "-" + ns + "-" + digest[:12])
    archived.mkdir(exist_ok=True)
    target=archived/"probe"
    if target.exists():(dest/"probe").unlink()
    else:(dest/"probe").rename(target)
    for path in OUT.glob(arm + "-" + ns + "-*"):
        if path.is_file():
            target=archived/path.name
            if target.exists():path.unlink()
            else:path.rename(target)


def build(arm, ns):
    assert os.sched_getaffinity(0) <= set(range(80, 96)), "build under taskset -c 80-95"
    source, objects = ARMS[arm]
    if not (objects / "tomokv").exists():
        cmd = ["make", "-C", str(source), "-j16", "all"]
        if arm == "X4":
            cmd += ["CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_EXEC1S_WB"]
        subprocess.run(cmd, check=True)
    dest = BUILD / (arm + "-" + ns)
    dest.mkdir(exist_ok=True)
    # Preserve the prior probe and its receipts before changing the link. A
    # newly written build receipt must never validate counts from an old probe.
    archive_probe(arm, ns)
    recipe = subprocess.check_output(["make", "-C", str(source), "BUILD_ROOT=" + str(objects),
                                     "-n", "-W", str(objects / "src/main.o"), "all"], text=True)
    link = shlex.split(next(line for line in recipe.splitlines() if " -o " + str(objects / "tomokv") + " " in line))
    flags = ["g++", "-std=c++20", "-O2", "-g", "-march=native", "-pthread", "-DTOMO_JEMALLOC", "-I" + str(source)]
    if ns == "db0":
        flags += ["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"]
    compile_cmd = flags + ["-c", str(FIXTURE), "-o", str(dest / "probe.o")]
    # main.o supplies the actual split executor instantiation. Keep both main
    # objects in their production link order and rename only the program entry.
    # Put fixture COMDATs last so production definitions keep precedence.
    renamed_main = dest / "original-main.o"
    rename_cmd = ["objcopy", "--redefine-sym", "main=execfair_original_main",
                  str(objects / "db0/src/main.o"), str(renamed_main)]
    link = [str(renamed_main) if arg == str(objects / "db0/src/main.o") else arg
            for arg in link]
    link = [str(OBJECT_OVERRIDES.get(arg, arg)) for arg in link]
    link += [str(dest / "probe.o")]
    link[link.index("-o") + 1] = str(dest / "probe")
    with (OUT / (arm + "-" + ns + "-build.log")).open("w") as log:
        subprocess.run(compile_cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(rename_cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(link, stdout=log, stderr=subprocess.STDOUT, check=True)
    save(OUT / (arm + "-" + ns + "-build.json"), {"compile": compile_cmd, "rename": rename_cmd, "link": link,
         "sha256": hashlib.sha256((dest / "probe").read_bytes()).hexdigest(),
         "production_binary":str(objects / "tomokv"),
         "production_sha256":hashlib.sha256((objects / "tomokv").read_bytes()).hexdigest()})


def trace(case):
    arm, ns, command, mode, batch, atomic, threshold = case
    binary = BUILD / (arm + "-" + ns) / "probe"
    probe_sha256 = hashlib.sha256(binary.read_bytes()).hexdigest()
    label = "-".join(map(str, case))
    symbols = []
    for line in subprocess.check_output(["nm", "-S", "--defined-only", str(binary)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[2] in ("t", "T", "W", "w"):
            symbols.append([int(fields[0], 16), int(fields[0], 16) + int(fields[1], 16), fields[3]])
    symbol_prefix = SYMBOL_PREFIXES.get(arm, "")
    # objcopy prefixes global definitions, while local production functions keep
    # their original symbols. Count every executed Tomo body in the common image;
    # filtering only prefixed symbols silently omits those local PRE functions.
    names = subprocess.check_output(["c++filt"], input="\n".join(
        row[2][len(symbol_prefix):] if symbol_prefix and row[2].startswith(symbol_prefix)
        else row[2] for row in symbols), text=True).splitlines()
    prefix = "tomo::" if ns == "normal" else "tomo_db0::"
    ranges = [row + [name] for row, name in zip(symbols, names)
              if prefix in name and "CoreConcurrencyTest::" not in name]
    ranges_file = BUILD / (label + "-ranges.json")
    save(ranges_file, ranges)
    begin_name = symbol_prefix + "_Z11scope_beginv" if symbol_prefix else "scope_begin"
    end_name = symbol_prefix + "_Z9scope_endv" if symbol_prefix else "scope_end"
    anchor = next(row[0] for row in symbols if row[2] == symbol_prefix + "_Z11scope_beginv")
    output = OUT / (label + ".json")
    existing_log = OUT / (label + ".log")
    compressed_log = Path(str(existing_log) + ".gz")
    log_text = existing_log.read_text() if existing_log.exists() else (
        gzip.open(compressed_log, "rt").read() if compressed_log.exists() else "")
    if output.exists() and "COUNT " in log_text and json.loads(output.read_text()).get("probe_sha256") == probe_sha256:
        receipt = json.loads((OUT / (arm + "-" + ns + "-build.json")).read_text())
        assert receipt["sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
        row = dict(zip(("arm", "namespace", "command", "mode", "batch", "atomic", "threshold"), case))
        row.update(json.loads(output.read_text()))
        print(label, row["total"], "cached completed trace", flush=True)
        return row
    script = f"""set pagination off
set confirm off
set auto-load off
set print thread-events off
set disable-randomization on
python
import gdb,json,bisect,re
from collections import Counter
ranges=json.load(open({str(ranges_file)!r}));ranges.sort()
start=gdb.Breakpoint({begin_name!r});end=gdb.Breakpoint({end_name!r})
gdb.execute('run {command} {mode} {batch} {atomic} {threshold}',to_string=True)
delta=int(gdb.parse_and_eval('(void*)&{begin_name}'))-{anchor}
for r in ranges:r[0]+=delta;r[1]+=delta
starts=[r[0] for r in ranges]
def at(pc):
 i=bisect.bisect_right(starts,pc)-1
 return ranges[i] if i>=0 and pc<ranges[i][1] else None
end_pc=int(gdb.parse_and_eval('(void*)&{end_name}'))
start.delete();gdb.execute('finish',to_string=True)
counts=Counter();bodies=Counter();excluded=Counter();clocks=0;arch=gdb.selected_frame().architecture()
idle={arm.startswith('IDLE-')!r};window_started=False;window_finished=False;stop_set=False
for step in range(2000000):
 pc=int(gdb.parse_and_eval('$pc'))
 if pc==end_pc:break
 active=True
 if idle:
  iteration=int(gdb.parse_and_eval('*scope_iterations'))
  active=iteration==2
  window_started=window_started or active
  if iteration>=3:
   window_finished=True
   if not stop_set:
    gdb.execute('set *((unsigned char*)scope_stop) = 1',to_string=True);stop_set=True
 fn=at(pc);ins=arch.disassemble(pc,count=1)[0]['asm']
 if fn and active:
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
assert not idle or (window_started and window_finished), 'idle rotation window did not fire'
json.dump(dict(total=sum(counts.values()),functions=dict(counts),bodies=dict(bodies),excluded=dict(excluded),clock_calls=clocks,probe_sha256={probe_sha256!r}),open({str(output)!r},'w'),indent=2)
end.delete();gdb.execute('continue',to_string=True)
assert int(gdb.parse_and_eval('$_exitcode'))==0,'fixture exact-data assertion failed'
print('COUNT',sum(counts.values()))
end
"""
    script_file = BUILD / (label + ".gdb")
    script_file.write_text(script)
    cmd = ["taskset", "-c", "80-95", "gdb", "-nx", "-batch", "-x", str(script_file), str(binary)]
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
    row = dict(zip(("arm", "namespace", "command", "mode", "batch", "atomic", "threshold"), case))
    row.update(json.loads(output.read_text()))
    print(label, row["total"], flush=True)
    return row


def main():
    p = argparse.ArgumentParser();p.add_argument("--build-only", action="store_true")
    p.add_argument("--trace-only", action="store_true");p.add_argument("--arms", default="PRE")
    a = p.parse_args();arms=a.arms.split(",")
    if not a.trace_only:
        for arm in arms:
            for ns in ("normal", "db0"):
                build(arm, ns)
    if a.build_only:
        return
    cases = [(arm, ns, command, mode, batch, atomic, -1) for arm in arms
             for ns in ("normal", "db0") for command in ("GET", "SET", "INCR", "MGET", "MSET")
             for mode in ("1s", "2s") for batch in (1, 32)
             for atomic in ((0, 1) if command == "MSET" else (1,))]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(trace, cases))
    save(OUT / ("results-"+a.arms+".json"), rows)
    if "PRE" in arms:
        comparisons=[]
        for arm in arms:
            if arm == "PRE": continue
            cases=[]
            for row in rows:
                if row['arm'] != arm: continue
                keys=('namespace','command','mode','batch','atomic','threshold')
                old=next(r for r in rows if r['arm']=='PRE' and all(r[k]==row[k] for k in keys))
                cases.append({k:row[k] for k in keys} | dict(pre=old['total'],post=row['total'],
                    delta=row['total']-old['total'],probe_sha256=row['probe_sha256']))
            comparisons.append(dict(arm=arm,cases=cases,case_count=len(cases),
                max_delta=max(r['delta'] for r in cases),passed=len(cases)==48 and all(r['delta']<=0 for r in cases)))
        save(OUT / 'comparison-arms.json', comparisons)
        for item in comparisons:
            print(item['arm'],'PASS' if item['passed'] else 'FAIL',item['case_count'],
                  'cases; max delta',item['max_delta'],flush=True)
    if not {"PRE", "POST"}.issubset(arms): return
    pairs=[]
    for row in rows:
        if row["arm"] != "POST":continue
        old=next(r for r in rows if r["arm"]=="PRE" and all(r[k]==row[k] for k in ("namespace","command","mode","batch","atomic","threshold")))
        pairs.append({k:row[k] for k in ("namespace","command","mode","batch","atomic","threshold")} | {
            "pre":old["total"],"post":row["total"],"delta":row["total"]-old["total"],
            "functions_equal":old["functions"]==row["functions"]})
    save(OUT / "comparison.json", pairs)


if __name__ == "__main__":main()
