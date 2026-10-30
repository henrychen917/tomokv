#!/usr/bin/env python3
"""Join hash-bound serverless counts; preserve positive and negative deltas."""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/wave10/instructions'


def attribution(name):
    if any(x in name for x in ('ScriptCache', 'eval_header', 'set_global_raw',
                              'run_eval', 'append_lua_result', 'script_execute')):
        return dict(lane='scriptfix2', commits=['370210cfc', 'cdd2c4673'],
                    reason='Case-normalized SHA lookup, shebang flags, protected invocation environment, '
                           'and retained numeric argument storage. Changed signatures/outlined helpers '
                           'move counts between bodies; both signs remain in the per-cell ledger.')
    if 'blocking_cleanup_published' in name:
        return dict(lane='blockfix3', commits=['1bbe8df19', '3697b91df'],
                    reason='Drain published stream-removal readiness before atomic cleanup loses the dispatch marker.')
    if 'r7_parse_and_dispatch' in name:
        return dict(lane='rlfix4 + exec1s-d', commits=['11ae8a977', '18f0ceb8b', '254180158', '1608a4381'],
                    reason='Read-local parser simplification plus regenerated owner-hint addressing; '
                           'the parser subtotal includes work moved out of its hash helper.')
    if any(x in name for x in ('atomic_collapse', 'xshard_cleanup_shard_at', 'atomic_commit_publish')):
        return dict(lane='exec1s-d X2', commits=['96624237a'],
                    reason='Eager retirement invokes bounded existing publication/cleanup at transaction completion.')
    if 'multi_ring_participants' in name:
        return dict(lane='exec1s-d X1/X3', commits=['f893d7432', '2022b5374'],
                    reason='Publish participant work hints and wake registered fused ring owners.')
    if any(x in name for x in ('allocate_participant_state', 'ensure_state_slot', 'prepare_claims',
                              'prepare_local_write_keys', 'prepare_write_key', 'watch_place_unit',
                              'multi_execute_task', 'multi_retire', 'multi_verb', 'assemble_final',
                              'Slice::key_eq', 'Op::key()', 'std::vector<std::vector<')):
        return dict(lane='exec1s-d X5/reuse', commits=['6e1a805ed', '26b64e70a', '5fb8dc7b0'],
                    reason='Sparse participant/namespace storage, enum command classification, and newest-key '
                           'reuse. New small-vector/helper calls replace the headline full-shard allocation/walk.')
    raise ValueError('Unattributed positive body delta: ' + name)


def main():
    pre = json.loads((OUT / 'headline-final/counts.json').read_text())
    post = json.loads((OUT / 'post-final/counts.json').read_text())
    assert pre['fixture_sha256'] == post['fixture_sha256']
    assert pre['tracer_sha256'] == post['tracer_sha256']
    fields = ('namespace', 'command', 'mode', 'batch', 'atomic', 'threshold')
    key = lambda row: tuple(row[x] for x in fields)
    old = {key(row): row for row in pre['rows']}
    assert len(old) == len(post['rows']) == 116
    cells = []
    additions = collections.defaultdict(list)
    for after in post['rows']:
        before = old[key(after)]
        differences = {name: after['functions'].get(name, 0) - before['functions'].get(name, 0)
                       for name in sorted(before['functions'].keys() | after['functions'].keys())}
        differences = {name: value for name, value in differences.items() if value}
        delta = after['total'] - before['total']
        assert sum(differences.values()) == delta
        if after['command'] in ('GET', 'SET', 'INCR'):
            assert delta <= 0, ('added main-command instructions', key(after), delta)
        row = {name: after[name] for name in fields}
        row.update(pre=before['total'], post=after['total'], delta=delta,
                   pre_probe_sha256=before['binary_sha256'], post_probe_sha256=after['binary_sha256'],
                   function_deltas=differences)
        cells.append(row)
        if after['command'].startswith(('EXEC', 'EVAL', 'READLOCAL')):
            for name, value in differences.items():
                if value > 0:
                    additions[name].append(dict(cell=list(key(after)), added=value))
    positive = [dict(function=name, **attribution(name), cells=rows)
                for name, rows in sorted(additions.items())]
    record = dict(definition='Retired native instructions in the production namespace, serverless owner-command '
                  'scope; REP counted once. Excludes fixture code and shared-library calls. Fixed clock and '
                  'fresh initialized fixture for each case. EVAL warms its Lua invocation once outside the '
                  'scope, then measures the second; the other cases execute their specified batch once. '
                  'Exact replies are required. No throughput inference.',
                  placement='EXEC-same repeats one key on shard 0; EXEC-cross uses one key per distinct '
                  'shard. With one INCR child, the cross-labelled placement necessarily has one shard '
                  'and is a degenerate control, not evidence of a cross-shard transaction. Two/four '
                  'children use two/four shards. MGET/MSET use eight keys on eight shards. The two EVAL '
                  'keys are selected on one shard or two distinct shards by actual routing.',
                  fixture_sha256=pre['fixture_sha256'], tracer_sha256=pre['tracer_sha256'],
                  pre_source_build_sha256=pre['production_sha256'], post_sha256=post['production_sha256'],
                  binding_receipts=['../binding-headline-final.json', '../binding-post-final.json'],
                  cells=cells, positive_body_attribution=positive)
    (OUT / 'comparison.json').write_text(json.dumps(record, indent=2) + '\n')
    lines = ['# Serverless command instruction counts', '', record['definition'], '', record['placement'], '',
             'Every positive EXEC/EVAL/read-local body subtotal has lane/commit attribution in '
             '`comparison.json`; negative subtotals are retained too. Function signature changes '
             'can move counts between rows. These are instruction counts, not latency or rate.', '',
             '| Namespace | Command | Mode | Batch/children | Atomic | PRE | POST | Delta |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    lines += [f"| {r['namespace']} | {r['command']} | {r['mode']} | {r['batch']} | {r['atomic']} | "
              f"{r['pre']} | {r['post']} | {r['delta']:+d} |" for r in cells]
    (OUT / 'comparison.md').write_text('\n'.join(lines) + '\n')
    print('paired cells', len(cells), 'positive body attributions', len(positive))


if __name__ == '__main__':
    main()
