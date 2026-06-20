"""Replica of THredis xxh64 (server.c:5173-5245, canonical XXH64 seed=0) for key placement/classify
without the bulk-FIND debug path. worker(key) uses the default 8-worker layout: bucket//512."""
M64=(1<<64)-1
P1=0x9E3779B185EBCA87; P2=0xC2B2AE3D27D4EB4F; P3=0x165667B19E3779F9
P4=0x85EBCA77C2B2AE63; P5=0x27D4EB2F165667C5
def _rotl(x,r): return ((x<<r)|(x>>(64-r)))&M64
def _round(acc,inp):
    acc=(acc+(inp*P2&M64))&M64; acc=_rotl(acc,31); acc=(acc*P1)&M64; return acc
def _merge(acc,val):
    val=_round(0,val); acc^=val; acc=((acc*P1&M64)+P4)&M64; return acc
def xxh64(data: bytes)->int:
    if isinstance(data,str): data=data.encode()
    n=len(data); p=0; end=n
    if n>=32:
        v1=(P1+P2)&M64; v2=P2; v3=0; v4=(0-P1)&M64
        while p+32<=end:
            v1=_round(v1,int.from_bytes(data[p:p+8],'little')); p+=8
            v2=_round(v2,int.from_bytes(data[p:p+8],'little')); p+=8
            v3=_round(v3,int.from_bytes(data[p:p+8],'little')); p+=8
            v4=_round(v4,int.from_bytes(data[p:p+8],'little')); p+=8
        h=(_rotl(v1,1)+_rotl(v2,7)+_rotl(v3,12)+_rotl(v4,18))&M64
        h=_merge(h,v1); h=_merge(h,v2); h=_merge(h,v3); h=_merge(h,v4)
    else:
        h=P5
    h=(h+n)&M64
    while p+8<=end:
        h^=_round(0,int.from_bytes(data[p:p+8],'little')); h=((_rotl(h,27)*P1&M64)+P4)&M64; p+=8
    if p+4<=end:
        h^=(int.from_bytes(data[p:p+4],'little')*P1)&M64; h=((_rotl(h,23)*P2&M64)+P3)&M64; p+=4
    while p<end:
        h^=(data[p]*P5)&M64; h=_rotl(h,11)*P1&M64; p+=1
    h^=h>>33; h=(h*P2)&M64; h^=h>>29; h=(h*P3)&M64; h^=h>>32
    return h&M64
BUCKETS=4096
def bucket(key): return xxh64(key)&(BUCKETS-1)
def worker(key,W=8): return (bucket(key)*W)//BUCKETS    # default contiguous layout
def keys_for_worker(target,count,W=8,prefix="k"):
    out=[]; i=0
    while len(out)<count:
        k="%s%d"%(prefix,i); i+=1
        if worker(k,W)==target: out.append(k)
    return out
if __name__=="__main__":
    import socket,sys
    s=socket.create_connection(("127.0.0.1",int(sys.argv[1]) if len(sys.argv)>1 else 7800)); f=s.makefile("rwb")
    def find(k):
        f.write(b"*4\r\n$5\r\nDEBUG\r\n$7\r\nRESHARD\r\n$4\r\nFIND\r\n$%d\r\n%s\r\n"%(len(k),k.encode())); f.flush()
        l=f.readline(); return l[1:].decode().strip()
    ok=True
    for k in ["1","42","hello","k0","k1","worker3test","abcdefghijklmnopqrstuvwxyz012345"]:
        r=find(k); srv_bucket=int(r.split("bucket=")[1].split(" ")[0]); srv_w=int(r.split("routed_worker=")[1].split(" ")[0])
        mine_b=bucket(k); mine_w=worker(k)
        match = (mine_b==srv_bucket)
        ok = ok and match
        print("key=%-34s py(bucket=%d worker=%d)  srv(bucket=%d worker=%d)  %s"%(k,mine_b,mine_w,srv_bucket,srv_w,"OK" if match else "MISMATCH"))
    print("XXH64 REPLICA", "VERIFIED" if ok else "FAILED")
