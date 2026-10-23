#!/usr/bin/env python3
"""EX4.1: offline disassembly witness, exact-layout PAD-A, and linked identity.

No server, workload generator, or performance verdict. The structural check must
reject PRE and the no-prefetch PAD; absence of a matching body is never a pass.
"""
import argparse
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import reorder_noop as audit
from lbstall_artifacts import Elf


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def disassemble(path, debug=False):
    bodies = {}
    current = None
    inline = ''
    options = '-dwlC' if debug else '-dwC'
    for line in subprocess.check_output(['objdump', options, str(path)], text=True).splitlines():
        match = re.match(r'^([0-9a-f]+) <(.+)>:$', line)
        if match:
            current = bodies.setdefault(match[2], [])
            inline = ''
        elif debug and line.endswith('):'):
            inline = line[:-1]
        elif current is not None:
            match = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
            if match:
                row = dict(address=int(match[1], 16), raw=match[2].strip(), ins=match[3])
                if debug and '::prefetch_exec_batch(' in inline:
                    row['inline'] = inline
                current.append(row)
    return bodies


def inspect(binary, output, expect):
    bodies = disassemble(binary, debug=True)
    selected = {}
    for name, rows in bodies.items():
        if 'ExLoopT<' not in name:
            continue
        calls = [r for r in rows if (target := re.match(r'(?:call|jmp)\s+([0-9a-f]+) ', r['ins'])) and
                 not rows[0]['address'] <= int(target[1], 16) <= rows[-1]['address'] and
                 any(s in r['ins'] for s in ('exec_batch_prefetched<', 'prefetch_exec_slots(', 'prefetch_owner_batch('))]
        walk_rows = [r for r in rows if 'inline' in r]
        if not calls and not walk_rows and not any(s in name for s in ('prefetch_exec_slots(', 'prefetch_owner_batch(')):
            continue
        hints = [r for r in rows if r['ins'].startswith('prefetch')]
        selected[name] = dict(address=hex(rows[0]['address']), instructions=len(rows),
                              hints=hints, calls=calls, inline_walk=walk_rows)
    for ns in ('tomo', 'tomo_db0'):
        for fused in ('false', 'true'):
            prefix = f'{ns}::ExLoopT<{fused}>::'
            drains = [v for k, v in selected.items() if prefix in k and 'drain_tasks' in k]
            assert drains, ('missing drain bodies', prefix)
            walks = [v for k, v in selected.items() if k.startswith(prefix + 'prefetch_exec_slots(')]
            if expect == 'post':
                assert len(walks) == 1 and len(walks[0]['hints']) == 2, ('missing bucket hints', prefix)
                assert any('prefetch_exec_slots(' in c['ins'] for v in drains for c in v['calls']), prefix
            elif expect == 'pre':
                assert not walks and all(not d['hints'] for d in drains), ('PRE changed', prefix)
    owners = [v for k, v in selected.items() if '::prefetch_owner_batch(' in k]
    assert len(owners) == 2 and all(len(v['hints']) == 2 for v in owners), 'fused baseline lost hints'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(binary=str(binary), sha256=digest(binary), expect=expect,
                                      bodies=selected), indent=2) + '\n')
    print(f'{expect}: {len(selected)} bodies; ' +
          ', '.join(f'{k}: {len(v["hints"])} hints' for k, v in selected.items()
                    if '::prefetch_' in k))


def pad(binary, output):
    elf = Elf(binary)
    patched = bytearray(elf.data)
    sites = []
    for name, rows in disassemble(binary).items():
        if '::prefetch_exec_slots(' not in name:
            continue
        hints = [r for r in rows if r['ins'].startswith('prefetch')]
        assert len(hints) == 2, ('expected both table hints', name)
        for row in hints:
            raw = bytes.fromhex(row['raw'])
            # One architectural NOP of the same length: retain addressing bytes,
            # ModRM/SIB/displacement and register dependencies in the walk.
            opcode = 1 if 0x40 <= raw[0] <= 0x4f else 0
            assert raw[opcode:opcode + 2] == b'\x0f\x18' and (raw[opcode + 2] >> 3) & 7 == 1, row
            replacement = (raw[:opcode] + b'\x0f\x1f' + bytes([raw[opcode + 2] & ~0x38]) +
                           raw[opcode + 3:])
            sections = [s for s in elf.sections if s[3] <= row['address'] < s[3] + s[5] and s[2] & 4]
            assert len(sections) == 1
            section = sections[0]
            offset = section[4] + row['address'] - section[3]
            assert patched[offset:offset + len(raw)] == raw
            patched[offset:offset + len(raw)] = replacement
            sites.append(dict(body=name, address=hex(row['address']), offset=offset,
                              before=raw.hex(), after=replacement.hex()))
    assert len(sites) == 8, ('expected four fallback bodies, two tables each', sites)
    output.write_bytes(patched)
    output.chmod(binary.stat().st_mode)
    allowed = {s['offset'] + i for s in sites for i in range(len(bytes.fromhex(s['before'])))}
    assert len(patched) == len(elf.data)
    assert all(i in allowed for i, (a, b) in enumerate(zip(elf.data, patched)) if a != b)
    print(json.dumps(dict(kind='A: behaviour twin', prefetches='fallback only; fused owner hints retained',
                          post_sha256=digest(binary), pad_sha256=digest(output), sites=sites), indent=2))


def identity_reason(name):
    if 'prefetch_exec_slots' in name:
        return 'EX4.1: flattened out-of-line fallback bucket walk.'
    if 'drain_tasks' in name or 'prefetch_exec_batch' in name:
        return 'EX4.1: inline fallback replaced by n > 1 guard and a direct walk call, including gathered/R7 emit copies.'
    if 'ExLoopT<' in name and '::run(' in name:
        return 'EX4.1: embedded task-drain fallback; compiler also changes drain inlining and register allocation.'
    if 'parse_and_dispatch' in name:
        return 'Unedited parser: executor-header change shifts GCC unit inlining; helpers/spills/blocks differ. Residual cost risk for merit.'
    if 'r7_fused_sweep_impl' in name:
        return 'Unedited sweep: compiler changes the inlining of compact_local_read_tombstones after the executor-header change.'
    if 'IoLoop::run_loop' in name or 'IoLoop::r7_run_loop' in name:
        return 'Unedited IO loop: downstream inlining/register allocation after executor-header change; cost risk for merit.'
    if 'pubsub_reply_restricted' in name:
        return 'Unedited helper: downstream inlining after executor-header change.'
    if 'IoLoop::touch_worker' in name or 'Rob<64u>::acquire' in name:
        return 'Unedited helper: standalone copy disappears as GCC changes inlining of callers.'
    if 'watch_flush' in name:
        return 'Existing study-label ordinal changes (tomo_multidb2_pad); inspect relocation identity, not a command-body edit.'
    if 'epoll_pass' in name:
        return 'Unedited epoll body: literal-pool target label changes in linked audit; no explicit executor edit.'
    return 'Unedited body: compiler/link propagation from the executor-header change; strict difference retained, merit decides.'


def identity(pre, post, output):
    output.mkdir(parents=True, exist_ok=True)
    before = audit.Binary(pre, output, literal_pools=True)
    after = audit.Binary(post, output, literal_pools=True)
    rows = []
    equal = 0
    for name in sorted(set(before.groups) | set(after.groups)):
        old = sorted(before.groups.get(name, []), key=lambda b: b['addr'])
        new = sorted(after.groups.get(name, []), key=lambda b: b['addr'])
        if [(b['ins'], b['encodings']) for b in old] == [(b['ins'], b['encodings']) for b in new]:
            equal += 1
            continue
        reason = identity_reason(name)
        def lines(bs):
            return [f'clone {i}: {ins} | {enc}\n' for i, b in enumerate(bs)
                    for ins, enc in zip(b['ins'], b['encodings'])]
        rows.append(dict(name=name, pre_sizes=[b['size'] for b in old],
                         post_sizes=[b['size'] for b in new], reason=reason,
                         diff=''.join(difflib.unified_diff(lines(old), lines(new), fromfile='PRE', tofile='POST'))))
    with gzip.open(output / 'strict-diffs.json.gz', 'wt') as f:
        json.dump(rows, f, indent=2)
    (output / 'changed-bodies.md').write_text(
        '# Linked body inventory\n\nGate normalizer with literal-pool verification. Identity is a proxy; merit decides.\n\n'
        '| Body | PRE bytes | POST bytes | Reason |\n|---|---|---|---|\n' +
        '\n'.join(f'| `{r["name"]}` | {r["pre_sizes"]} | {r["post_sizes"]} | {r["reason"]} |' for r in rows) + '\n')
    summary = dict(pre_sha256=before.sha256, post_sha256=after.sha256, equal=equal, changed=len(rows),
                   changed_bodies=[{k: v for k, v in r.items() if k != 'diff'} for r in rows])
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'changed_bodies'}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('inspect')
    p.add_argument('binary', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--expect', choices=('pre', 'post', 'control'), required=True)
    p = sub.add_parser('pad')
    p.add_argument('binary', type=Path)
    p.add_argument('output', type=Path)
    p = sub.add_parser('identity')
    p.add_argument('pre', type=Path)
    p.add_argument('post', type=Path)
    p.add_argument('output', type=Path)
    args = vars(parser.parse_args())
    globals()[args.pop('command')](**args)


if __name__ == '__main__':
    main()
