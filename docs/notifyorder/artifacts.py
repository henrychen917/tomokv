#!/usr/bin/env python3
"""Offline notifyorder controls and identity receipts; no servers or measurements."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pad(source, output, receipt):
    before = Elf(source)
    assert before.kind != 1 and Path(source).resolve() != Path(output).resolve()
    data = bytearray(before.data)
    symbols = list(before.functions().values())
    patches = []
    for namespace in ('tomo', 'tomo_db0'):
        prefix = '_ZN' + str(len(namespace)) + namespace
        emit, = [s for s in symbols if s['name'].startswith(prefix + '16notify_flat_emitE') and '.cold' not in s['name']]
        legacy, = [s for s in symbols if s['name'].startswith(prefix) and
                    '29notify_flat_emit_unattributedE' in s['name'] and '.cold' not in s['name']]
        observe, = [s for s in symbols if s['name'].startswith(prefix + '23notify_overwrite_expiryE') and '.cold' not in s['name']]
        for symbol, target in ((emit, legacy), (observe, None)):
            sec = before.sections[symbol['sec']]
            offset = sec[4] + symbol['value'] - sec[3]
            address = symbol['value']
            if data[offset:offset+4] == b'\xf3\x0f\x1e\xfa':
                offset += 4
                address += 4
            patch = b'\xe9' + struct.pack('<i', target['value'] - address - 5) if target else b'\xc3'
            assert symbol['size'] >= len(patch) + address - symbol['value']
            patches.append(dict(symbol=symbol['name'], offset=offset, address=address,
                                target=target['name'] if target else 'return: retain PRE overwrite probe without observing',
                                before=data[offset:offset+len(patch)].hex(), after=patch.hex()))
            data[offset:offset+len(patch)] = patch
    Path(output).write_bytes(data)
    Path(output).chmod(0o755)
    after = Elf(output)
    assert before.sections == after.sections and before.symbols == after.symbols
    restored = bytearray(after.data)
    for patch in patches:
        at = patch['offset']
        restored[at:at+len(bytes.fromhex(patch['before']))] = bytes.fromhex(patch['before'])
    assert restored == before.data, 'unplanned PAD byte change'
    evidence = dict(kind='A: behaviour twin', source=str(source), output=str(output),
                    source_sha256=sha(before.data), sha256=sha(after.data),
                    behavior='PRE lazy-expiry routing/order and raw SET observation; POST AOF grouping remains',
                    layout='All bytes outside four entry patches are POST-identical, including text extent, function addresses/sizes, section/program headers',
                    patches=patches)
    Path(receipt).write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence, indent=2))


def no_salvage(source, output, receipt):
    """Throwaway negative control: abort/retry returns no physical batch."""
    before = Elf(source)
    data = bytearray(before.data)
    patches = []
    for symbol in before.functions().values():
        if '20notify_keep_physicalE' not in symbol['name'] or '.cold' in symbol['name']:
            continue
        sec = before.sections[symbol['sec']]
        offset = sec[4] + symbol['value'] - sec[3]
        if data[offset:offset+4] == b'\xf3\x0f\x1e\xfa':
            offset += 4
        patch = b'\x31\xc0\xc3'  # xor eax,eax; ret. No production source switch.
        patches.append(dict(symbol=symbol['name'], offset=offset,
                            before=data[offset:offset+3].hex(), after=patch.hex()))
        data[offset:offset+3] = patch
    assert patches and Path(source).resolve() != Path(output).resolve()
    Path(output).write_bytes(data); Path(output).chmod(0o755)
    after = Elf(output)
    assert before.sections == after.sections and before.symbols == after.symbols
    evidence = dict(control='S disabled: return null instead of salvaging physical records',
                    limitation='Short-lived negative control leaks the discarded batch; never a production or merit arm',
                    source=str(source), output=str(output), sha256=sha(after.data),
                    source_sha256=sha(before.data), patches=patches)
    Path(receipt).write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence, indent=2))


def reasons(folder):
    folder = Path(folder)
    rows = json.loads((folder / 'changed-bodies.json').read_text())
    # A second audit resolves local code addresses as well as ELF relocations.
    # Preserve the conservative inventory while distinguishing mere displacements.
    import gzip
    resolved_path = folder.parent / 'identity-resolved' / 'bodies.json.gz'
    resolved = {}
    if resolved_path.is_file():
        with gzip.open(resolved_path, 'rt') as stream:
            resolved = {(r['object'], r['symbol']): r['equal'] for r in json.load(stream)}
    for row in rows:
        name = row['name']
        row['resolved_equal'] = resolved.get((row['object'], row['symbol']))
        if row['resolved_equal']:
            reason = 'Local code-address/displacement normalization only; resolved body is PRE-identical'
        elif 'aof_record_local_op' in name:
            reason = 'A5: notification-attached scripts use the grouped persistence writer'
        elif 'notify_overwrite_expiry' in name or 'store_string_notify' in name:
            reason = 'Observe the raw SET overwrite lookup in the armed handler only'
        elif 'notify_keep_physical' in name or 'notify_discard_speculative' in name or 'notify_take_batch' in name or 'script_clear_attempt' in name:
            reason = 'S: speculative discard retains physically deleted keys'
        elif 'notify_flat_emit' in name or 'notify_record_physical' in name or 'notify_event_priority' in name or 'notify_flat_store_emit' in name:
            reason = 'R1: separate named and unattributed expiry, order Expired before New'
        elif 'NotifyBatch' in name or 'NotifyRecordImpl' in name or 'notify_get_or_create_batch' in name or 'notify_record_slow' in name:
            reason = 'Heap batch records carry physical-effect metadata; locked server layouts unchanged'
        elif 'script_drive' in name or 'notify_discard_speculative' in repr(row.get('code_targets_added')):
            reason = 'S: one of the five cross-shard script discard/retry edges uses physical salvage'
        elif 'version' in name or 'main' == name:
            reason = 'Build identity metadata or link layout; inspect recorded canonical targets'
        else:
            reason = 'Unedited body emitted differently in a changed translation unit (inlining/constant/target layout); retained as explicit spillover for merit review'
        row['reason'] = reason
    (folder / 'changed-bodies-with-reasons.json').write_text(json.dumps(rows, indent=2)+'\n')
    lines = ['| Object | Body | PRE bytes | POST bytes | Reason |', '|---|---|---:|---:|---|']
    for row in rows:
        lines.append('| ' + ' | '.join([row['object'], row['name'].replace('|', '&#124;'),
                                      str(row['pre_size']), str(row['post_size']), row['reason']]) + ' |')
    (folder / 'changed-bodies.md').write_text('\n'.join(lines)+'\n')
    print(f'{len(rows)} changed bodies attributed')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    a = sub.add_parser('pad')
    a.add_argument('source'); a.add_argument('output'); a.add_argument('receipt')
    a = sub.add_parser('no-salvage')
    a.add_argument('source'); a.add_argument('output'); a.add_argument('receipt')
    a = sub.add_parser('reasons'); a.add_argument('folder')
    args = p.parse_args()
    if args.action == 'pad':
        pad(args.source, args.output, args.receipt)
    elif args.action == 'no-salvage':
        no_salvage(args.source, args.output, args.receipt)
    else:
        reasons(args.folder)


if __name__ == '__main__':
    main()
