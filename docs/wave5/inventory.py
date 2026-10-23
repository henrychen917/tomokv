#!/usr/bin/env python3
"""Independent additive source/fixture accounting, including quick collector positions."""
from collections import Counter
import json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tests'))
import gate_ledger_fixture as fixture
BASE='a7dfb9d23';LANES='txnfix bugs5 compat3 trackfix fliplisten netfix iofix'.split()
def source(ref):return subprocess.check_output(['git','show',ref+':tests/gate.sh'],text=True,cwd=ROOT)
def labels(s,quick=False):
 if quick:
  first=s.index('\nstart_workers\n');cut=s.index('\nif [ "$TIER" = quick ]; then',first);last=s.index('\n# Every worker has reaped',cut)
  s=s[:cut]+s[last:]
 return fixture.source_labels(s)
base=source(BASE);gate=(ROOT/'tests/gate.sh').read_text();rows=[]
expected={q:Counter(labels(base,q)) for q in (False,True)}
for lane in LANES:
 s=source('cx-'+lane);row=dict(lane=lane,tip=subprocess.check_output(['git','rev-parse','cx-'+lane],text=True,cwd=ROOT).strip())
 for q,key in [(True,'quick'),(False,'full')]:
  old,new=Counter(labels(base,q)),Counter(labels(s,q));added=new-old;removed=old-new
  expected[q].update(added);expected[q].subtract(removed)
  row[key]=dict(delta=sum(new.values())-sum(old.values()),added=dict(added),removed=dict(removed))
 rows.append(row)
for q in (False,True):assert Counter(labels(gate,q))==expected[q]
want=json.loads((ROOT/fixture.FIXTURE).read_text())['labels'];assert Counter(want)==expected[False]
constants=re.findall(r'^EXPECT_(?:QUICK|FULL)=\d+',gate,re.M)
assert constants==re.findall(r'^EXPECT_(?:QUICK|FULL)=\d+',base,re.M)
result=dict(base=BASE,protected_constants=constants,base_quick=len(labels(base,True)),base_full=len(labels(base)),
 required_quick=len(labels(gate,True)),required_full=len(labels(gate)),fixture_count=len(want),lanes=rows,
 collectors=[dict(line=i,text=line) for i,line in enumerate(gate.splitlines(),1) if line.startswith('collect_job ') or line=='if [ "$TIER" = quick ]; then'])
(ROOT/'docs/wave5/row-inventory.json').write_text(json.dumps(result,indent=2)+'\n')
print({k:v for k,v in result.items() if k not in ('lanes','collectors')})
