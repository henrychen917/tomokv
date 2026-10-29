set pagination off
python
exec(open('/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/gdbhelp.py').read())
s = srv.dereference()
print('barrier', int(s['snapshot_atomic_barrier_']['_M_i']), 'snapshot phase', s['snapshot_']['phase_']['_M_i'],
      'epoch', int(s['snapshot_']['epoch_']['_M_i']))
for i in range(8):
    print('lane', i, 'head', s['multi_retry_lanes_'][i]['head']['_M_b']['_M_p'])
gdb.execute('thread 1')
f = gdb.newest_frame()
exs = None; ios = None
while f is not None:
    try:
        exs = vec(f.read_var('exs')); ios = vec(f.read_var('ios')); break
    except Exception:
        pass
    try:
        exs = vec(f.read_var('executors')); ios = vec(f.read_var('ios')); break
    except Exception:
        pass
    f = f.older()
print('frame', f.name(), 'exs', len(exs), 'ios', len(ios))
taskt = gdb.lookup_type('tomo::Task')
mst = gdb.lookup_type('tomo::MultiExecState').pointer()
def taskstr(t):
    sc = int(t['scatter'])
    tag = sc & 1
    return 'client=%s op=%d shard=%d scatter=0x%x%s' % (int(t['client']) and int(t['client'].dereference()['id_']), int(t['op_id']) & 0xffffffffffffffff, int(t['shard']), sc, ' MULTI' if tag else '')
def mstate(ptr):
    m = gdb.Value(ptr & ~1).cast(mst).dereference()
    d = m['decision']
    return ('kind=%s attempt=%d phase=%s epoch=%d aborted=%d watch_arrived=%d watch_phase_done=%d lists_pending=%d tasks_pending=%d finalized=%d doomed=%d shards=%s noted=%s age=%d published=%d retired=%d' % (
        m['kind'], int(m['attempt']), d['phase']['_M_i'], int(d['epoch']['_M_i']), int(d['aborted']['_M_base']['_M_i']),
        int(m['watch_arrived']['_M_i']), int(m['watch_phase_done']['_M_base']['_M_i']), int(m['lists_pending']['_M_i']),
        int(m['tasks_pending']['_M_i']), int(m['finalized']['_M_base']['_M_i']), int(m['doomed']),
        [int(x) for x in vec(m['shards'])], [int(x) for x in vec(m['execution_noted'])][:16], int(d['age_ns']), int(m['published']), int(m['retired'])))
for i, ex in enumerate(exs):
    mr = ex['multi_retries_']
    print('ex', i, 'snap_state', ex['snapshot_owner_state_'], 'multi_retries', int(mr['count']), 'fast', int(mr['fast_count']),
          'atomic_deferred', deque_len(ex['atomic_deferred_']), 'xshard_retries', deque_len(ex['xshard_retries_']),
          'ordered_deferred', deque_len(ex['ordered_deferred_']), 'stale', deque_len(ex['stale_tasks_']))
    bl = vec(ex['snapshot_backlogs_'])
    print('     backlogs', [deque_len(b) for b in bl])
    for name in ('fast_head', 'rotation_head'):
        n = mr[name]
        while int(n):
            t = n['task']
            print('     retry', name, taskstr(t))
            n = n['next']
    for name in ('atomic_deferred_', 'xshard_retries_', 'ordered_deferred_'):
        for t in deque_items(ex[name]):
            print('    ', name, taskstr(t))
    for k, b in enumerate(bl):
        for t in deque_items(b):
            print('     backlog', k, taskstr(t))
shards = vec(s['shards_'])
keyq = gdb.lookup_type('tomo::TxnKeyQueue')
strt = gdb.lookup_type('std::string')
for i, u in enumerate(shards):
    sh = uptr(u).dereference()
    wr = sh['watch_reservations_']
    n = int(wr['_M_h']['_M_element_count'])
    nw = int(sh['watchers_']['_M_h']['_M_element_count'])
    if not n and not nw: continue
    print('shard', i, 'has_watches', int(sh['has_watches_']), 'reservations', n, 'watchers', nw)
    for st in umap_items(wr):
        key = st.cast(strt.pointer()).dereference()
        q = (st + strt.sizeof).cast(keyq.pointer()).dereference()
        held = vec(q['held']); marks = vec(q['marks'])
        print('   key', repr(stdstr(key)), 'held', len(held), 'waiters', int(q['waiters']), 'marks', len(marks))
        for h in held:
            print('      held token', h['token'], 'kind', int(h['entry_kind']), 'unit', int(h['unit_kind']), 'mode', int(h['unit_mode']), 'blocking', int(h['blocking']), 'gen', int(h['writer_generation']))
        for m in marks:
            print('      mark token', m['token'], 'gen', int(m['writer_generation']))
        w = q['head']
        while int(w) != 0:
            e = w['entry']
            print('      waiter token', e['token'], 'unit', int(e['unit_kind']), 'mode', int(e['unit_mode']), 'kind', int(e['entry_kind']))
            w = w['next']
ths = threads()
for t, th in enumerate(ths):
    for c in vec(th['slots_']):
        if int(c) == 0: continue
        cl = c.dereference()
        rob = cl['rob_']
        d = int(rob['dispatch_']['_M_i']); fl = int(rob['flush_']['_M_i'])
        nchunks = rob['chunks_'].type.range()[1] + 1
        ops_per = 64 // nchunks
        print('io %d client %d bp %d rpos %d rlen %d inflight %d recv_armed %d in_active %d serve_pending %d' % (
            t, int(cl['id_']), int(cl['parse_backpressure_']), int(cl['rpos_']), int(cl['rlen_']), d - fl,
            int(cl['recv_armed_']), int(cl['in_active_']), int(cl['serve_pending_'])))
        for k in range(fl, d):
            idx = k & 63
            op = (rob['chunks_'][idx // ops_per] + (idx % ops_per)).dereference()
            spec = op['spec']
            name = spec['name'].string() if int(spec) else None
            zc = int(op['zc_ptr']); zs = int(op['zc_shard'])
            extra = ''
            if zs == -5 and zc:
                extra = mstate(zc)
            print('     op', k, name, 'state', op['state']['_M_i'], 'shard', int(op['shard']), 'zc_shard', zs, extra)
end
