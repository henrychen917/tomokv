#!/usr/bin/env python3
# Broad command-coverage GATE for THredis. NOT exhaustive — a few representative invocations per command
# family with KNOWN-correct expected results (Part A), PLUS a concurrency race sweep (Part B): many
# connections, each deterministic on its OWN keys with per-connection-VARIED parameters, verifying every
# result. Part B is what catches the class of bug where a command stashes per-invocation state in a
# process global (the SORT desc/alpha race: 19 mis-sorts on the buggy build). Exit 0 = pass, 1 = fail.
# Usage: cmd_gate.py PORT [label]
import socket, sys, time, threading, random
PORT=int(sys.argv[1]); LABEL=sys.argv[2] if len(sys.argv)>2 else '?'
HOST='127.0.0.1'
def conn():
    s=socket.create_connection((HOST,PORT),timeout=15); s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1); return s,s.makefile('rb')
def enc(*a):
    o=[b'*%d\r\n'%len(a)]
    for x in a:
        x=str(x).encode() if not isinstance(x,bytes) else x
        o.append(b'$%d\r\n'%len(x)); o.append(x); o.append(b'\r\n')
    return b''.join(o)
def rr(f):
    ln=f.readline()
    if not ln: raise EOFError
    t=ln[:1]
    if t==b'+': return ln[1:].strip()
    if t==b':': return int(ln[1:])
    if t==b'-': return Exception(ln[1:].strip().decode())
    if t==b'$':
        n=int(ln[1:]); return None if n<0 else f.read(n+2)[:-2]
    if t==b'*':
        n=int(ln[1:]); return None if n<0 else [rr(f) for _ in range(n)]
    if t==b'%':  # RESP3 map (if used)
        n=int(ln[1:]); return [rr(f) for _ in range(2*n)]
    raise ValueError(ln)
def c(s,f,*a): s.sendall(enc(*a)); return rr(f)

fails=[]
def ck(cond,msg):
    if not cond: fails.append(msg)
def eq(got,want,msg): ck(got==want, "%s: got %r want %r"%(msg,got,want))
def B(x): return x.encode() if isinstance(x,str) else x
def lst(r): return [x.decode() if isinstance(x,bytes) else x for x in r] if isinstance(r,list) else r
def rejected(r): return isinstance(r,Exception)  # THredis fail-safe-rejects some cross-shard/txn cmds

def partA():
    s,f=conn(); c(s,f,'FLUSHDB')
    # ---- strings ----
    eq(c(s,f,'SET','s','hello'),b'OK','SET'); eq(c(s,f,'GET','s'),b'hello','GET')
    eq(c(s,f,'APPEND','s',' world'),11,'APPEND'); eq(c(s,f,'STRLEN','s'),11,'STRLEN')
    eq(c(s,f,'GETRANGE','s','0','4'),b'hello','GETRANGE'); eq(c(s,f,'GETRANGE','s','-5','-1'),b'world','GETRANGE-neg')
    c(s,f,'SETRANGE','s','6','WORLD'); eq(c(s,f,'GET','s'),b'hello WORLD','SETRANGE')
    c(s,f,'SET','n','10'); eq(c(s,f,'INCR','n'),11,'INCR'); eq(c(s,f,'INCRBY','n','5'),16,'INCRBY')
    eq(c(s,f,'DECR','n'),15,'DECR'); eq(c(s,f,'DECRBY','n','5'),10,'DECRBY')
    eq(c(s,f,'INCRBYFLOAT','n','2.5'),b'12.5','INCRBYFLOAT')
    eq(c(s,f,'GETSET','g','v1'),None,'GETSET-new'); eq(c(s,f,'GETSET','g','v2'),b'v1','GETSET')
    eq(c(s,f,'SETNX','g','x'),0,'SETNX-exists'); eq(c(s,f,'SETNX','g2','y'),1,'SETNX-new')
    c(s,f,'MSET','a','1','b','2','cc','3'); eq(lst(c(s,f,'MGET','a','b','cc','nope')),['1','2','3',None],'MSET/MGET')
    eq(c(s,f,'GETDEL','g2'),b'y','GETDEL'); eq(c(s,f,'EXISTS','g2'),0,'GETDEL-removed')
    # ---- bitmaps ----
    c(s,f,'DEL','bit'); c(s,f,'SETBIT','bit','7','1'); eq(c(s,f,'GETBIT','bit','7'),1,'SETBIT/GETBIT')
    eq(c(s,f,'BITCOUNT','bit'),1,'BITCOUNT'); c(s,f,'SET','bc','foobar'); eq(c(s,f,'BITCOUNT','bc'),26,'BITCOUNT-str')
    eq(c(s,f,'BITCOUNT','bc','1','1'),6,'BITCOUNT-range'); eq(c(s,f,'BITPOS','bit','1'),7,'BITPOS')
    eq(lst(c(s,f,'BITFIELD','bf','SET','u8','0','255','GET','u8','0')),[0,255],'BITFIELD')
    # ---- hashes ----
    c(s,f,'DEL','h'); eq(c(s,f,'HSET','h','f1','v1','f2','v2'),2,'HSET'); eq(c(s,f,'HGET','h','f1'),b'v1','HGET')
    eq(c(s,f,'HLEN','h'),2,'HLEN'); eq(c(s,f,'HEXISTS','h','f1'),1,'HEXISTS'); eq(c(s,f,'HDEL','h','f2'),1,'HDEL')
    eq(c(s,f,'HINCRBY','h','cnt','5'),5,'HINCRBY'); eq(sorted(lst(c(s,f,'HKEYS','h'))),['cnt','f1'],'HKEYS')
    eq(lst(c(s,f,'HMGET','h','f1','nope')),['v1',None],'HMGET')
    # Large listpack HMGET: reverse-order probes, a miss, and duplicates exercise the one-pass request map.
    hm_fields=['hf%03d'%i for i in range(400)]; hm_values={name:'hv%03d'%i for i,name in enumerate(hm_fields)}
    hm_args=[x for name in hm_fields for x in (name,hm_values[name])]
    c(s,f,'DEL','hmget-lp'); eq(c(s,f,'HSET','hmget-lp',*hm_args),400,'HMGET-listpack-HSET')
    eq(c(s,f,'OBJECT','ENCODING','hmget-lp'),b'listpack','HMGET-listpack-encoding')
    hm_req=hm_fields[::-2]+['hm-missing',hm_fields[17],hm_fields[17]]
    hm_want=[hm_values.get(name) for name in hm_req]
    eq(lst(c(s,f,'HMGET','hmget-lp',*hm_req)),hm_want,'HMGET-listpack-one-pass/order/missing/duplicate')
    # hash field expiry (THredis HFE)
    c(s,f,'HSET','he','x','1'); r=c(s,f,'HEXPIRE','he','100','FIELDS','1','x'); ck(isinstance(r,list) and r[0]==1,'HEXPIRE %r'%r)
    r=c(s,f,'HTTL','he','FIELDS','1','x'); ck(isinstance(r,list) and 0<int(r[0])<=100,'HTTL %r'%r)
    # ---- lists ----
    c(s,f,'DEL','l'); eq(c(s,f,'RPUSH','l','a','b','c'),3,'RPUSH'); eq(c(s,f,'LPUSH','l','z'),4,'LPUSH')
    eq(lst(c(s,f,'LRANGE','l','0','-1')),['z','a','b','c'],'LRANGE'); eq(c(s,f,'LLEN','l'),4,'LLEN')
    eq(c(s,f,'LINDEX','l','1'),b'a','LINDEX'); eq(c(s,f,'LPOP','l'),b'z','LPOP'); eq(c(s,f,'RPOP','l'),b'c','RPOP')
    c(s,f,'LSET','l','0','A'); eq(c(s,f,'LINDEX','l','0'),b'A','LSET'); eq(c(s,f,'LPOS','l','b'),1,'LPOS')
    c(s,f,'RPUSH','l2','1','2','3'); eq(c(s,f,'LMOVE','l2','l3','LEFT','RIGHT'),b'1','LMOVE')
    # ---- sets ----
    c(s,f,'DEL','st'); eq(c(s,f,'SADD','st','a','b','c'),3,'SADD'); eq(c(s,f,'SCARD','st'),3,'SCARD')
    eq(c(s,f,'SISMEMBER','st','a'),1,'SISMEMBER'); eq(sorted(lst(c(s,f,'SMEMBERS','st'))),['a','b','c'],'SMEMBERS')
    eq(lst(c(s,f,'SMISMEMBER','st','a','z')),[1,0],'SMISMEMBER'); eq(c(s,f,'SREM','st','c'),1,'SREM')
    c(s,f,'SADD','s1','a','b','c','d'); c(s,f,'SADD','s2','c','d','e')
    eq(sorted(lst(c(s,f,'SINTER','s1','s2'))),['c','d'],'SINTER'); eq(sorted(lst(c(s,f,'SUNION','s1','s2'))),['a','b','c','d','e'],'SUNION')
    eq(sorted(lst(c(s,f,'SDIFF','s1','s2'))),['a','b'],'SDIFF'); eq(c(s,f,'SINTERCARD','2','s1','s2'),2,'SINTERCARD')
    eq(c(s,f,'SINTERSTORE','sd','s1','s2'),2,'SINTERSTORE'); eq(c(s,f,'SUNIONSTORE','su','s1','s2'),5,'SUNIONSTORE')
    eq(c(s,f,'SDIFFSTORE','sf','s1','s2'),2,'SDIFFSTORE')
    # ---- sorted sets ----
    c(s,f,'DEL','z'); eq(c(s,f,'ZADD','z','1','a','2','b','3','c'),3,'ZADD'); eq(c(s,f,'ZSCORE','z','b'),b'2','ZSCORE')
    eq(c(s,f,'ZCARD','z'),3,'ZCARD'); eq(lst(c(s,f,'ZRANGE','z','0','-1')),['a','b','c'],'ZRANGE')
    eq(lst(c(s,f,'ZREVRANGE','z','0','-1')),['c','b','a'],'ZREVRANGE')
    eq(lst(c(s,f,'ZRANGEBYSCORE','z','2','3')),['b','c'],'ZRANGEBYSCORE'); eq(c(s,f,'ZRANK','z','c'),2,'ZRANK')
    eq(c(s,f,'ZCOUNT','z','1','2'),2,'ZCOUNT'); eq(c(s,f,'ZINCRBY','z','5','a'),b'6','ZINCRBY')
    eq(lst(c(s,f,'ZPOPMIN','z')),['b','2'],'ZPOPMIN')
    c(s,f,'ZADD','z1','1','a','2','b'); c(s,f,'ZADD','z2','3','b','4','c')
    eq(c(s,f,'ZUNIONSTORE','zu','2','z1','z2'),3,'ZUNIONSTORE'); eq(c(s,f,'ZINTERSTORE','zi','2','z1','z2'),1,'ZINTERSTORE')
    eq(lst(c(s,f,'ZDIFF','2','z1','z2')),['a'],'ZDIFF'); eq(lst(c(s,f,'ZMSCORE','z1','a','x')),['1',None],'ZMSCORE')
    # Monotonic skiplist inserts (including equal-score lexical tails) must retain exact sorted order.
    zmono=[('zm%04d'%i,i//3) for i in range(384)]; zmono_args=[x for name,score in zmono for x in (str(score),name)]
    c(s,f,'DEL','zmono'); eq(c(s,f,'ZADD','zmono',*zmono_args),len(zmono),'ZADD-monotonic-append')
    eq(c(s,f,'OBJECT','ENCODING','zmono'),b'skiplist','ZADD-monotonic-skiplist-encoding')
    zmono_want=[x for name,score in zmono for x in (name,str(score))]
    eq(lst(c(s,f,'ZRANGE','zmono','0','-1','WITHSCORES')),zmono_want,'ZADD-monotonic-append-order')
    eq(lst(c(s,f,'ZRANGE','zmono','190','195','WITHSCORES')),zmono_want[380:392],'ZADD-monotonic-span-window')
    eq(c(s,f,'ZRANK','zmono',zmono[-1][0]),len(zmono)-1,'ZADD-monotonic-tail-rank')
    zs,zd='zrs-src','zrs-dst'; zref=[('a',-3),('b',-1),('c',0),('d',1),('e',2),('f',4)]
    def zrs(tail,want,tag):
        exp=[x for m,q in sorted(want,key=lambda p:(p[1],p[0])) for x in (m,str(q))]
        eq(c(s,f,'ZRANGESTORE',zd,zs,*tail),len(want),tag+'-card'); eq(lst(c(s,f,'ZRANGE',zd,'0','-1','WITHSCORES')),exp,tag+'-data')
    c(s,f,'ZADD',zs,*[x for m,q in zref for x in (str(q),m)]); c(s,f,'SET',zd,'stale')
    zrs(('1','4'),zref[1:5],'ZRANGESTORE-index/overwrite'); zrs(('1','3','REV'),zref[::-1][1:4],'ZRANGESTORE-REV')
    zrs(('-inf','(2','BYSCORE'),[p for p in zref if p[1]<2],'ZRANGESTORE-BYSCORE--inf/exclusive')
    zrs(('(0','+inf','BYSCORE','LIMIT','1','2'),[p for p in zref if p[1]>0][1:3],'ZRANGESTORE-BYSCORE-+inf/LIMIT')
    lexref=[(m,7) for m in 'abcdef']; c(s,f,'DEL',zs); c(s,f,'ZADD',zs,*[x for m,q in lexref for x in (str(q),m)])
    zrs(('[b','(f','BYLEX','LIMIT','1','3'),[p for p in lexref if 'b'<=p[0]<'f'][1:4],'ZRANGESTORE-BYLEX/LIMIT')
    eq(c(s,f,'ZRANGESTORE',zd,zs,'99','100'),0,'ZRANGESTORE-empty-card'); eq(c(s,f,'EXISTS',zd),0,'ZRANGESTORE-empty-deletes')
    # ---- streams ----
    c(s,f,'DEL','x'); i1=c(s,f,'XADD','x','*','k','v1'); c(s,f,'XADD','x','*','k','v2'); eq(c(s,f,'XLEN','x'),2,'XADD/XLEN')
    r=c(s,f,'XRANGE','x','-','+'); ck(isinstance(r,list) and len(r)==2,'XRANGE %r'%(r if not isinstance(r,list) else len(r)))
    eq(c(s,f,'XDEL','x',i1.decode() if i1 else ''),1,'XDEL')
    # ---- HLL ----
    c(s,f,'DEL','hll'); c(s,f,'PFADD','hll','a','b','c','a'); v=c(s,f,'PFCOUNT','hll'); ck(isinstance(v,int) and 2<=v<=4,'PFCOUNT %r'%v)
    # ---- geo ----
    c(s,f,'DEL','geo'); c(s,f,'GEOADD','geo','13.361','38.115','Palermo','15.087','37.502','Catania')
    d=c(s,f,'GEODIST','geo','Palermo','Catania','km'); ck(d and 160<float(d)<170,'GEODIST %r'%d)
    r=c(s,f,'GEOSEARCH','geo','FROMMEMBER','Palermo','BYRADIUS','200','km','ASC'); eq(lst(r),['Palermo','Catania'],'GEOSEARCH')
    # ---- generic / key ----
    c(s,f,'SET','k1','v'); eq(c(s,f,'TYPE','k1'),b'string','TYPE'); eq(c(s,f,'EXISTS','k1'),1,'EXISTS')
    c(s,f,'EXPIRE','k1','100'); t=c(s,f,'TTL','k1'); ck(0<int(t)<=100,'TTL %r'%t); eq(c(s,f,'PERSIST','k1'),1,'PERSIST')
    c(s,f,'RENAME','k1','k2'); eq(c(s,f,'GET','k2'),b'v','RENAME'); eq(c(s,f,'COPY','k2','k3'),1,'COPY'); eq(c(s,f,'GET','k3'),b'v','COPY-val')
    eq(c(s,f,'TOUCH','k2','k3'),2,'TOUCH'); eq(c(s,f,'UNLINK','k3'),1,'UNLINK')
    du=c(s,f,'DUMP','k2'); ck(du is not None,'DUMP'); c(s,f,'DEL','k4'); eq(c(s,f,'RESTORE','k4','0',du),b'OK','RESTORE'); eq(c(s,f,'GET','k4'),b'v','RESTORE-val')
    # SORT (the fixed one): numeric + alpha + LIMIT, verify order
    c(s,f,'DEL','so'); c(s,f,'RPUSH','so','3','1','2','5','4')
    eq(lst(c(s,f,'SORT','so')),['1','2','3','4','5'],'SORT'); eq(lst(c(s,f,'SORT','so','LIMIT','0','3')),['1','2','3'],'SORT-LIMIT')
    eq(lst(c(s,f,'SORT','so','DESC','LIMIT','0','2')),['5','4'],'SORT-DESC-LIMIT')
    c(s,f,'DEL','sa'); c(s,f,'RPUSH','sa','banana','apple','cherry')
    eq(lst(c(s,f,'SORT','sa','ALPHA','LIMIT','0','2')),['apple','banana'],'SORT-ALPHA-LIMIT')
    eq(lst(c(s,f,'SORT_RO','so','LIMIT','0','2')),['1','2'],'SORT_RO')
    # A huge COUNT is still wall-time sliced: follow every cursor and verify no key is lost or repeated.
    eq(c(s,f,'FLUSHDB'),b'OK','SCAN-cap-FLUSHDB')
    scan_want={'scan-cap:%04d'%i for i in range(4096)}
    scan_args=[x for key in sorted(scan_want) for x in (key,'v')]
    eq(c(s,f,'MSET',*scan_args),b'OK','SCAN-cap-fixture')
    seen=[]; cur=b'0'; scan_calls=0
    while True:
        r=c(s,f,'SCAN',cur,'COUNT','1000000'); cur=r[0]; scan_calls+=1
        seen.extend(lst(r[1]))
        if cur==b'0': break
        if scan_calls>100000: fails.append('SCAN cap cursor did not terminate'); break
    eq(set(seen),scan_want,'SCAN-cap-full-keyspace')
    eq(len(seen),len(scan_want),'SCAN-cap-no-duplicates')
    ck(scan_calls>1,'SCAN cap did not split huge COUNT (calls=%d)'%scan_calls)
    # ---- transactions ---- THredis rejects MULTI under sharding (would hit the decoy DB); must fail-SAFE.
    ck(rejected(c(s,f,'MULTI')),'MULTI must reject cleanly under sharding (fail-safe, not silent loss)')
    # ---- server/conn ----
    eq(c(s,f,'PING'),b'PONG','PING'); eq(c(s,f,'ECHO','hi'),b'hi','ECHO')
    s.close()

def partB(C=48, iters=12):
    # concurrency race sweep: each conn deterministic on its OWN keys, params VARIED per conn. This is the
    # net that catches process-global command scratch races (the SORT desc/alpha class) across workers.
    def worker(cid):
        try:
            s,f=conn(); r=random.Random(9000+cid); desc=(cid%2==0); alpha=(cid%3==0)
            for it in range(iters):
                # SORT with per-conn DESC/ALPHA (the known race pattern)
                k='rk%d'%cid; c(s,f,'DEL',k)
                vals=[r.randint(0,10**7) for _ in range(150)]; c(s,f,'RPUSH',k,*map(str,vals))
                opt=['SORT',k]+(['ALPHA'] if alpha else [])+(['DESC'] if desc else [])+['LIMIT','0','40']
                got=lst(c(s,f,*opt))
                exp=sorted(map(str,vals)) if alpha else sorted(vals)
                if desc: exp=exp[::-1]
                exp=[str(x) for x in exp[:40]]
                if got!=exp: fails.append('B conn%d it%d SORT desc=%s alpha=%s mismatch'%(cid,it,desc,alpha)); return
                # GETRANGE with per-conn offsets
                sv=('p%d_'%cid)+('y'*(cid%17))+str(it); c(s,f,'SET','g%d'%cid,sv)
                lo=cid%7; hi=lo+4; gr=c(s,f,'GETRANGE','g%d'%cid,str(lo),str(hi))
                if gr!=B(sv)[lo:hi+1]: fails.append('B conn%d it%d GETRANGE mismatch'%(cid,it)); return
                # ZRANGEBYSCORE window per-conn
                zk='z%d'%cid; c(s,f,'DEL',zk)
                for i in range(20): c(s,f,'ZADD',zk,str(i),'m%d'%i)
                a0=cid%5; a1=a0+6; zr=lst(c(s,f,'ZRANGEBYSCORE',zk,str(a0),str(a1)))
                if zr!=['m%d'%i for i in range(a0,a1+1)]: fails.append('B conn%d it%d ZRANGEBYSCORE mismatch'%(cid,it)); return
                # INCR sequence integrity (same-key same-conn order)
                c(s,f,'SET','ic%d'%cid,'0')
                for want in range(1,11):
                    if int(c(s,f,'INCR','ic%d'%cid))!=want: fails.append('B conn%d INCR order'%cid); return
            s.close()
        except Exception as e:
            fails.append('B conn%d exception %r'%(cid,e))
    ts=[threading.Thread(target=worker,args=(i,)) for i in range(C)]
    [t.start() for t in ts]; [t.join() for t in ts]

print('[%s] cmd_gate: Part A (breadth) ...'%LABEL, flush=True)
try: partA()
except Exception as e: fails.append('Part A crashed: %r'%e)
print('[%s] cmd_gate: Part B (concurrency race sweep) ...'%LABEL, flush=True)
try: partB()
except Exception as e: fails.append('Part B crashed: %r'%e)
if fails:
    print("FAIL (%d):"%len(fails))
    for m in fails[:30]: print("  -",m)
    sys.exit(1)
print("PASS — all command-family checks + concurrency race sweep clean")
