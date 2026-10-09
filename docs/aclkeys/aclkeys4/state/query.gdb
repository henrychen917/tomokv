set pagination off
set confirm off
set breakpoint pending on
set print elements 20
set print pretty on
set debuginfod enabled off
python
import gdb
class Wake(gdb.Breakpoint):
    def stop(self):
        key=gdb.parse_and_eval('key')
        if key.string(length=int(gdb.parse_and_eval('key_len'))) != 'block:aclkeys': return False
        if gdb.parse_and_eval('ns').is_optimized_out: return False
        print('ACLKEYS4 PUBLISH')
        for expr in ('ns','hash','shard.id_','shard.blocking_waiters_','shard.blocking_dirty_'):
            try: print(expr, gdb.parse_and_eval(expr))
            except gdb.error as e: print(e)
        sh=gdb.parse_and_eval('shard')
        reg=sh['blocking_registry_'].cast(gdb.lookup_type('tomo::(anonymous namespace)::BlockingRegistry').pointer()).dereference()
        for _,queue in gdb.default_visualizer(reg['queues_']).children():
            print('QUEUE',queue['key'], 'ns',queue['ns'], 'hash',queue['hash'])
            for _,entry in gdb.default_visualizer(queue['waiters']).children():
                state=entry['state'].dereference()
                server=state['server'].dereference()
                current=server['databases_']['current_']['_M_b']['_M_p']
                print('DATABASE MAP', current.dereference() if int(current) else 'identity')
                for _,ptr in gdb.default_visualizer(server['shards_']).children():
                    item=next(gdb.default_visualizer(ptr).children())[1].dereference()
                    print('SHARD',item['id_'],'waiters',item['blocking_waiters_'],'dirty',item['blocking_dirty_'])
                for field in ('logical_db','phase','active_tasks','pending','keys'):
                    print('STATE',field,state[field])
        class After(gdb.FinishBreakpoint):
            def stop(self):
                print('ACLKEYS4 AFTER PUBLISH waiters', sh['blocking_waiters_'], 'dirty', sh['blocking_dirty_'])
                return False
        After(internal=True)
        return False
Wake('tomo::blocking_publish_key')
end
handle SIGTERM nostop noprint pass
run
