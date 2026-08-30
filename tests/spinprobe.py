#!/usr/bin/env python3
# L2 partial-frame spin probe. A connection that has sent an INCOMPLETE RESP frame and then goes
# quiet must not make its io thread spin: the parser returns Incomplete without advancing, and if
# the loop counts that as progress it never parks. usage: spinprobe.py PORT [server_pid]
#
# Scored as a DELTA over the same server's zero-conn idle burn: background timers (cron, climon,
# lb census, the age sampler) legitimately tick the loop and drift across binaries, so an
# absolute threshold rots. The defect this guards against costs ~1000 ticks/6s; wakeup-only
# parking costs ~0 over baseline.
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
t0=ticks(); time.sleep(6); base=ticks()-t0
s=socket.create_connection(("127.0.0.1",PORT)); s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
s.sendall(b"*3\r\n$3\r\nSE")
time.sleep(0.5)                       # let the frame land and the conn reach its parked state
t0=ticks(); time.sleep(6); d=ticks()-t0
print("idle 6s: baseline %d ticks, with partial-frame conn %d ticks (delta %+d)"%(base,d,d-base))
sys.exit(0 if d-base<=40 else 1)
