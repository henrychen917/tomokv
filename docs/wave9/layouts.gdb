python
import gdb,json,os
names=['StreamNode','BlockingState','MultiCommand','MultiExecState','Server','MultiRetryLane','ScatterState','Op','Client','ThreadCtx','Shard','FlatStore','Rob<64>','AtomicEntry','Config']
rows={}
for ns in ['tomo','tomo_db0']:
 for name in names:
  key=ns+'::'+name
  try:
   t=gdb.lookup_type(key)
   rows[key]=dict(size=t.sizeof,fields=[dict(name=f.name,bitpos=getattr(f,'bitpos',None),bitsize=f.bitsize,size=f.type.sizeof) for f in t.fields() if not f.is_base_class])
  except Exception as e:rows[key]=dict(error=str(e))
open(os.environ['WAVE9_LAYOUT_OUT'],'w').write(json.dumps(rows,indent=2)+'\n')
end
