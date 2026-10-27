#!/usr/bin/env python3
"""Require complete lane proof, keeping the maintainer-owned count refusal explicit."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];DOC=ROOT/'docs/streamfix'
proof=json.loads((DOC/'proof-summary.json').read_text())
def need(value,message):
    if not value:raise AssertionError(message)
for name,passes in [('final-directed',24),('controls-pre',0),('controls-pad',0),('controls-mutant',0)]:
    item=proof[name];need(item['binary_unchanged'],name+' binary changed')
    need(item['exit']==(0 if passes else 1),name+' exit')
    need(len(item['directed'])==6,name+' six roots')
    for root,row in item['directed'].items():
        need(row['observed_legs']==24 and row['passed']==passes,(name,root,row['observed_legs'],row['passed']))
        need(all(r['geometry'] and r['oracle'] for r in row['legs']),(name,root,'geometry/oracle'))
for mode in ['1s','2s']:
    good=proof['final-quiet-recheck']['tcl-'+mode]['promoted']
    bad=proof['controls-mutant']['tcl-'+mode]['promoted']
    need(len(good)==21 and all(r['events'] and all(e['status']=='ok' for e in r['events']) for r in good),(mode,'promoted tests'))
    for root in {r['root'] for r in good}:
        need(any(e['status']=='err' for r in bad if r['root']==root for e in r['events']),(mode,root,'no named mutant failure'))
# Every owning main job must finish green, except jobs explicitly superseded by
# the complete isolated recheck after the final test expectation edit.
rechecked={'redis_tcl','feature-split-0','feature-split-1','feature-armed-0','feature-armed-1'}
for name,job in proof['final-main']['jobs'].items():
    if name in rechecked:continue
    need(job['done'] and not any(r.startswith('FAIL') for r in job['rows']),('main job',name))
quiet=proof['final-quiet-recheck']
need(quiet['binary_unchanged'] and quiet['proof_files_unchanged'],'quiet proof source/binary changed')
for name,job in quiet['jobs'].items():
    need(job['done'],('unfinished quiet job',name))
    if name!='abba_selftest':need(not any(r.startswith('FAIL') for r in job['rows']),('quiet job',name))
for name in ['final-differ-uring','final-differ-epoll']:
    item=proof[name];need(item['exit']==0 and item['binary_unchanged'],name)
    need(all(j['done'] and not any(r.startswith('FAIL') for r in j['rows']) for j in item['jobs'].values()),name+' job completion')
checks=json.loads((DOC/'quiet-rechecks.json').read_text())
need(checks['checks'][0]['exit']==0,'standalone gates_test.py must pass')
receipt=json.loads((DOC/'build/receipt.json').read_text())
need(len(receipt['freshness'])==49 and all(r['exit']==0 for r in receipt['builds']+receipt['freshness']),'production/freshness')
counts=json.loads((DOC/'instructions/comparison.json').read_text())
need(len(counts)==72 and all(r['delta']==0 and r['functions_equal'] and r['external_calls_equal'] for r in counts),'command-scope counts')
pad=json.loads((DOC/'pad-a.json').read_text())
for arm in ['PRE','POST','PAD-A']:
    record=pad['arms'][arm];need(hashlib.sha256(Path(record['path']).read_bytes()).hexdigest()==record['sha256'],arm+' digest')
need(pad['post_text']==pad['pad_text'],'PAD aggregate text')
need('EXPECT_FULL=815, fixture=829, source declarations=829' in (DOC/'ledger-fixture.log').read_text(),'explicit owner count refusal')
unit_log=(DOC/'abba-selftest.log').read_text()
need(unit_log.count('RECEIPT FIXTURE REFUSED:')==1 and 'EXPECT_FULL=815, fixture=829, source declarations=829' in unit_log,'ABBA owner count refusal')
need('\nFAILED (' not in unit_log and '\nFAIL: ' not in unit_log and '\nERROR: ' not in unit_log,'additional self-test assertion failure')
print('Lane proof verified; the full receipt/ABBA-selftest count refusal remains an owner action, not a green full gate.')
