#!/usr/bin/env python3
"""Attach source, operand and call-site evidence to every strict body difference."""
from collections import Counter
import gzip
import json
from pathlib import Path
import re
import identity

ROOT = identity.ROOT
DOC = ROOT / 'docs/wave9/identity'
rows = json.loads((DOC / 'changed-bodies.json').read_text())
calls = {r['name']: r for r in json.loads((ROOT / 'docs/wave9/callsites/summary.json').read_text())}
sources = json.loads((DOC / 'residual-source-lines.json').read_text())
proofs = {}
raw = {a: json.load(gzip.open(ROOT / 'docs/wave9/callsites' / (a + '.json.gz'), 'rt'))
       for a in ['headline', 'post', *[x for x in identity.REFS if x != 'headline']]}


def annotation_only(a, b):
    return bool(a) and len(a) == len(b) and all(
        x['encodings'] == y['encodings'] and len(x['ins']) == len(y['ins']) and
        all(u.split('#')[0] == v.split('#')[0] for u, v in zip(x['ins'], y['ins']))
        for x, y in zip(a, b))


for row in rows:
    name = row['name']
    if row['matches']:
        row['category'] = 'lane body retained'
        continue
    evidence = calls[name]
    origin = sources[name].replace(str(ROOT) + '/', '')
    row['source'] = origin
    row['diff'] = evidence['diff']
    row['callsites'] = evidence['callsites']
    baseline = row['changed_lanes'][0] if len(row['changed_lanes']) == 1 else 'headline'
    row['comparison'] = baseline
    if annotation_only(raw[baseline][name], raw['post'][name]):
        category = 'symbolic reference annotation'
        reason = (f'All normalized encodings and instructions before the reference comment equal {baseline}; '
                  'only RIP reference annotations differ after linking. Full target annotations are retained in the diff; '
                  'this category alone does not prove referenced data equal.')
    elif 'cmd_get<true, false>' in name:
        category = 'cold GET nil reply inlining'
        reason = ('The successful GET path is unchanged. The RESP nil tail inlines Sink::advance '
                  'instead of its five-byte tail branch; this accounts for the seven-byte body growth. '
                  'Both batch sizes add no instructions. Full diff retains the cold path for measurement.')
    elif any(x in name for x in ('multi_', 'MultiExec', 'MultiCommand', 'prepare_write_key', 'prepare_commands', 'WatchReservation')) or 'multi.inc' in origin:
        category = 'EXEC lane composition'
        reason = ('Multifix RESET/PAUSE/slowlog and repeated-key version reuse share the finalizer with '
                  'woundfix cancellation and blockfix2 post-commit blocking publication. Wave8b timing '
                  'selection remains outside the child loop. See ../exec-attribution.json for every '
                  'executed function delta; instruction and call-site differences here include cold branches.')
    elif any(x in name for x in ('txn_group', 'txn_key_', 'TxnGroupAttempt', 'TxnWaiter', 'script_escalat')) or any(x in origin for x in ('txn_group.inc','txn_key_queue.inc','script_escalation.inc')):
        category = 'wound cancellation and escalated claims'
        reason = ('Woundfix publishes cancelled decisions before abort visibility; at412c reuses group '
                  'claims for scripts, preserving age across a FIFO hand-off. The composed reservation '
                  'and cleanup helpers cannot equal either isolated implementation. Wounded hand-off '
                  'and actual conflicted escalation are directed checks.')
    elif 'xshard_' in name or 'scatter_engine' in origin:
        category = 'scatter and script admission composition'
        reason = ('At412c separates script preparation and adds FIFO admission/escalation; woundfix '
                  'cancellation, streamfix MPOP handling and central reply builders share the unit. '
                  'Body diffs show helper extraction and inlining, including MGET/MSET dispatch; '
                  'all counted MGET/MSET cells add no instructions.')
    elif 'IoLoop::' in name or any(x in origin for x in ('io_loop.h','reorder.cc')):
        category = 'IO protocol and FIFO composition'
        reason = ('Protofix inline decoding, at412c script-window FIFO draining, multifix RESET/PAUSE '
                  'and blockfix2 blocking cleanup instantiate in shared IO code. The selected budgets '
                  'also move helpers between callers and callees. Read-local GET is instruction-identical; '
                  'the full instruction diff remains visible for the maintainer null.')
    elif 'ExLoopT<' in name or 'ex_loop' in origin:
        category = 'executor script hand-off composition'
        reason = ('At412c owner-side script retries and FIFO promotion share executor dispatch with '
                  'the headline timing-selected execution. The diff records register/inline propagation; '
                  'loaded execfair checks all eight legs and zero snapshot-window refusals.')
    elif any(x in origin for x in ('scripting.cc','functions.cc')) or 'ScriptWorkbench' in name:
        category = 'script escalation and reply composition'
        reason = ('At412c escalated activation and claim handling compose with central sanitized errors '
                  'and existing script timing. Exact successful/failed activation behavior is exercised by '
                  'the script, scriptatomic and at412 jobs; full call-site differences remain recorded.')
    elif 'blocking' in origin or any(x in name for x in ('blocking_', 'Blocked', 'stream_remove')):
        category = 'blocking lifecycle and stream removal'
        reason = ('Blockfix2 waiter retention, EXEC-mutation publication and removal notification '
                  'compose with multifix reused versions and streamfix accounting. Sequential removal '
                  'and escalated/EXEC list publication have directed checks. The pipelined re-create '
                  'diagnostic remains an explicit failing wave-10 dependency.')
    elif 'stream' in origin or 'Stream' in name:
        category = 'stream node accounting and blocking signal'
        reason = ('Streamfix node lifetime/accounting and stream/MPOP semantics compose with blockfix2 '
                  'last-reference removal notification and crlffix central error framing. Stream-node '
                  'conservation and blocked-reader reply framing are checked together.')
    elif any(x in origin for x in ('flatstore','kvobj','atomic_mvcc','atomics_glue','watch_modified')):
        category = 'version reuse and value retirement composition'
        reason = ('Multifix reuses transaction-owned versions; blockfix2 distinguishes external-byte '
                  'accounting from retiring value destruction and signals removed streams. Woundfix '
                  'decision publication shares these immutable-version helpers. Full source/call-site '
                  'evidence is retained, including template/inline propagation.')
    elif any(x in origin for x in ('resp.h','resp3.h')) or any(x in name for x in ('reply_err','reply_status','sanitize')):
        category = 'central reply sanitization'
        reason = ('Crlffix sanitizes CR/LF in status/error builders. Shared template instantiations '
                  'and inlining differ in the merged unit; docs/crlffix/audit.md and wave9-added-sites.json '
                  'enumerate original and newly added error paths.')
    elif any(x in origin for x in ('notify.inc','tracking.cc','climon.cc','pubsub.inc')):
        category = 'observer publication composition'
        reason = ('Multifix RESET/EXEC behavior and blockfix2 committed mutation publication share '
                  'observer/reply helpers with crlffix. Inline placement and referenced static data '
                  'change after composition; call-site deltas retain each added or removed helper.')
    elif name.startswith('_GLOBAL__sub_I_'):
        category = 'initialization and static data layout'
        reason = ('Combined command/static registrations and script FIFO initialization relocate referenced objects '
                  'and change static initialization code. This is outside per-command execution.')
    elif name.startswith(('std::', 'void std::', 'bool std::', 'unsigned long std::')) or '/usr/include/' in origin:
        category = 'container template instantiation'
        reason = ('Container/string helper instantiations reflect combined script queue, transaction and stream data types and compiler '
                  'inline decisions. Call-site deltas and exact types distinguish added helpers from relocated existing helpers.')
    elif 'cfg_' in name or 'config.' in origin or 'info_' in name or 't_server.cc' in origin:
        category = 'configuration and INFO composition'
        reason = ('Multifix RESET/PAUSE and at412c script counters compose with existing server configuration; '
                  'merged inline/static-data context changes this body. Grammar, INFO and Tcl checks cover public behavior.')
    elif name == 'main' or 'tomokv_multidb_main(' in name or 'Server::init(' in name or '::run_' in name:
        category = 'boot and loop instantiation'
        reason = ('Combined configuration/command registrations and executor/IO template instantiations alter initialization '
                  'and loop selection. Both namespaces/modes boot in the gate jobs; these bodies are outside command dispatch accounting.')
    elif 'classify_keys(' in name:
        category = 'scatter classifier compilation'
        reason = ('The merged scatter inline budget changes basic-block placement and register allocation in the existing '
                  'key classifier. All MGET/MSET executed totals add no instructions; '
                  'the strict full classifier difference is retained for the null.')
    else:
        category = 'remaining compiler propagation'
        reason = (f'Body in {origin} differs after the recorded combined-source and budget build. '
                  'Lane parentage, complete instruction diff and call-site deltas are retained; '
                  'no single optimizer decision was isolated. This remains a compiler identity difference for the maintainer null.')
    row['category'] = category
    row['reason'] = reason

(DOC / 'reviewed-bodies.json').write_text(json.dumps(rows, indent=2) + '\n')
lines = ['# Complete merged body review', '',
         f"All {len(rows):,} strict differences are listed. Exact lane matches retain their lane body; the {sum(not r['matches'] for r in rows):,} residual groups include source/call-site evidence. No opcode, branch, register, member offset or clone was masked in the strict inventory.", '',
         '| Function | Headline → POST bytes | Reason and evidence |', '|---|---|---|']
for row in rows:
    reason = row['reason']
    if 'diff' in row:
        reason += f" Source: `{row['source']}`. [Instructions]({Path(row['diff']).name.replace('diff-', '../callsites/diff-')})."
    lines.append(f"| `{row['name']}` | {row['headline_sizes']} → {row['post_sizes']} | {reason} |")
(DOC / 'reviewed-bodies.md').write_text('\n'.join(lines) + '\n')
counts = dict(Counter(row['category'] for row in rows))
(DOC / 'review-summary.json').write_text(json.dumps(counts, indent=2) + '\n')
print(json.dumps(counts))
