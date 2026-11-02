"""Read-only GDB snapshot of the owned witness process; no inferior calls."""
import gdb
import json


def children(value):
    return [v for _, v in gdb.default_visualizer(value).children()]


def atom(value):
    for field in ('_M_i', '_M_base', '_M_p'):
        try:
            return atom(value[field])
        except gdb.error:
            pass
    return int(value)


server = gdb.parse_and_eval("'" + namespace + "::(anonymous namespace)::g_server'").dereference()
result = {'stage': str(server['flip_stage_']), 'clients': []}
for tid, ptr in enumerate(children(server['threads_'])):
    thread = children(ptr)[0].dereference()
    for cp in children(thread['clients_']):
        c = cp.dereference()
        row = {'io': tid}
        for field in ('id_', 'send_inflight_', 'serve_pending_', 'barrier_owners_',
                      'atomic_groups_io_', 'connection_flags_', 'tls_slot_', 'obuf_bytes_',
                      'retire_queued_', 'closing_', 'wsent_', 'fill_'):
            row[field] = atom(c[field])
        row['rob'] = str(c['rob_'])
        rob = c['rob_']
        first, end = atom(rob['flush_']), atom(rob['dispatch_'])
        if first != end:
            head = rob['chunks_'][(first & 63) // 8][(first & 63) % 8]
            row['head_state'] = str(head['state'])
            if int(head['zc_shard']) == -4 and int(head['zc_ptr']):
                block = head['zc_ptr'].cast(gdb.lookup_type(namespace + '::BlockingState').pointer()).dereference()
                row['blocked_phase'] = str(block['phase'])
                row['blocked_active_tasks'] = atom(block['active_tasks'])
                row['blocked_refs'] = atom(block['refs'])
        row['buffers'] = str(c['buf_'])
        row['segments'] = str(c['segments_'])
        result['clients'].append(row)
print('FLIPFIX7_SNAPSHOT ' + json.dumps(result))
