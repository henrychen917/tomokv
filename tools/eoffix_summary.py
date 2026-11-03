#!/usr/bin/env python3
"""Fold retained receipts without converting a failed or incomplete run to a pass."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/eoffix'


def main():
    jobs, tcl, loops = [], [], []
    arms = {r['sha256']:r['arm'] for r in json.loads((DOC/'arms-final.json').read_text())}
    for path in sorted(DOC.glob('*.json')):
        record = json.loads(path.read_text())
        if not isinstance(record, dict) or 'exit_code' not in record or 'directory' not in record:
            continue
        run = Path(record['directory'])
        arm = arms.get(record['native_sha256'], 'intermediate')
        failures = [line for ledger in record.get('ledgers', {}).values()
                    for line in ledger.splitlines() if line.startswith('FAIL\t')]
        jobs.append(dict(tag=path.stem, arm=arm, engine=record['engine'], jobs=record['jobs'],
                         binary_sha256=record['native_sha256'], exit_code=record['exit_code'],
                         failures=failures, captures=record.get('captures', [])))
        if record['jobs'] == 'txnorder-fused-0':
            log = run / 'jobs/txnorder-fused-0/txnorder-2s-0.txt'
            text = log.read_text() if log.exists() else ''
            loops.append(dict(tag=path.stem, arm=arm, engine=record['engine'], exit_code=record['exit_code'],
                              aof_pass='\nPASS d\n' in text, exact_reload='"exact": true' in text,
                              failures=re.findall(r'^FAIL .+$', text, re.M),
                              captures=record.get('captures', []),
                              build_done=(run/'jobs/production_units/done').read_text().strip(),
                              shutdown_failed='TIMEOUT after 30s' in
                              (run/'jobs/txnorder-fused-0/output.log').read_text()))
        for summary in sorted(run.glob('jobs/redis_tcl/*/summary.json')):
            result = json.loads(summary.read_text())
            errors = []
            for row in result['rows']:
                named = [dict(test=e['test'], data=e['data']) for e in row['events']
                         if e['status'] == 'err' and e['test']]
                if row['error'] or named:
                    log = summary.parent / row['file'] / 'suite.log'
                    errors.append(dict(file=row['file'], complete=row['complete'], passed=row['passed'],
                                       error=row['error'], named=named,
                                       tcl_timeout=log.exists() and 'TIMEOUT' in log.read_text()))
            fairness = [e for row in result['rows'] for e in row['events']
                        if 'fairness' in e.get('test', '').lower() and e['status'] in ('ok', 'err')]
            tcl.append(dict(tag=path.stem, arm=arm, engine=record['engine'], mode=result['mode'],
                            files=len(result['rows']), errors=errors,
                            fairness=[dict(test=e['test'], status=e['status']) for e in fairness]))
    # The first PRE full Tcl run predates the recorder's final receipt format.
    initial = ROOT/'build/gate-run.7676EW/jobs/redis_tcl'
    for summary in sorted(initial.glob('*/summary.json')):
        result = json.loads(summary.read_text())
        tcl.append(dict(tag='pre-tcl', arm='PRE', engine='epoll', mode=result['mode'], files=len(result['rows']),
                        errors=[dict(file=row['file'], complete=row['complete'], error=row['error'],
                                     named=[dict(test=e['test'], data=e['data']) for e in row['events']
                                            if e['status']=='err' and e['test']])
                                for row in result['rows'] if row['error']]))
    output = dict(jobs=jobs, transaction_loops=loops, tcl=tcl)
    (DOC/'validation-summary.json').write_text(json.dumps(output, indent=2)+'\n')
    print('completed gate receipts', len(jobs), 'Tcl mode legs', len(tcl), 'transaction loops', len(loops))
    for arm in ['PRE','POST']:
        for engine in ['epoll','uring']:
            rows=[r for r in loops if r['engine']==engine and r['arm']==arm and
                  r['build_done'].split('\t')[0]=='0']
            print(arm,engine,'complete loops',len(rows),'green',sum(r['exit_code']==0 for r in rows),
                  'AOF passes',sum(r['aof_pass'] and r['exact_reload'] for r in rows),
                  'shutdown timeouts',sum(r['shutdown_failed'] for r in rows))


if __name__ == '__main__':
    main()
