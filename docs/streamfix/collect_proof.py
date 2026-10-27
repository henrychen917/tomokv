#!/usr/bin/env python3
"""Summarize completed real gate jobs; missing or partial evidence stays visible."""
import collections,gzip,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/streamfix'
PROMOTED=json.loads((DOC/'tcl-promotions.json').read_text())
CASES=dict(trim='STREAM-TRIM-APPROX-LIMIT',xread='XREAD-PLUS-LAST',ranges='XRANGE-EXCLUSIVE-SENTINEL',groupdash='STREAM-GROUP-ID-DASH',claimcount='XAUTOCLAIM-COUNT-RANGE',mpop='MPOP-ARG-ERROR-TEXT')
result={}
for receipt in sorted((DOC/'jobs').glob('*.json')):
    job=json.loads(receipt.read_text())
    item=dict(receipt=str(receipt.relative_to(ROOT)),exit=job['exit'],binary_sha256=job['binary_sha256'],binary_unchanged=job['binary_unchanged'],proof_files_unchanged=job.get('proof_files_unchanged'),summary=job['summary'],seconds=job['seconds'])
    result[receipt.stem]=item
    if 'artifacts' not in job:continue
    folder=Path(job['artifacts'])/'jobs';item['artifacts']=str(folder.parent)
    item['jobs']={}
    for part in sorted(folder.iterdir()):
        if not part.is_dir():continue
        ledger=part/'ledger'
        item['jobs'][part.name]=dict(done=(part/'done').exists(),rows=ledger.read_text().splitlines() if ledger.exists() else [])
    if (folder/'streamfix').exists():
        item['directed']={}
        for case,root in CASES.items():
            legs=[]
            for log in sorted((folder/'streamfix').glob(case+'-db*-*.log')):
                text=log.read_text();lines=text.splitlines()
                legs.append(dict(leg=log.stem,geometry='GEOMETRY ' in text,oracle='ORACLE 7.4.10' in text,passed=bool(lines) and lines[-1]=='PASS '+case,tail=lines[-1][:1000] if lines else '',sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
            item['directed'][root]=dict(expected_legs=24,observed_legs=len(legs),passed=sum(l['passed'] for l in legs),legs=legs)
    for mode in ['1s','2s']:
        summary=folder/'redis_tcl'/('redis-tcl-'+mode)/'summary.json'
        if not summary.exists():continue
        j=json.loads(summary.read_text());rows=[]
        for promotion in PROMOTED:
            name=promotion['name']+' in tests/'+promotion['unit']+'.tcl'
            events=[e for r in j['rows'] for e in r.get('events',[]) if e['test']==name and e['status'] in ['ok','err','skip']]
            rows.append(dict(root=promotion['root'],name=name,events=events))
        item['tcl-'+mode]=dict(binary_sha256=j['binary_sha256'],promoted=rows,files=[{k:r.get(k) for k in ['file','passed','failed','skipped','complete','exit_code','error','setup_errors']} for r in j['rows']])
        target=DOC/'proof-tcl'/receipt.stem/(mode+'.json.gz');target.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(target,'wt') as out:json.dump(j,out)
(DOC/'proof-summary.json').write_text(json.dumps(result,indent=2)+'\n')
for name,item in result.items():
    print(name,item['exit'],item['summary'])
    for root,row in item.get('directed',{}).items():print(' ',root,row['passed'],'/',row['observed_legs'])
    for mode in ['1s','2s']:
        if 'tcl-'+mode in item:
            counts=collections.Counter(e['status'] for row in item['tcl-'+mode]['promoted'] for e in row['events']);print(' ',mode,'promoted:',dict(counts))
