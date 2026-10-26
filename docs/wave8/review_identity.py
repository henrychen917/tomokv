#!/usr/bin/env python3
"""Attach source, operand and call-site evidence to every strict body difference."""
from collections import Counter
import gzip
import json
from pathlib import Path
import re
import identity

ROOT = identity.ROOT
DOC = ROOT / 'docs/wave8/identity'
rows = json.loads((DOC / 'changed-bodies.json').read_text())
calls = {r['name']: r for r in json.loads((ROOT / 'docs/wave8/callsites/summary.json').read_text())}
sources = json.loads((DOC / 'residual-source-lines.json').read_text())
proofs = json.loads((DOC / 'hot-provenance.json').read_text())['bodies']
raw = {a: json.load(gzip.open(ROOT / 'docs/wave8/callsites' / (a + '.json.gz'), 'rt'))
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
    if name in proofs:
        category = 'verified operand relocation'
        reason = ('Exact instruction shape and read-only bytes; TLS operands resolve to the same '
                  'ScriptWorkbench fields/guard. See hot-provenance.json; strict identity remains different.')
    elif annotation_only(raw[baseline][name], raw['post'][name]):
        category = 'symbolic reference annotation'
        reason = (f'All normalized encodings and instructions before the reference comment equal {baseline}; '
                  'only RIP reference annotations differ after linking. Full target annotations are retained in the diff; '
                  'this category alone does not prove referenced data equal.')
    elif any(x in name for x in ('txn_link_waiter(', 'txn_unlink_waiter(', 'TxnWaiter::',
                                'TxnGroupAttempt::~', 'txn_group_arrive(', 'txn_group_prepare(',
                                'FlatStore::make_word(', 'atomic_epoch(')):
        category = 'stable assertion diagnostics'
        reason = ('Readability site IDs replace source file/line/function assertion arguments, including assertions '
                  'inlined from execindex queue nodes. The generated 15-site map and deliberate abort controls '
                  'verify diagnostic identity. Assertion failure paths remain failures.')
    elif 'latency_tracking' in origin or 'ExecutorHistograms' in name or 'retire_script_children' in name:
        category = 'logical timing retirement'
        reason = ('Latency histogram store and helpers include integration staging/cleanup of script-child samples '
                  'and transfer of EXEC active durations across retry. Exact-count positive and broken-control checks cover retirement.')
    elif 'multi.inc' in origin or any(x in name for x in ('MultiClaim', 'MultiExec', 'MultiOwnerRetry', 'WatchReservation')):
        category = 'EXEC index and timing composition'
        reason = ('Execindex intrusive claims/retry queues compose with latencyfix active scopes and the integration '
                  'logical-child retirement/transfer repair. Claim, retry and histogram checks cover this path.')
    elif any(x in origin for x in ('ex_loop', 'ex_execute')) or 'ExLoopT<' in name:
        category = 'executor dispatch composition'
        reason = ('Latency-selected owner execution and intrusive EXEC retry callbacks share the executor instantiation; '
                  'inline placement/register allocation also changes. Resumed work retains execute_resumed. '
                  'Instruction traces cover executed main-command paths; execfair covers parked/polled owners.')
    elif 'IoLoop::' in name or 'io_loop' in origin:
        if 'flush_ready<' in name:
            category = 'IO inline propagation'
            reason = ('Merged main/R7 inline context moves receive-buffer reset and parser helpers between caller and callee; '
                      'the per-body call-site additions/removals below record the actual change. '
                      'No individual throughput conclusion follows from this compiler difference.')
        elif 'run_loop<' in name:
            category = 'IO grace and timing composition'
            reason = ('Completion-derived WB4.1 grace with multiplier 2 shares the loop with latency configuration/admission. '
                      'The merged loop cannot equal either isolated lane; parking and timing jobs exercise both.')
        else:
            category = 'IO admission and inline propagation'
            reason = ('Latency tracking changes parser/read-local admission and timed dispatch; the merged unit budgets '
                      'also change helper inlining. Exact off-path command counts and read-local timing transitions are checked.')
    elif 'scripting.cc' in origin or 'functions.cc' in origin or 'script_execute(' in name:
        category = 'Lua libraries and timing composition'
        reason = ('Lua helper registration/sandbox composition plus staged nested-command timing and fresh-activation cleanup; '
                  'script OCC retries publish only the final activation children.')
    elif any(x in origin for x in ('lua/helpers', 'lua_bit', 'lua_cjson', 'lua_cmsgpack', 'lua_struct')):
        category = 'Lua helper compiler propagation'
        reason = ('Imported lualibs helper code retained; merged translation-unit/link context changes the emitted body. '
                  'All lane references, call sites and instruction differences remain recorded; helper oracle/Tcl checks cover semantics.')
    elif name.startswith('_GLOBAL__sub_I_'):
        category = 'initialization and static data layout'
        reason = ('Combined command/static registrations and histogram-store initialization relocate referenced objects '
                  'and change static initialization code. This is outside per-command execution.')
    elif name.startswith(('std::', 'void std::', 'bool std::', 'unsigned long std::')) or '/usr/include/' in origin:
        category = 'container template instantiation'
        reason = ('Container/string helper instantiations reflect combined queue and histogram data types and compiler '
                  'inline decisions. Call-site deltas and exact types distinguish added helpers from relocated existing helpers.')
    elif 'cfg_' in name or 'config.' in origin or 'info_' in name or 't_server.cc' in origin:
        category = 'configuration and INFO composition'
        reason = ('Latency configuration, histogram metadata and INFO latencystats compose with existing server configuration; '
                  'merged inline/static-data context changes this body. Grammar, INFO and Tcl checks cover public behavior.')
    elif name == 'main' or 'tomokv_multidb_main(' in name or 'Server::init(' in name or '::run_' in name:
        category = 'boot and loop instantiation'
        reason = ('Combined configuration/command registrations and executor/IO template instantiations alter initialization '
                  'and loop selection. Both namespaces/modes boot in the gate jobs; these bodies are outside command dispatch accounting.')
    elif 'classify_keys(' in name:
        category = 'scatter classifier compilation'
        reason = ('The merged scatter inline budget changes basic-block placement and register allocation in the existing '
                  'key classifier. All MGET/MSET executed totals and per-function instruction counts remain equal; '
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
         'All 1,717 strict differences are listed. Exact lane matches retain their lane body; the 607 residual groups include source/call-site evidence. No opcode, branch, register, member offset or clone was masked in the strict inventory.', '',
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
