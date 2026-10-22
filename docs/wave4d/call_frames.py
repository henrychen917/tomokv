"""DWARF inline chains at all changed direct-call sites; references stay frozen."""
import gzip,json,subprocess
from pathlib import Path
DOC=Path(__file__).resolve().parent
refs=json.load(gzip.open(DOC/'call-sites.json.gz','rt'))
diffs=json.loads((DOC/'call-differences.json').read_text())
rows=[]
for arm,data in refs.items():
 sites=[]
 for row in diffs:
  if arm not in (row['reference'],row['candidate']):continue
  targets={d['target'] for d in row['added']+row['removed'] if d['kind']=='call'}
  for b in data['groups'][row['name']]:
   for s in b['calls']:
    if s['kind']=='call' and s['target'] in targets:
     sites.append(dict(arm=arm,name=row['name'],target=s['target'],offset=s['offset'],address=int(b['address'],16)+int(s['offset'],16)))
 sites=list({(s['name'],s['offset']):s for s in sites}.values())
 if not sites:continue
 output=subprocess.check_output(['addr2line','-a','-f','-i','-C','-e',data['binary']],input='\n'.join(hex(s['address']) for s in sites)+'\n',text=True)
 frames={};current=None
 for line in output.splitlines():
  if line.startswith('0x'):current=int(line,16);frames[current]=[]
  else:frames[current].append(line)
 for site in sites:
  lines=frames[site['address']];site['frames']=[dict(function=a,source=b) for a,b in zip(lines[::2],lines[1::2])];site['address']=hex(site['address']);rows.append(site)
(DOC/'call-frames.json').write_text(json.dumps(rows,indent=2)+'\n')
print(len(rows),'changed-call-site inline chains')
