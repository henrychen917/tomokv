#!/usr/bin/env python3
"""Summarize the complete finite-counter matrix without reporting rates."""
from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import median

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/execfifo3/perf'

def main():
    rows=json.loads((OUT/'results.json').read_text())
    assert len(rows)==378 and all(r['passed'] for r in rows)
    groups=defaultdict(lambda:defaultdict(list))
    for row in rows:
        key=tuple(row[k] for k in ('command','mode','read_local','threads','arm'))
        for event,value in row['values'].items():
            assert value['running_percent']=='100.00'
            groups[key][event].append(float(value['count']))
    summary=[dict(zip(('command','mode','read_local','threads','arm'),key),
                  medians={event:median(values) for event,values in events.items()},
                  blocks=dict(events)) for key,events in groups.items()]
    assert len(summary)==42 and all(len(v)==3 for g in groups.values() for v in g.values())
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    events=list(summary[0]['medians'])
    with (OUT/'medians.csv').open('w') as stream:
        writer=csv.writer(stream,lineterminator='\n')
        writer.writerow(['command','mode','read_local','threads','arm',*events])
        for row in summary:
            writer.writerow([row[k] for k in ('command','mode','read_local','threads','arm')]+
                            [row['medians'][event] for event in events])
    lines=['# Finite perf counter results','',
           'Three blocks, 8,192 turns × 32 commands per owner; 378 counter runs. '
           'All counters ran at 100%. The two-owner fixture uses disjoint shards '
           'on CPUs 96 and 104 (different L3 domains). No EXEC, sockets or load generator.', '',
           'Counts include fixture setup, allocation, exact-reply checks and teardown. '
           'They are not isolated command costs or server throughput. The parser cells '
           'also execute and check the dispatched commands after parsing. All cells '
           'use the single-database namespace; both namespaces have linked instruction/access proofs.', '',
           'Every entry below is PRE / FIFO / POST, in millions of events. '
           'Do not infer zero regression from restored instruction counts: the '
           'cycle medians are not uniformly at PRE, and these short process-level '
           'fixtures do not replace the maintainer’s matched-load cells.', '',
           '| Fixture | Mode | Read-local | Owners | Instructions (M) | Cycles (M) |',
           '| --- | --- | ---: | ---: | --- | --- |']
    keys=list(dict.fromkeys(key[:-1] for key in groups))
    for key in keys:
        values=[]
        for event in ('instructions:u','cycles:u'):
            values.append(' / '.join(f'{median(groups[(*key,arm)][event])/1e6:.3f}'
                                     for arm in ('PRE','FIFO','POST-final')))
        lines.append('| '+' | '.join(map(str,(*key,*values)))+' |')
    lines+=['','The [complete CSV](medians.csv) and [block counts](summary.json) include '
            'L1 load misses, L2 data-request misses, generic LLC misses, instruction-cache '
            'misses, remote-CCX cache fills, local-CCX fills and requests to obtain exclusive state. '
            'The last three are the available coherence-related proxies used here; they '
            'do not identify dirty HITM transfers. Their process-level counts include '
            'startup and cannot attribute a transfer to a FIFO cache line.', '',
            'The exact commands, event runtimes, probe hashes, CSVs and assertion logs '
            'are retained in [results.json](results.json). Event descriptions and the '
            'two CPUs’ L3 topology are recorded in the parent directory.']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':main()
