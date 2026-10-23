set pagination off
set print elements 16
set max-value-size unlimited
python
import gdb
s=gdb.parse_and_eval("'tomo_db0::(anonymous namespace)::g_server'").dereference()
def children(v):return list(gdb.default_visualizer(v).children())
for _,t in children(s['threads_']):
 t=children(t)[0][1].dereference()
 if int(t['id_']) not in (0,7):continue
 print('OWNER',t['id_'],t['task_notify_'])
 q=children(t['task_in_'])[0][1].dereference()
 print(q)
end
