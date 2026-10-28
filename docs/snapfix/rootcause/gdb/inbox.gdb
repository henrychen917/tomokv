set pagination off
python
exec(open('/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/gdbhelp.py').read())
ths = threads()
for t in (6, 7):
    th = ths[t]
    tin = uptr(th['task_in_'])
    q = tin.dereference()['q_']
    lanes = q['lanes_']
    nm = th['task_notify_']['words_']
    words = [int(nm[i]['_M_i']) for i in range(2)]
    print('thread', t, 'notify words', [hex(w) for w in words], 'producers', int(q['producers_']))
    for p in range(int(q['producers_'])):
        c = lanes[p]['consumer']; pr = lanes[p]['producer']
        head = int(c['head']['_M_i']); tail = int(pr['tail']['_M_i']); ret = int(c['retired']['_M_i'])
        if head != tail or ret != head:
            bit = (words[p >> 6] >> (p & 63)) & 1
            print('   lane', p, 'head', head, 'tail', tail, 'retired', ret, 'pending', (tail - head) & 0xffffffff, 'notify_bit', bit)
end
