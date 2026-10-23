"""Keep completed gate receipts; never infer a pass from a missing leg."""
import argparse,hashlib,json,re,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser();parser.add_argument('label');parser.add_argument('log',type=Path)
args=parser.parse_args();text=args.log.read_text()
assert 'GATE(PARTIAL):' in text,'gate has not finished'
run=Path(re.search(r'artifacts: (.+)',text)[1]);dest=ROOT/'docs/bugs5/gate-receipts';dest.mkdir(exist_ok=True)
archive=dest/(args.label+'.tar.gz')
with tarfile.open(archive,'w:gz') as tar:
 for p in sorted(run.rglob('*')):
  if p.is_file() and p.stat().st_size<20_000_000:
   tar.add(p,arcname=str(p.relative_to(run)),recursive=False)
jobs=[]
for p in sorted((run/'jobs').iterdir()):
 d=p/'done';assert d.exists(),p
 jobs.append(dict(job=p.name,done=d.read_text().strip()))
receipt=dict(label=args.label,run=str(run),gate_summary=[l for l in text.splitlines() if l.startswith('GATE(PARTIAL):')],jobs=jobs,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
if (run/'jobs/bugs5').exists():
 witness=[]
 markers={'scancompact':'compact scan guarantee PASS','slowlog_identity':'slowlog historical identity PASS','read_local_lfu':'lane LFU logarithmic probability PASS'}
 for case,marker in markers.items():
  for mode in ('1s','2s'):
   for engine in ('uring','epoll'):
    for atomic in (0,1):
     stem=f'{mode}-{engine}-{atomic}'
     row=run/'jobs/bugs5'/f'{case}-{stem}.log';control=run/'jobs/bugs5'/f'{case}-control-{stem}.log'
     assert row.exists() and control.exists(),(row,control)
     rr=row.read_text();cc=control.read_text()
     witness.append(dict(case=case,mode=mode,engine=engine,atomic=atomic,
                         new_pass=marker in rr,new_assertion='AssertionError' in rr,
                         control_pass=('0 failed' in cc or '0 failures -> PASS' in cc or 'read_local_lane PASS' in cc)))
 receipt['legs']=witness
(dest/(args.label+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
print(args.label,len(jobs),'jobs',receipt['gate_summary'])
