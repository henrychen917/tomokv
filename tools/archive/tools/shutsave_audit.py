#!/usr/bin/env python3
"""Annotate the full PSFIX byte audit with shutdown-specific instruction receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from lbstall_artifacts import Elf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('build/shutsave'))
    args = parser.parse_args()
    root = args.root
    report = json.loads((root / 'audit/audit.json').read_text())
    decoded = {}

    def instructions(arm, relative, symbol):
        path = root / arm / relative
        if path not in decoded:
            elf = Elf(path)
            rows, section = {}, None
            for line in subprocess.check_output(['objdump', '-dw', str(path)], text=True).splitlines():
                if line.startswith('Disassembly of section '):
                    section = line[len('Disassembly of section '):-1]
                match = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*', line)
                if match:
                    rows.setdefault(section, []).append((int(match[1], 16), bytes.fromhex(match[2])))
            decoded[path] = elf, rows
        elf, rows = decoded[path]
        fn = elf.functions()[symbol]
        body = [raw for at, raw in rows[elf.names[fn['sec']]]
                if fn['value'] <= at < fn['value'] + fn['size']]
        assert b''.join(body) == elf.body(fn), (arm, relative, symbol, 'instruction coverage')
        return len(body), hashlib.sha256(elf.body(fn)).hexdigest()

    for row in report['changed_bodies']:
        name = row['name']
        if 'SnapshotManager::start(' in name:
            reason = 'Terminal stop cancels SAVE, reaps its own IO, and returns without stopped-owner acknowledgements'
        elif 'SnapshotManager::on_io_complete(' in name:
            reason = 'Unchanged cold completion logic; GCC inlining changed after the new cancellation caller'
        elif 'DatabaseMap::join_workers(' in name:
            reason = 'Latch bounded persistence grace through save finalization and worker-stack exit'
        elif 'DatabaseMap::monitor(' in name or 'DatabaseMap::reclaim(' in name:
            reason = 'Apply bounded persistence grace to pending live map acknowledgements/drains'
        elif 'DatabaseMap::state(' in name:
            reason = 'Allocate/initialize eight extra cold State bytes for the last persistence observation'
        elif any(token in name for token in ('DatabaseMap::publish(', 'DatabaseMap::worker_exited(',
                                             'DatabaseMap::boundary_started(', 'DatabaseMap::~DatabaseMap(')):
            reason = 'Cold State mutex/condition-variable offsets and sized destruction follow the added timestamp'
        else:
            raise AssertionError((name, 'unreviewed changed body'))
        row['reason'] = reason
        for arm in ('PRE', 'POST'):
            row[arm.lower() + '_instructions'], row[arm.lower() + '_raw_sha256'] = instructions(
                arm, row['object'], row['symbol'])
    commands = report['command_bodies']
    assert commands and all(row['raw_equal'] and row['relocation_equal'] for row in commands)
    hot = json.loads((root / 'audit/hot-bodies.json').read_text())
    assert hot and all(row['raw_equal'] and row['relocation_equal'] for row in hot)
    # Validate that normalization cannot hide a changed opcode or a changed callee.
    witness = Elf(root / 'PRE/src/cmd/t_string.o')
    fn = next(fn for name, fn in witness.functions().items() if 'cmd_get' in name and fn['size'] > 100)
    before = witness.canonical(fn)
    raw = witness.data
    changed = bytearray(raw)
    changed[witness.sections[fn['sec']][4] + fn['value']] ^= 1
    witness.data = bytes(changed)
    assert witness.canonical(fn) != before, 'changed opcode escaped byte audit'
    witness.data = raw
    rels = witness.relocs[fn['sec']]
    index = next(i for i, (at, kind, _, _) in enumerate(rels)
                 if kind == 4 and fn['value'] <= at < fn['value'] + fn['size'])
    saved = rels[index]
    at, kind, target, addend = saved
    rels[index] = (at, kind, dict(target, sec=0, name='SHUTSAVE_WRONG_CALLEE'), addend)
    assert witness.canonical(fn) != before, 'changed callee escaped relocation audit'
    rels[index] = saved
    report.update(all_command_bodies_raw_equal=len(commands), stock_hot_bodies_raw_equal=len(hot),
                  audit_controls=dict(changed_opcode_rejected=True, changed_callee_rejected=True))
    (root / 'audit/shutsave.json').write_text(json.dumps(report, indent=2) + '\n')
    print('%d/%d command bodies and %d/%d hot bodies: raw bytes AND relocation targets identical' %
          (len(commands), len(commands), len(hot), len(hot)))
    for row in report['changed_bodies']:
        print('%s | %d -> %d bytes | %d -> %d instructions | %s | %s' %
              (row['object'], row['pre_size'], row['post_size'], row['pre_instructions'],
               row['post_instructions'], row['name'], row['reason']))
    print('Changed-opcode and changed-callee negative controls: PASS')


if __name__ == '__main__':
    main()
