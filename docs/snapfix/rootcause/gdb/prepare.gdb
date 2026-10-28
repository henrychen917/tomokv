set pagination off
python
exec(open('/home/user/Projects/cx-snapfix/docs/snapfix/rootcause/gdb/gdbhelp.py').read())
s = srv.dereference()
m = s['snapshot_']
print('manager phase', m['phase_']['_M_i'], 'epoch', int(m['epoch_']['_M_i']),
      'ready', int(m['ready_owners_']['_M_i']), 'frozen', int(m['frozen_owners_']['_M_i']),
      'marked', int(m['marked_owners_']['_M_i']), 'finished', int(m['finished_owners_']['_M_i']),
      'executor_count', int(m['executor_count_']), 'writer_tid', int(m['writer_tid_']['_M_i']),
      'barrier', int(s['snapshot_atomic_barrier_']['_M_i']))
gdb.execute('thread 1')
f = gdb.newest_frame()
exs = None
while f is not None:
    for name in ('exs', 'executors'):
        try:
            exs = vec(f.read_var(name)); break
        except Exception:
            pass
    if exs is not None: break
    f = f.older()
print('executors', len(exs))
for i, ex in enumerate(exs):
    print('ex', i, 'state', ex['snapshot_owner_state_'], 'epoch', int(ex['snapshot_epoch_']),
          'prepare_cursor', int(ex['snapshot_prepare_cursor_']),
          'xshard_retries', deque_len(ex['xshard_retries_']), 'ordered_deferred', deque_len(ex['ordered_deferred_']),
          'atomic_deferred', deque_len(ex['atomic_deferred_']),
          'backlogs', [deque_len(b) for b in vec(ex['snapshot_backlogs_'])])
    self_ = ex['self_'].dereference()
    for sp in vec(self_['shards_']):
        sh = sp.dereference()
        st = sh['store_']
        print('    shard', int(sh['id_']), 'prepared', int(st['snapshot_prepared_']), 'active', int(st['snapshot_active_']),
              'cap0', int(st['cap_'][0]), 'cap1', int(st['cap_'][1]), 'live0', int(st['live_'][0]), 'live1', int(st['live_'][1]),
              'rehash_pos', int(st['rehash_pos_']), 'tab1', st['tab_'][1])
end
