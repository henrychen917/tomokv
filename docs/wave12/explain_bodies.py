#!/usr/bin/env python3
"""Add instruction-level evidence to the strict, unmodified identity census."""
import collections
import gzip
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT/'docs/wave12/identity'
sys.path.insert(0, str(ROOT/'tools'))
from lbstall_artifacts import Elf


def literals(path):
    elf = Elf(path)
    names = {}
    for line in subprocess.check_output(['nm','-S','-C','--defined-only',str(path)], text=True).splitlines():
        parts = line.split(None,3)
        if len(parts)==4 and parts[2] not in 'tTwW':
            names.setdefault(parts[3],set()).add(int(parts[0],16))

    def resolve(line):
        # Only the exact eight bytes read by scalar double arithmetic. Other
        # address forms remain unexplained by this supplementary classification.
        match = re.search(r'\b(?:v?addsd|v?subsd|v?mulsd|v?divsd|v?u?comisd) .* # <(.+)\+0x([0-9a-f]+)>$',line)
        if not match:
            return None
        targets = names.get(match[1],set())
        if len(targets)!=1:
            return None
        target = next(iter(targets))+int(match[2],16)
        for section in elf.sections:
            if section[1]==1 and section[2]&2 and not section[2]&(1|4):
                if section[3] <= target <= section[3]+section[5]-8:
                    start = section[4]+target-section[3]
                    return dict(address=hex(target), bytes=elf.data[start:start+8].hex())
        return None
    return resolve


def main():
    rows = json.loads((DOC/'changed-bodies.json').read_text())
    with gzip.open(DOC/'residual-instruction-deltas.json.gz','rt') as stream:
        deltas = json.load(stream)
    by = {r['name']:r for r in deltas['rows']}
    resolve = {a:literals(deltas['arms'][a]['path']) for a in ('headline','POST')}
    for row in rows:
        if row['matches']:
            continue
        proof = by[row['name']]['references']['headline']
        literal_proof = []
        eligible = all(p['encoding_equal'] for p in proof)
        for pair in proof:
            removed = [s[1:] for s in pair['instruction_diff'] if s.startswith('-') and not s.startswith('---')]
            added = [s[1:] for s in pair['instruction_diff'] if s.startswith('+') and not s.startswith('+++')]
            if len(removed)!=len(added):
                eligible=False
                break
            for a,b in zip(removed,added):
                x,y = resolve['headline'](a),resolve['POST'](b)
                if a.split(' # ')[0]!=b.split(' # ')[0] or not x or not y or x['bytes']!=y['bytes']:
                    eligible=False
                    break
                literal_proof.append(dict(pre=x,post=y))
        if eligible and literal_proof:
            row['reason']='Identical encoded instructions after relocation masking; only objdump labels for unnamed double constants differ. All loaded eight-byte values verified equal; strict census still retains this difference.'
            row['literal_proof']=literal_proof
            continue
        lane = row['changed_lanes'][0] if len(row['changed_lanes'])==1 else 'headline'
        calls = collections.Counter()
        for pair in by[row['name']]['references'][lane]:
            for line in pair['instruction_diff']:
                if line.startswith(('+','-')) and (m:=re.search(r'\bcall (.+)$',line)):
                    calls[m[1]] += 1 if line[0]=='+' else -1
        row['static_call_site_delta_vs']=lane
        row['static_call_site_deltas']={k:v for k,v in calls.items() if v}
        if 'flush_redispatch<false>' in row['name']:
            row['reason']='FLUSH redispatch retains the unconditional continuation wake. Compared with flushfix3, GCC outlines MaskedSpscArray::note_lane_full and changes register allocation; the literal instruction diff is retained.'
        elif '::execute_flush(' in row['name']:
            row['reason']='The db0 FLUSH body calls Server::atomic_read_floor instead of inlining its scan; all range-ready, erase and release calls remain. This purposeful lane body does not exactly match its isolated POST.'
        elif any(s in row['name'] for s in ('flip_control_pass','flip_begin','flipctl_debug_dump')):
            row['reason']='Composition with wave11 flipfix5 stage-owed/debug-stage handling and the FLUSH admission/drain path; retain both behaviors. Compiler layout/inlining also differs. See exact reference instruction and call-site deltas.'
        elif '::cmd_info(' in row['name'] or 'info_stats_build_fields' in row['name']:
            row['reason']='INFO combines wave11 script/FLIP metadata with the new FLUSH counters and CONFIG state; the build identifier also changes. Register allocation, inlining and cold paths follow the combined body.'
        elif 'parse_and_dispatch<' in row['name'] or 'xshard_flush_commits' in row['name']:
            row['reason']='Shared dispatch/commit code combines FLUSH unit admission and retirement, maxmemrace owner binding, and wave11 script/PAUSE metadata. It cannot be represented by one isolated lane POST; exact instruction diffs and command-scope counts are retained.'
        elif '::script_execute(' in row['name'] or 'ScriptCache::' in row['name']:
            row['reason']='Persistent cached-script execution combines wave11 scriptfix3 with owner memory-config binding; GCC makes different inlining choices in db0. Warm EVAL/EVALSHA native and Lua counts remain at or below scriptfix3.'
        else:
            row['reason'] += ' Exact opcode/register/block and static call-site differences are retained in residual-instruction-deltas.json.gz; no semantic or performance equivalence is inferred from equal size.'
    (DOC/'changed-bodies.json').write_text(json.dumps(rows,indent=2)+'\n')
    lines=['# Linked body differences','','Strict instruction/address normalization. Literal-only explanations do not alter the original census. Identity is a proxy; no throughput claim.','',
           '| Function | Headline sizes | Merged sizes | Reason |','|---|---|---|---|']
    for r in rows:
        lines.append(f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |")
    (DOC/'changed-bodies.md').write_text('\n'.join(lines)+'\n')
    print('verified literal-only groups',sum('literal_proof' in r for r in rows))


if __name__ == '__main__':
    main()
