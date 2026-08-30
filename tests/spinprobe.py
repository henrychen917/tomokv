#!/usr/bin/env python3
# L2 partial-frame spin probe. A connection that has sent an INCOMPLETE RESP frame and then goes
# quiet must not make its io thread spin: the parser returns Incomplete without advancing, and if
# the loop counts that as progress it never parks. usage: spinprobe.py PORT [server_pid]
import socket, sys, time, os, glob
PORT=int(sys.argv[1])
def find_srv():
    if len(sys.argv)>2: return int(sys.argv[2])
    for d in glob.glob('/proc/[0-9]*'):
        try:
            if 'tomokv' in open(d+'/comm').read(): return int(d.split('/')[2])
        except OSError: pass
    raise SystemExit("no tomokv")
srv=find_srv()
def ticks():
    p=open("/proc/%d/stat"%srv).read().split(); return int(p[13])+int(p[14])
s=socket.create_connection(("127.0.0.1",PORT)); s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
s.sendall(b"*3\r\n$3\r\nSE")
t0=ticks(); time.sleep(6); d=ticks()-t0
print("partial-frame idle 6s: %d server CPU ticks"%d)
# clean = server parks; a 6s idle window should cost only wakeups, not a pegged core
sys.exit(0 if d<=40 else 1)
