#!/usr/bin/env python3
"""Explain strict identity exceptions without weakening the identity census."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave13'
IDENTITY = DOC / 'identity'
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf


def tables(path):
    elf = Elf(path)
    found = collections.defaultdict(set)
    for line in subprocess.check_output(['nm', '-S', '--defined-only', str(path)], text=True).splitlines():
        fields = line.split()
        if len(fields) != 4 or not fields[3].startswith('CSWTCH.'):
            continue
        address, size = int(fields[0], 16), int(fields[1], 16)
        for section in elf.sections:
            if section[1] == 1 and section[2] & 2 and not section[2] & (1 | 4):
                if section[3] <= address and address + size <= section[3] + section[5]:
                    start = section[4] + address - section[3]
                    found[fields[3]].add(elf.data[start:start+size].hex())
    return {name: next(iter(values)) for name, values in found.items() if len(values) == 1}


def main():
    rows = json.loads((IDENTITY / 'changed-bodies.json').read_text())
    with gzip.open(IDENTITY / 'residual-instruction-deltas.json.gz', 'rt') as stream:
        deltas = json.load(stream)
    by = {row['name']: row for row in deltas['rows']}
    layouts = json.loads((DOC / 'layouts.json').read_text())
    layouts.update(json.loads((DOC / 'reference-layouts.json').read_text()))
    layouts['headline'] = layouts['PRE']
    literal = {label: tables(arm['path']) for label, arm in deltas['arms'].items()}
    counts = collections.Counter()

    def explain(row, reference):
        ns = 'tomo_db0' if 'tomo_db0::' in row['name'] else 'tomo'
        pre_type = layouts[reference]['types'][ns]['Server']
        post_type = layouts['POST']['types'][ns]['Server']
        before, after = pre_type['fields'], post_type['fields']
        # Include interior members (e.g. string data/size) only inside a real,
        # independently inspected field whose complete size stays unchanged.
        moves = [(offset, pre_type['field_bytes'][name], after[name], name)
                 for name, offset in before.items() if name in after and after[name] != offset
                 and pre_type['field_bytes'][name] == post_type['field_bytes'][name]]
        member_proof, table_proof = [], []
        for pair in by[row['name']]['references'][reference]:
            if pair['pre_size'] != pair['post_size']:
                return None
            removed = [s[1:] for s in pair['instruction_diff'] if s.startswith('-') and not s.startswith('---')]
            added = [s[1:] for s in pair['instruction_diff'] if s.startswith('+') and not s.startswith('+++')]
            if len(removed) != len(added):
                return None
            for old, new in zip(removed, added):
                def member(match):
                    number = int(match[1], 16)
                    for start, size, target, name in moves:
                        if start <= number < start + size:
                            target += number - start
                            member_proof.append(dict(field=name, field_bytes=size,
                                                     interior_offset=number-start,
                                                     before=number, after=target))
                            return '0x' + format(target, 'x')
                    return match[0]
                replaced = re.sub(r'0x([0-9a-f]+)(?=\(%[a-z0-9]+[,)])', member, old)
                # GCC can fold shard_owner_'s byte offset into the array index:
                # add $field_offset/4,index; mov (server,index,4),owner. Require
                # that exact unchanged consumer, the same instruction position,
                # and independently inspected offsets for this uint32_t array.
                bias = re.search(r'\badd \$0x([0-9a-f]+),(%[a-z0-9]+)$', old)
                if bias and int(bias[1], 16) * 4 == before['shard_owner_']:
                    index = pair['instruction_diff'].index('-' + old)
                    consumer = pair['instruction_diff'][index + 2:index + 3]
                    if (consumer and consumer[0].startswith(' ') and
                            re.search(r'\bmov \(%[a-z0-9]+,' + re.escape(bias[2]) + r',4\),%[a-z0-9]+$', consumer[0]) and
                            after['shard_owner_'] % 4 == 0 and
                            pre_type['field_bytes']['shard_owner_'] == post_type['field_bytes']['shard_owner_'] == 1024):
                        replaced = replaced.replace('$0x' + bias[1], '$0x' + format(after['shard_owner_'] // 4, 'x'))
                        member_proof.append(dict(field='shard_owner_', field_bytes=1024,
                                                 before=before['shard_owner_'], after=after['shard_owner_'],
                                                 addressing='uint32 index bias; unchanged scale-4 load',
                                                 consumer=consumer[0][1:]))
                def table(line, arm):
                    def replace(match):
                        value = literal[arm].get(match[1])
                        if value is None:
                            return match[0]
                        table_proof.append(dict(arm=arm, symbol=match[1], bytes=value))
                        return '<TABLE:' + value + '>'
                    return re.sub(r'<(CSWTCH\.\d+)>', replace, line)
                if table(replaced, reference) != table(new, 'POST'):
                    return None
        if not member_proof and not table_proof:
            return None
        return dict(reference=reference, members=member_proof, tables=table_proof)

    for row in rows:
        if row['matches']:
            counts['exact-lane'] += 1
            continue
        candidates = ['headline', *row['changed_lanes']]
        proof = next((p for arm in candidates if (p := explain(row, arm))), None)
        if proof:
            row['verified_displacement_or_table_only'] = proof
            reasons = []
            if proof['members']:
                reasons.append('only independently verified Server member displacements differ')
            if proof['tables']:
                reasons.append('only compiler switch-table labels differ; complete table bytes match')
            row['reason'] = ('Compared with ' + proof['reference'] + ', ' + '; '.join(reasons) +
                             '. Instruction positions, lengths, opcodes and other operands match. '
                             'The strict identity census retains this difference.')
            counts['verified-layout-or-table'] += 1
            continue
        reference = row['changed_lanes'][0] if len(row['changed_lanes']) == 1 else 'headline'
        calls = collections.Counter()
        for pair in by[row['name']]['references'][reference]:
            for line in pair['instruction_diff']:
                if line.startswith(('+', '-')) and (match := re.search(r'\bcall (.+)$', line)):
                    calls[match[1]] += 1 if line[0] == '+' else -1
        row['static_call_site_delta_vs'] = reference
        row['static_call_site_deltas'] = {name: n for name, n in calls.items() if n}
        name = row['name']
        if any(s in name for s in ('flip_control_pass', 'flip_begin', 'flip_session_drain_refused', 'flipctl_debug_dump')):
            reason = ('FLIP composes session transfer/refusal and alias accounting with headline FLUSH drain state; '
                      'persistfmt also shifts trailing Server fields. GCC propagation differs from the isolated lane.')
        elif any(s in name for s in ('xshard_prepare(', 'xshard_execute(', 'classify_keys(', 'prepare_commands(')):
            reason = ('Shared fanout/transaction code retains the headline FLUSH unit, script FIFO and CONFIG ownership, '
                      'plus flipfix6 WATCH aliases. SnapshotManager growth moves trailing Server fields by 24 bytes; '
                      'whole-unit compilation also changes inlining/register/block choices. Per-command executed deltas are retained.')
        elif 'flush_redispatch<' in name:
            reason = ('Headline FLUSH continuation/wake logic is unchanged. Shared xshard compilation changes outlining '
                      'and register allocation; the normal namespace adds one counted instruction per FLUSH activation.')
        elif any(s in name for s in ('Snapshot', 'snapshot_', 'decode_stream', 'decode_value', 'restore', 'function_', 'Function')):
            reason = ('Persistfmt stream/library persistence combines with headline snapshot/FLUSH integration. '
                      'The retained implementation has compiler/layout propagation beyond the isolated lane body.')
        elif '::cmd_info(' in name or 'info_stats' in name:
            reason = ('INFO combines both lanes with headline FLUSH/CONFIG counters, and includes the recorded build ID; '
                      'generated constants, inlining and field displacements follow the combined implementation.')
        elif 'Aof' in name or 'aof_' in name:
            reason = ('Persistence composes PS4.4 failure-before-acknowledgement handling and function-bearing snapshot '
                      'preambles with headline FLUSH records. Exact instruction differences are retained.')
        elif not row['changed_lanes']:
            reason = ('No lane edits this logical body. Whole-unit inlining, emitted clone multiplicity, '
                      'register allocation or generated source-location constants propagate from the merged unit.')
        else:
            reason = row['reason'].split(' See residual-instruction-deltas.json.gz', 1)[0]
        row['reason'] = reason + ' See residual-instruction-deltas.json.gz for every reference diff; equal size is not an equivalence claim.'
        counts['other-residual'] += 1
    (IDENTITY / 'changed-bodies.json').write_text(json.dumps(rows, indent=2) + '\n')
    lines = ['# Linked body differences', '', 'Strict identity results remain unchanged. Supplementary explanations do not mask member offsets or rename tables in the census.', '',
             '| Function | Headline bytes | POST bytes | Reason |', '|---|---|---|---|']
    lines += [f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in rows]
    (IDENTITY / 'changed-bodies.md').write_text('\n'.join(lines) + '\n')
    (IDENTITY / 'explanation-summary.json').write_text(json.dumps(counts, indent=2) + '\n')
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
