set pagination off
python
exec(open('/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/gdbhelp.py').read())
mst = gdb.lookup_type('tomo::MultiExecState').pointer()
decl = gdb.lookup_type('tomo::MultiDecision').pointer()
addrs = [0x7fffd9792300, 0x7fffd9108100, 0x7fffd9399100, 0x7fffd9381900, 0x7fffd9106500, 0x7fffd8e6fe00, 0x7fffd9791500, 0x7fffee272000]
for a in addrs:
    m = gdb.Value(a).cast(mst).dereference()
    print('unit 0x%x client %d kind %s age %d phase %s epoch %d aborted %d watch_failed %d finalized %d' % (a, int(m['client'].dereference()['id_']), m['kind'], int(m['decision']['age_ns']), m['decision']['phase']['_M_i'], int(m['decision']['epoch']['_M_i']), int(m['decision']['aborted']['_M_base']['_M_i']), int(m['watch_failed']['_M_base']['_M_i']), int(m['finalized']['_M_base']['_M_i'])))
    pb = m['place_blockers']['_M_t']['_M_t']
    # unique_ptr<TxnPlaceBlocker[]>
    ptr = m['place_blockers'].address.cast(gdb.lookup_type('tomo::TxnPlaceBlocker').pointer().pointer()).dereference()
    if int(ptr):
        for sid in range(16):
            b = ptr[sid]
            if int(b['epoch']):
                ep = b['epoch']
                owner = gdb.Value(int(ep)).cast(decl).dereference()
                own = owner['owner']
                oc = int(own.dereference()['client'].dereference()['id_']) if int(own) else -1
                print('    blocker shard %d -> epoch@0x%x val %d aborted %d live %d owner-unit 0x%x client %d age %d' % (sid, int(ep), int(ep.dereference()['_M_i']), int(b['aborted'].dereference()['_M_base']['_M_i']), int(ep.dereference()['_M_i'])==0 and not int(b['aborted'].dereference()['_M_base']['_M_i']), int(own), oc, int(owner['age_ns'])))
end
