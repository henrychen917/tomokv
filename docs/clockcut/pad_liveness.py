#!/usr/bin/env python3
"""Static check that every PAD-A jump lands where the skipped refresh's registers are dead.

pad.py replaces each added `call clock_gettime` with a jump past the millisecond arithmetic,
the cached_now_ms_ store and the maxmemory test. That is behaviour-preserving only if no
register or flag the skipped bytes would have defined (rax/rcx/rdx/rsi and EFLAGS) is read
at the landing point before being redefined. This walks every path from each landing point
inside its containing function (conditional branches both ways, bounded) and fails on any such
read. A call whose argument registers may still hold skipped state is listed for arity review.

usage: pad_liveness.py <pad-a executable> <pad.json>
"""
import json
from pathlib import Path
import re
import subprocess
import sys

FAMILIES = {}
for full, names in {
        "rax": "rax eax ax al ah", "rcx": "rcx ecx cx cl ch", "rdx": "rdx edx dx dl dh",
        "rsi": "rsi esi si sil", "rdi": "rdi edi di dil", "r8": "r8 r8d r8w r8b",
        "r9": "r9 r9d r9w r9b"}.items():
    for name in names.split():
        FAMILIES[name] = full
TRACKED = {"rax", "rcx", "rdx", "rsi", "flags"}
WRITE_ONLY = re.compile(r"(mov|movabs|movz\w*|movs[bwl]\w*|lea|cvt\w*|pop)$")
NO_FLAGS = re.compile(r"(mov\w*|lea|push|pop|nop\w*|j\w+|call|ret|set\w+|cmov\w+|xchg|bswap|"
                      r"endbr64|prefetch\w*|cltq|cqto|cltd|cwtl)$")
FLAG_READERS = re.compile(r"(j(?!mp)\w+|set\w+|cmov\w+|adc|sbb|rcl|rcr)$")
ARGS = {"rdi", "rsi", "rdx", "rcx", "r8", "r9"}


def registers(operand):
    return [FAMILIES[r] for r in re.findall(r"%(\w+)", operand) if r in FAMILIES]


def effects(text):
    """(reads, writes) over the tracked families plus 'flags'."""
    parts = text.split(None, 1)
    mnemonic = parts[0]
    if mnemonic in ("rep", "repz", "repnz", "lock", "notrack", "bnd"):
        return effects(parts[1]) if len(parts) > 1 else (set(), set())
    operands = re.split(r",(?![^()]*\))", parts[1]) if len(parts) > 1 else []
    operands = [o.strip() for o in operands if o.strip() and not o.strip().startswith("#")]
    operands = [o.split("#")[0].strip() for o in operands]
    reads, writes = set(), set()
    if FLAG_READERS.match(mnemonic):
        reads.add("flags")
    if not NO_FLAGS.match(mnemonic):
        writes.add("flags")
    if mnemonic == "call":
        reads |= ARGS
        writes |= {"rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "flags"}
        return reads, writes
    if mnemonic.startswith("ret"):
        return {"rax"}, set()
    if mnemonic in ("cqto", "cltd"):
        return {"rax"}, {"rdx"}
    if mnemonic in ("cltq", "cwtl"):
        return {"rax"}, {"rax"}
    if mnemonic in ("imul", "mul", "imulq", "mulq") and len(operands) == 1:
        return {"rax", *registers(operands[0])}, {"rax", "rdx", "flags"}
    if mnemonic in ("idiv", "div", "idivq", "divq", "idivl", "divl"):
        return {"rax", "rdx", *registers(operands[0])}, {"rax", "rdx", "flags"}
    if not operands:
        return reads, writes
    destination = operands[-1]
    for operand in operands[:-1]:
        reads |= set(registers(operand))
    if "(" in destination or not destination.startswith("%"):
        reads |= set(registers(destination))      # memory operand: address registers are read
        return reads, writes
    family = registers(destination)
    if not family:
        return reads, writes
    name = destination[1:]
    zeroing = mnemonic.startswith(("xor", "sub")) and len(operands) == 2 and \
        operands[0] == operands[1]
    partial = name in ("ax", "al", "ah", "cx", "cl", "ch", "dx", "dl", "dh", "si", "sil") or \
        mnemonic.startswith(("set", "cmov"))
    if mnemonic.startswith(("cmp", "test", "bt")):
        reads |= set(family)
    elif zeroing:
        writes |= set(family)
    elif WRITE_ONLY.match(mnemonic) and not partial:
        writes |= set(family)
    else:
        reads |= set(family)
        writes |= set(family)
    return reads, writes


def main():
    binary, pad = Path(sys.argv[1]), Path(sys.argv[2])
    patches = json.loads(pad.read_text())["patches"]
    code = {}
    order = []
    owner = None
    dump = subprocess.check_output(["objdump", "-dw", "--no-show-raw-insn", str(binary)], text=True)
    for line in dump.splitlines():
        head = re.fullmatch(r"([0-9a-f]+) <(.+)>:", line)
        if head:
            owner = head[2]
            continue
        match = re.match(r"\s*([0-9a-f]+):\s+(.*)", line)
        if match and owner:
            address = int(match[1], 16)
            code[address] = (match[2].strip(), owner)
            order.append(address)
    following = {a: b for a, b in zip(order, order[1:])}
    failures, warnings, checked = [], [], 0
    for patch in patches:
        start, function = patch["target"], patch["function"]
        stack = [(start, frozenset(TRACKED), 0)]
        seen = set()
        while stack:
            at, live, depth = stack.pop()
            if not live or depth > 400 or (at, live) in seen:
                continue
            seen.add((at, live))
            if at not in code or code[at][1] != function:
                continue
            text = code[at][0]
            checked += 1
            reads, writes = effects(text)
            mnemonic = text.split()[0]
            if mnemonic == "call":
                # Argument registers are read only up to the callee's arity: report, then review.
                if live & ARGS:
                    callee = re.search(r"<([^>]+)>", text)
                    warnings.append(dict(patch=hex(patch["address"]), at=hex(at),
                                         callee=callee[1] if callee else text,
                                         live_argument_registers=sorted(live & ARGS)))
                reads = reads - ARGS
            bad = live & reads
            if bad:
                failures.append(dict(patch=hex(patch["address"]), at=hex(at), text=text,
                                     reads=sorted(bad)))
                continue
            live = frozenset(live - writes)
            target = re.search(r"\s([0-9a-f]+) <", text)
            if mnemonic == "jmp":
                if target:
                    stack.append((int(target[1], 16), live, depth + 1))
                elif live:
                    failures.append(dict(patch=hex(patch["address"]), at=hex(at), text=text,
                                         reads=["indirect jump with live skipped state"]))
                continue
            if mnemonic.startswith("ret") or mnemonic in ("ud2", "hlt"):
                continue
            if mnemonic.startswith("j") and target:
                stack.append((int(target[1], 16), live, depth + 1))
            if at in following:
                stack.append((following[at], live, depth + 1))
    report = dict(binary=str(binary), patches=len(patches), instructions_examined=checked,
                  failures=failures, call_argument_warnings=warnings)
    print(json.dumps(report, indent=1))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
