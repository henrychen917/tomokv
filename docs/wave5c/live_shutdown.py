#!/usr/bin/env python3
"""ASAN shutdown with idle, borrowed, watched, blocked and pub/sub clients held open."""
import argparse,json,os,signal,socket,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/"tests"))
from _lib import Conn,wait_ready
p=argparse.ArgumentParser();p.add_argument("--binary",type=Path,required=True);p.add_argument("--cores",required=True);p.add_argument("--port",type=int,required=True);a=p.parse_args()
assert 26800<=a.port<=26899
out=ROOT/"docs/wave5c/live-shutdown";out.mkdir(exist_ok=True)
records=[]
for mode in ("2s","1s"):
 for engine in ("uring","epoll"):
  for stop in ("sigterm","sigint","command"):
   label=f"{mode}-{engine}-{stop}";directory=ROOT/"build/wave5c/live-shutdown"/label;directory.mkdir(parents=True,exist_ok=True)
   cmd=["taskset","-c",a.cores,str(a.binary.resolve()),"--port",str(a.port),"--bind","127.0.0.1","--shards","16","--databases","1","--thread-mode",mode,"--net-io",engine,"--save","","--dir",str(directory),"--zc-min","16384","--enable-debug-command","yes"]
   if mode=="2s":cmd += ["--ratio","6:2"]
   sockets=[];log=out/(label+".log")
   with log.open("w") as f:
    proc=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT)
    try:
     admin=wait_ready("127.0.0.1",a.port,timeout=20,process=proc,log_path=log);sockets.append(admin)
     assert admin.must("SET","shutdown:large",b"x"*(2*1024*1024))==b"OK"
     for i in range(24):sockets.append(Conn("127.0.0.1",a.port))
     watcher=Conn("127.0.0.1",a.port);sockets.append(watcher)
     assert watcher.must("WATCH","shutdown:large")==b"OK"
     assert watcher.must("MULTI")==b"OK"
     assert watcher.must("SET","shutdown:queued","never-executed")==b"QUEUED"
     blocked=Conn("127.0.0.1",a.port);sockets.append(blocked);blocked.send("BLPOP","shutdown:empty","0")
     sub=Conn("127.0.0.1",a.port);sockets.append(sub);sub.send("SUBSCRIBE","shutdown:channel");sub.read()
     reader=Conn("127.0.0.1",a.port);sockets.append(reader);reader.sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4096);reader.send("GET","shutdown:large")
     assert admin.must("PING")==b"PONG"
     if stop=="command":admin.send("SHUTDOWN","NOSAVE")
     else:proc.send_signal(signal.SIGTERM if stop=="sigterm" else signal.SIGINT)
     rc=proc.wait(timeout=30)
    finally:
     if proc.poll() is None:proc.kill();proc.wait()
     for s in sockets:s.close()
   text=log.read_text();passed=rc==0 and "Sanitizer" not in text and text.rstrip().splitlines()[-1].startswith("shutdown_report ")
   row=dict(label=label,command=cmd,returncode=rc,passed=passed);records.append(row);(out/"results.json").write_text(json.dumps(records,indent=2)+"\n")
   print(label,rc,passed,flush=True)
   if not passed:raise SystemExit(1)
