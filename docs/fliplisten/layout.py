"""Read DWARF layouts without starting either executable."""
import json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
types=['tomo::Server','tomo::IoLoop','tomo::Op','tomo::Client','tomo::ThreadCtx',
       'tomo::Shard','tomo::FlatStore','tomo::Rob<64>','tomo::AtomicEntry','tomo::Config']
code="""import gdb,json
names=%r
rows={}
for n in names:
 t=gdb.lookup_type(n)
 rows[n]={'size':t.sizeof,'fields':{f.name:f.bitpos for f in t.fields() if f.name and hasattr(f,'bitpos')}}
print(json.dumps(rows))
"""%types
out=ROOT/'build/fliplisten/layout.gdb';out.write_text('python\n'+code+'\nend\n')
arms={}
for name in ['tomokv-PRE','tomokv']:
 text=subprocess.check_output(['gdb','-nx','-q','-batch',str(ROOT/'build'/name),'-x',str(out)],text=True)
 arms[name]=json.loads(text)
before,after=arms.values();result={}
for name in types:
 a,b=before[name],after[name]
 changed={f:(pos,b['fields'].get(f)) for f,pos in a['fields'].items() if b['fields'].get(f)!=pos}
 result[name]={'pre_size':a['size'],'post_size':b['size'],'moved_existing_fields':changed,
               'added_fields':{f:p for f,p in b['fields'].items() if f not in a['fields']}}
 assert not changed and a['size']==b['size'],result[name]
(ROOT/'docs/fliplisten/layout.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
