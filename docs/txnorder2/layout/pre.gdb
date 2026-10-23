set pagination off
set auto-load off
python
import gdb,json
rows={}
for ns in ('tomo','tomo_db0'):
 for name in ['Op', 'Client', 'ThreadCtx', 'Shard', 'FlatStore', 'AtomicEntry', 'Config', 'Rob<64>', 'ScatterState', 'Shard::WatchReservation', 'AtomicScriptIntent', 'AtomicPendingState', 'Server', 'MultiWriteKey']:
  t=gdb.lookup_type(ns+'::'+name)
  fields={f.name:dict(bitpos=int(f.bitpos),size=int(f.type.sizeof)) for f in t.fields() if hasattr(f,'bitpos')}
  rows[ns+'::'+name]=dict(size=int(t.sizeof),fields=fields)
json.dump(rows,open('/home/user/Projects/cx-txnfix/docs/txnorder2/layout/pre.json','w'),indent=2)
end
