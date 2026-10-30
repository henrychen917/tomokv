set pagination off
python
exec(open('/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/gdbhelp.py').read())
shards = vec(srv['shards_'])
print('nshards', len(shards))
keyq = gdb.lookup_type('tomo::TxnKeyQueue')
strt = gdb.lookup_type('std::string')
for i, u in enumerate(shards):
    s = uptr(u).dereference()
    wr = s['watch_reservations_']
    n = int(wr['_M_h']['_M_element_count'])
    nw = int(s['watchers_']['_M_h']['_M_element_count'])
    print('shard', i, 'has_watches', int(s['has_watches_']), 'reservations', n, 'watchers', nw)
    for st in umap_items(wr):
        key = st.cast(strt.pointer()).dereference()
        q = (st + strt.sizeof).cast(keyq.pointer()).dereference()
        held = vec(q['held'])
        marks = vec(q['marks'])
        print('   key', repr(stdstr(key)), 'held', len(held), 'waiters', int(q['waiters']), 'marks', len(marks))
        for h in held:
            print('      held token', h['token'], 'kind', int(h['entry_kind']), 'unit', int(h['unit_kind']), 'mode', int(h['unit_mode']), 'blocking', int(h['blocking']), 'epoch', h['epoch'].dereference() if int(h['epoch']) else None, 'aborted', h['aborted'].dereference()['_M_base']['_M_i'] if int(h['aborted']) else None)
        for m in marks:
            print('      mark token', m['token'], 'kind', int(m['entry_kind']), 'gen', int(m['writer_generation']), 'writer', m['writer'])
        w = q['head']
        while int(w) != 0:
            e = w['entry']
            print('      waiter token', e['token'], 'unit', int(e['unit_kind']), 'mode', int(e['unit_mode']), 'kind', int(e['entry_kind']))
            w = w['next']
end
