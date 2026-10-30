import gdb

def vec(v):
    start = v['_M_impl']['_M_start']
    finish = v['_M_impl']['_M_finish']
    n = int(finish - start)
    return [start[i] for i in range(n)]

def uptr(u):
    t = u.type.strip_typedefs().template_argument(0)
    return u.address.cast(t.pointer().pointer()).dereference()

def umap_items(m):
    # libstdc++ unordered_map: iterate singly-linked node list from _M_before_begin
    h = m['_M_h']
    node = h['_M_before_begin']['_M_nxt']
    vt = m.type.strip_typedefs().template_argument(0)
    vt2 = m.type.strip_typedefs().template_argument(1)
    pair_t = gdb.lookup_type('std::pair<%s const, %s>' % (vt, vt2)) if False else None
    out = []
    while int(node) != 0:
        # node layout: _Hash_node_base{_M_nxt} then value storage
        nodetype = gdb.lookup_type('std::__detail::_Hash_node_base').pointer()
        storage = (node.cast(gdb.lookup_type('char').pointer()) + 8)
        out.append(storage)
        node = node['_M_nxt']
    return out

def stdstr(s):
    p = s['_M_dataplus']['_M_p']
    n = int(s['_M_string_length'])
    return p.string(length=n) if n else ''

srv = gdb.parse_and_eval("'tomo::(anonymous namespace)::g_server'")

def deque_items(d):
    impl = d['_M_impl']
    start = impl['_M_start']
    finish = impl['_M_finish']
    out = []
    cur = start['_M_cur']; last = start['_M_last']; node = start['_M_node']
    elt = d.type.strip_typedefs().template_argument(0)
    bufsz = max(1, 512 // elt.sizeof) if elt.sizeof < 512 else 1
    while True:
        if cur == finish['_M_cur']:
            break
        out.append(cur.dereference())
        cur = cur + 1
        if cur == last:
            node = node + 1
            first = node.dereference()
            cur = first
            last = first + bufsz
    return out

def deque_len(d):
    impl = d['_M_impl']
    s = impl['_M_start']; f = impl['_M_finish']
    elt = d.type.strip_typedefs().template_argument(0)
    bufsz = max(1, 512 // elt.sizeof) if elt.sizeof < 512 else 1
    return int((f['_M_node'] - s['_M_node'] - 1)) * bufsz + int(f['_M_cur'] - f['_M_first']) + int(s['_M_last'] - s['_M_cur'])

def threads():
    return [uptr(t) for t in vec(srv['threads_'])]
