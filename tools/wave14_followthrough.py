#!/usr/bin/env python3
"""Repeat the declared correctness jobs after the R7 integration correction."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from wave14 import ROOT, DOC, BUILD, save, sha


def plans(group):
    if group == 'uring':
        bulk = (BUILD/'all-correctness-jobs.txt').read_text().split()
        bulk += ['wave14_functions', 'source_identity']
        result = [dict(tag='merged-final-uring', engine='uring', jobs=bulk)]
        fused = (BUILD/'fused-correctness-jobs.txt').read_text().split()
        for engine in ('uring', 'epoll'):
            names = fused if engine == 'uring' else [
                n for n in fused if not n.startswith(('aof-', 'snapshot-'))]
            result.append(dict(tag='merged-final-fused-'+engine, engine=engine,
                               fused=True, atomic=1, jobs=names+['scriptfix']))
        for engine in ('uring', 'epoll'):
            for fused_mode in (False, True):
                result.append(dict(tag=f'merged-final-script-bounds-a0-{engine}-'+
                    ('1s' if fused_mode else '2s'), engine=engine, fused=fused_mode,
                    atomic=0, jobs=['script_bounds']))
    else:
        result = [dict(tag='merged-final-epoll', engine='epoll',
            jobs=(BUILD/'epoll-correctness-jobs.txt').read_text().split())]
        for engine, databases in [('epoll', 1), ('uring', 16), ('epoll', 16)]:
            result.append(dict(tag=f'merged-final-blockfix4-{engine}-db{databases}',
                engine=engine, databases=databases, jobs=['blockfix4']))
    return result


def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=('uring', 'epoll'))
    args = parser.parse_args()
    group = args.group
    selected = plans(group)
    predecessor = 'merged-uring-consumers' if group == 'uring' else 'merged-epoll'
    plan = dict(wait_for=predecessor, readiness='r7-final-ready.json', plans=selected,
        reason='Repeat all selected jobs after the generated R7 owner correction; '
               'the earlier candidate and every earlier red row remain recorded.')
    save(DOC/('final-'+group+'-plan.json'), plan)
    deadline = time.monotonic() + 12*3600
    while not ((DOC/'jobs'/(predecessor+'.json')).exists() and
               (DOC/'r7-final-ready.json').exists()):
        if time.monotonic() >= deadline:
            raise TimeoutError('final candidate or predecessor did not finalize')
        time.sleep(1)
    ready = json.loads((DOC/'r7-final-ready.json').read_text())
    binary = ROOT/ready['binary']
    assert sha(binary) == ready['sha256']
    results = []
    for item in selected:
        command = ['python3', 'tools/wave14.py', 'jobs', '--tag', item['tag'],
            '--engine', item['engine'], '--jobs', ' '.join(item['jobs']),
            '--binary', str(binary), '--server-cores', '0-15' if group == 'uring' else '24-31',
            '--load-cores', '16-23', '--ports', '20000-20089' if group == 'uring' else '20090-20092']
        if item.get('fused'):
            command.append('--fused')
        env = dict(os.environ, LC_ALL='C')
        if 'atomic' in item:
            env['GATE_TXN_ATOMIC'] = str(item['atomic'])
        if 'databases' in item:
            env['BLOCKFIX4_DATABASES'] = str(item['databases'])
        print('START', item['tag'], flush=True)
        result = subprocess.run(command, cwd=ROOT, env=env)
        results.append(dict(tag=item['tag'], exit_code=result.returncode))
        save(DOC/('final-'+group+'-results.json'), results)
        print('DONE', results[-1], flush=True)
    raise SystemExit(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    main()
