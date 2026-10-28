#!/usr/bin/env python3
"""Function-body identity between the PRE and POST object sets (no server, no rates).

For every object in the production link, disassemble with relocations, drop addresses, normalize
intra-function offsets, hash each function body and compare PRE with POST by symbol. Prints the
changed, padding-only (alignment NOP encoding only), added and removed functions so a review can
see exactly which bodies the source change reached; everything else is the same instruction
stream. Output:
docs/snapfix/identity/functions.json.
"""
import bisect
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ARMS = {'pre': (ROOT / 'build/snapfix/pre-source', ROOT / 'build/snapfix/pre'),
        'post': (ROOT, ROOT / 'build')}
OUT = ROOT / 'docs/snapfix/identity'

HEADER = re.compile(r'^[0-9a-f]+ <(.+)>:$')
ADDR = re.compile(r'^\s*[0-9a-f]+:\s*')
TARGET = re.compile(r'\b[0-9a-f]+ <([^>]+)>')
# Section-relative relocations (string literals, jump tables, cold splits) move with unrelated code;
# compiler clone numbers (.part.N, .isra.N, .constprop.N, .cold.N) are renumbered per translation unit.
SECTION_RELOC = re.compile(r'(R_X86_64_\w+\s+\.[\w.]+)[+-]0x[0-9a-f]+')
CLONE = re.compile(r'\.(part|isra|constprop|cold|lto_priv)\.[0-9]+')
# kvobj.h's zero-byte local label for the type-A PAD twin is numbered by inline-asm instance (%=),
# so any added asm instance earlier in the TU renumbers it. It is a label inside a function, not one.
PAD = re.compile(r'(tomo(?:_db0)?_multidb2_pad_)[0-9]+')
# With -w the relocation is printed on its instruction's line, prefixed by its section offset,
# which moves whenever an earlier function in the object changes size.
RELOC_AT = re.compile(r'\s[0-9a-f]+: (R_X86_64_)')
# Assembler-resolved RIP-relative displacements to named code and per-TU local constant labels
# (.LCn) move or renumber with unrelated code; the target symbol stays in the normalized text.
RIP = re.compile(r'-?0x[0-9a-f]+\(%rip\)')
LOCAL = re.compile(r'\.L(C?)[0-9]+\b')
# Alignment padding: the assembler picks the NOP encoding (nopl/nopw/xchg %ax,%ax/cs nopw ...)
# from the function's offset in its section, which moves when an EARLIER function in the same
# section changes size. NOP_ONLY records functions whose only difference is padding.
NOP = re.compile(r'^(?:data16 |cs |ds )*(?:nop[wl]?|xchg\s+%ax,%ax)\b')
# The fix RENAMES the snapshot drain's two ThreadCtx instantiations (drain_tasks ->
# drain_tasks_capped, drain_tasks_unmasked -> drain_tasks_unmasked_capped; same lambda, LaneCap =
# the snapshot drain's BatchOps). PRE names are mapped first, so the renamed bodies compare with
# their successors and a caller differing only in that call target compares equal.
RENAME = re.compile(r'(_ZN\w*?9ThreadCtx)(11drain_tasks|20drain_tasks_unmasked)ILb([01])E'
                    r'(RZN[\w.]*?drain_tasks_snapshotILj(\d+)E[\w.]*?)OT0_')


def rename(text):
    def sub(m):
        name = '18drain_tasks_capped' if m[2] == '11drain_tasks' else '27drain_tasks_unmasked_capped'
        return f'{m[1]}{name}ILb{m[3]}ELj{m[5]}E{m[4]}OT1_'
    return RENAME.sub(sub, text)


def canon(name):
    return CLONE.sub(lambda m: '.' + m.group(1), name)


def objects(arm):
    source, build = ARMS[arm]
    recipe = subprocess.check_output(['make', '-C', str(source), 'BUILD_ROOT=' + str(build), '-n', '-W',
                                      str(build / 'src/main.o'), 'all'], text=True)
    link = shlex.split(next(line for line in recipe.splitlines() if ' -o ' + str(build / 'tomokv') + ' ' in line))
    return [Path(x) for x in link if x.endswith('.o')]


SELF = re.compile(r'<([^<>]+)\+0x([0-9a-f]+)>')


def strip_padding(name, start, lines, addresses):
    """Drop alignment NOPs; renumber branch targets inside the function by instruction ordinal.

    A NOP of another length moves every later label by the same few bytes, so offsets inside the
    function are replaced by the ordinal of the first non-padding instruction at or after them."""
    ordinal, kept = {}, 0
    for line, address in zip(lines, addresses):
        if address is None:
            continue
        ordinal.setdefault(address, kept)
        if not NOP.match(line):
            kept += 1
    positions = sorted(ordinal)

    def target(m):
        if m.group(1) != name:
            return m.group(0)
        address = start + int(m.group(2), 16)
        i = bisect.bisect_left(positions, address)
        return f'<{name}+#{ordinal[positions[i]] if i < len(positions) else kept}>'

    out = []
    for line in lines:
        if NOP.match(line):
            if not out or out[-1] != 'padding':
                out.append('padding')
            continue
        out.append(SELF.sub(target, line))
    return out


def bodies(path, pre=False, padding=True):
    text = subprocess.check_output(['objdump', '-dr', '--no-show-raw-insn', '-w', str(path)], text=True,
                                   errors='replace')
    if pre:
        text = rename(text)
    out, name, lines, addresses, start = {}, None, [], [], 0

    def close():
        if name is not None:
            text = lines if padding else strip_padding(name, start, lines, addresses)
            out[name] = hashlib.sha256('\n'.join(text).encode()).hexdigest()

    for line in text.splitlines():
        head = HEADER.match(line)
        if head and PAD.fullmatch(head.group(1)):
            lines.append('pad-label')
            addresses.append(None)
            continue
        if head:
            close()
            name, lines, addresses = canon(head.group(1)), [], []
            start = int(line.split(' ', 1)[0], 16)
            continue
        if name is None or not line.strip() or line.startswith('Disassembly of section'):
            continue
        at = re.match(r'\s*([0-9a-f]+):', line)
        addresses.append(int(at.group(1), 16) if at else None)
        body = ADDR.sub('', line)
        body = RELOC_AT.sub(lambda m: ' ' + m.group(1), body)
        # A relocated field is still zero in the object, so objdump's <symbol+offset> annotation
        # for it names whatever follows the instruction (often the NEXT function in the section,
        # which moves with unrelated code). The relocation names the real target; keep only it.
        if ' R_X86_64_' in body:
            insn, reloc = body.split(' R_X86_64_', 1)
            body = re.sub(r'(?:#\s*)?(?:[0-9a-f]+ )?<[^<>]*>', '', insn).rstrip() + ' R_X86_64_' + reloc
        body = TARGET.sub(lambda m: '<' + canon(m.group(1)) + '>', body)
        body = SECTION_RELOC.sub(lambda m: m.group(1), body)
        body = CLONE.sub(lambda m: '.' + m.group(1), body)
        body = PAD.sub(lambda m: m.group(1) + 'N', body)
        body = RIP.sub('(%rip)', body)
        body = LOCAL.sub(lambda m: '.L' + m.group(1), body)
        lines.append(body.strip())
    close()
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pre_objects = objects('pre')
    post_objects = objects('post')
    pre_rel = {p.relative_to(ARMS['pre'][1]): p for p in pre_objects}
    post_rel = {p.relative_to(ARMS['post'][1]): p for p in post_objects}
    assert set(pre_rel) == set(post_rel), set(pre_rel) ^ set(post_rel)
    report = {}
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        futures = {rel: (pool.submit(bodies, pre_rel[rel], True), pool.submit(bodies, post_rel[rel]),
                         pool.submit(bodies, pre_rel[rel], True, False),
                         pool.submit(bodies, post_rel[rel], False, False))
                   for rel in sorted(pre_rel)}
        for rel, (a, b, a2, b2) in futures.items():
            old, new = a.result(), b.result()
            old2, new2 = a2.result(), b2.result()
            differ = sorted(n for n in old.keys() & new.keys() if old[n] != new[n])
            padding = [n for n in differ if old2[n] == new2[n]]
            changed = [n for n in differ if old2[n] != new2[n]]
            added = sorted(new.keys() - old.keys())
            removed = sorted(old.keys() - new.keys())
            report[str(rel)] = dict(functions=len(new), equal=len(old.keys() & new.keys()) - len(differ),
                                    padding_only=padding, changed=changed, added=added, removed=removed)
    (OUT / 'functions.json').write_text(json.dumps(report, indent=2) + '\n')
    total = sum(r['functions'] for r in report.values())
    equal = sum(r['equal'] for r in report.values())
    padding = sum(len(r['padding_only']) for r in report.values())
    print(json.dumps(dict(objects=len(report), functions=total, equal=equal, padding_only=padding)))
    for rel, r in report.items():
        if r['changed'] or r['added'] or r['removed'] or r['padding_only']:
            print(rel, 'changed', len(r['changed']), 'padding-only', len(r['padding_only']),
                  'added', len(r['added']), 'removed', len(r['removed']))


if __name__ == '__main__':
    main()
