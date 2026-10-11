set auto-load off
python
import gdb,json
out={}
for ns in ('tomo','tomo_db0'):
 for name in ('Op','Client','ThreadCtx','Shard','FlatStore','Rob<64>','AtomicEntry','Config','AtomicScriptIntent','AtomicPendingState','Server','ScatterState','MultiRetryNode','MultiRetryLane'):
  t=gdb.lookup_type(ns+'::'+name)
  out[ns+'::'+name]={'size':t.sizeof,'fields':{f.name:f.bitpos for f in t.fields() if f.name and hasattr(f,'bitpos')}}
print(json.dumps(out))
end
