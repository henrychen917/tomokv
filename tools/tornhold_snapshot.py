"""Read-only GDB witness of a selected connection's live hold; no inferior calls."""
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


found = []
for namespace in ('tomo', 'tomo_db0'):
    pointer = gdb.parse_and_eval("'" + namespace + "::(anonymous namespace)::g_server'")
    if not int(pointer):
        continue
    server = pointer.dereference()
    for tid, pointer in enumerate(children(server['threads_'])):
        thread = children(pointer)[0].dereference()
        for pointer in children(thread['clients_']):
            client = pointer.dereference()
            if atom(client['id_']) != identity:
                continue
            rob = client['rob_']
            hold = rob['plain_hold_']
            found.append(dict(io=tid, identity=identity,
                              dispatch=atom(rob['dispatch_']), flush=atom(rob['flush_']),
                              **{field: int(hold[field]) for field in
                                 ('a_slot', 'a_end', 'b_slot', 'b_end')}))
assert len(found) == 1, found
print('TORNHOLD_SNAPSHOT ' + json.dumps(found[0]))
