#!/usr/bin/env python3
"""Throwaway iofix ASAN: log only final destructor ownership/pins, before old cleanup."""
import hashlib,json,os,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; build=ROOT/"build/wave5c"; src=build/"diagnostic-source"
assert os.sched_getaffinity(0)<=set(range(64,112))
src.mkdir(exist_ok=True)
archive=build/"diagnostic.tar"
with archive.open("wb") as f:subprocess.run(["git","archive","fcb52cd49","src","tests","third_party"],stdout=f,check=True)
with tarfile.open(archive) as t:t.extractall(src,filter="data")
archive.unlink()
p=src/"src/core/io_loop.h";old=p.read_text();needle="    ~IoLoop() {"
log=r"""
        if (self_) {
            auto log = [&](const char* place, Client* c) {
                std::fprintf(stderr, "shutdown-pin tid=%u place=%s id=%llu dead=%d closing=%d serve=%d recv=%d send=%d rob=%u\n",
                    self_->id(), place, (unsigned long long)c->id(), c->dead(), c->closing(), c->serve_pending(), c->recv_armed(), c->send_inflight(), c->rob().in_flight());
            };
            for (Client* c : dead_ready_) log("dead_ready", c);
            for (Client* c : dead_next_) log("dead_next", c);
            for (Client* c : active_.v) log("active", c);
            for (Client* c : pending_serve_) log("pending_serve", c);
            for (Client* c : pending_handoffs_) log("pending_handoffs", c);
        }
"""
assert old.count(needle)==1;p.write_text(old.replace(needle,needle+log))
sources=["src/main.cc","src/net/tls.cc"]
for d in ("core","cmd","snapshot","persist"):sources.extend(str(p.relative_to(src)) for p in sorted((src/"src"/d).glob("*.cc")))
out=build/"arms/iofix-diagnostic-asan"
cmd=[str(ROOT/"tests/parbuild.sh"),str(out),str(src/"objects"),"-std=c++20 -O1 -g -fsanitize=address -march=native -pthread -I.","-luring -pthread -lssl -lcrypto",*sources]
with (build/"diagnostic-build.log").open("w") as f:r=subprocess.run(cmd,cwd=src,env=dict(os.environ,PARBUILD_JOBS="32"),stdout=f,stderr=subprocess.STDOUT)
record=dict(ref="fcb52cd49",patch=log,command=cmd,returncode=r.returncode)
if r.returncode==0:record["sha256"]=hashlib.sha256(out.read_bytes()).hexdigest()
(ROOT/"docs/wave5c/diagnostic-build.json").write_text(json.dumps(record,indent=2)+"\n")
raise SystemExit(r.returncode)
