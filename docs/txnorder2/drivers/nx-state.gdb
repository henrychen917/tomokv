set $server = 'tomo_db0::(anonymous namespace)::g_server'
python
import gdb
s=gdb.parse_and_eval('$server').dereference()
print('NX OWNER STATE')
print(s['multi_retry_lanes_'])
for thread in gdb.selected_inferior().threads():
 thread.switch()
 frame=gdb.newest_frame()
 while frame:
  if 'IoLoop::run_loop' in (frame.name() or ''):
   io=frame.read_var('this').dereference()
   ex=io['fused_executor_'].dereference()
   print('OWNER',ex['self_'].dereference()['id_'])
   for field in ('atomic_deferred_','xshard_retries_','ordered_deferred_','multi_retries_'):
    print(field,ex[field])
   break
  frame=frame.older()
def children(v):
 p=gdb.default_visualizer(v)
 return list(p.children()) if p else []
for n,owned in children(s['shards_']):
 parts=children(owned)
 if not parts:continue
 ptr=parts[0][1]
 if ptr.type.code!=gdb.TYPE_CODE_PTR:continue
 sh=ptr.dereference()
 print('SHARD',n,ptr)
 print('RESERVATIONS',sh['watch_reservations_']['_M_h']['_M_element_count'])
 entries=[]
 table=sh['watch_reservations_']['_M_h']
 value_type=table.type.template_argument(1)
 node=table['_M_before_begin']['_M_nxt']
 while int(node):
  pair=(node.cast(gdb.lookup_type('char').pointer())+node.type.target().sizeof).cast(value_type.pointer()).dereference()
  entries.extend([('key',pair['first']),('claims',pair['second'])])
  node=node.dereference()['_M_nxt']
 for j in range(1,len(entries),2):
  print('KEY', entries[j-1][1])
  for _,claim in children(entries[j][1]):
   print('CLAIM',claim)
   token=claim['token']
   if int(claim['unit_kind'])==2:
    group=token.cast(gdb.lookup_type('tomo_db0::ScatterState').pointer()).dereference()
    print('GROUP',token,group)
    print('ATTEMPT',group['group_attempt_storage'].dereference())
    for i in range(int(group['nsub'])): print('SHARDGROUP',group['groups'][i])
    for i in range(int(group['owner_slots'])): print('OWNERPROGRESS',i,group['owner_record_refs'][i])
   elif int(claim['unit_kind'])==1:
    unit=token.cast(gdb.lookup_type('tomo_db0::MultiExecState').pointer()).dereference()
    print('EXEC',token,unit)
end
