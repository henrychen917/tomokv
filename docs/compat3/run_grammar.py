import contextlib, json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tests"))
from _lib import Conn, wait_ready
OUT=ROOT/"docs/compat3/grammar";OUT.mkdir(exist_ok=True)
@contextlib.contextmanager
def server(binary,port,cores,extra,name):
    assert not subprocess.check_output(["ss","-H","-ltn",f"sport = :{port}"],text=True).strip()
    data=ROOT/"build/compat3"/("grammar-"+name);data.mkdir(exist_ok=True)
    cmd=["taskset","-c",cores,str(binary),"--bind","127.0.0.1","--port",str(port),"--save","","--appendonly","no","--dir",str(data),*extra]
    with (OUT/(name+".log")).open("w") as log:
        child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
        print(json.dumps(dict(command=cmd,pid=child.pid)),flush=True)
        try:
            wait_ready("127.0.0.1",port,process=child,timeout=10).close()
            yield
        finally:
            child.terminate()
            child.wait(timeout=10)
            deadline=time.monotonic()+5
            while subprocess.check_output(["ss","-H","-ltn",f"sport = :{port}"],text=True).strip():
                assert time.monotonic()<deadline, "owned port did not close"
                time.sleep(.01)
            print("STOP",child.pid,child.returncode,flush=True)

def main():
    with server(Path("/home/user/Projects/redis74/src/redis-server"),25891,"104",[],"oracle"):
        for mode in ("1s","2s"):
            extra=["--shards","16","--thread-mode",mode,"--atomic","0","--net-io","uring","--databases","1"]
            if mode=="2s":extra += ["--ratio","6:2"]
            with server(ROOT/"build/tomokv",25890,"96-103",extra,mode):
                subprocess.run([sys.executable,str(ROOT/"docs/compat3/grammar_audit.py"),"25891","25890",str(OUT/(mode+".json"))],check=True)

if __name__ == "__main__": main()
