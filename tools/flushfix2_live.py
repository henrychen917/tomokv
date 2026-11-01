#!/usr/bin/env python3
"""Finite MGET scopes with eight live EXEC-format records, no listening server."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess

import flushfix2_counts as counts

ROOT = counts.ROOT
BUILD = ROOT / 'build/flushfix2/live-counts'
OUT = ROOT / 'docs/flushfix2/live-counts'


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'tests/txnorder_command_scope.cc').read_text()
    anchor = '  if(command=="EVAL"||command=="EVAL-ADMIT"){'
    assert source.count(anchor) == 1
    source = source.replace(anchor, '''  need(command == "MGET" && atomic);
  std::atomic<uint64_t> live_epoch{0};
  std::atomic<bool> live_aborted{false};
  std::atomic<uint32_t> live_refs{1};
  const unsigned floor_io = Fused ? 0 : 1;
  server.publish_atomic_read_floor(floor_io, 1);
  for(const auto& name:keys){
   Slice key(name.data(),name.size());const auto hash=FlatStore::hash_key(key);
   auto& store=server.shard(server.router().shard_of(hash)).store();void* record=nullptr;
   need(store.atomic_prepare_transaction(key,hash,8877,&live_epoch,&live_refs,&live_aborted,nullptr,record));
   KvObj* object=kvobj_new_string(key,{value.data(),uint32_t(value.size())});need(object);
   need(store.atomic_admit(key,object));store.atomic_install_transaction(hash,key,record,object);
   store.atomic_finish_plain();need(store.atomic_pending_entries()==1);
  }
  live_epoch.store(server.atomic_commit());
''' + anchor)
    anchor = '  command_bind_server(nullptr);'
    assert source.count(anchor) == 1
    source = source.replace(anchor, '''  for(const auto& name:keys){
   Slice key(name.data(),name.size());auto& store=server.shard(server.router().shard_of(FlatStore::hash_key(key))).store();
   need(store.atomic_pending_entries()==1);store.atomic_shutdown_release_records();
  }
  server.publish_atomic_read_floor(floor_io,UINT64_MAX);
''' + anchor)
    fixture = BUILD / 'live.cc'
    fixture.write_text(source)
    counts.BUILD, counts.OUT = BUILD, OUT
    counts.scope.BUILD = BUILD
    subprocess.run(['gcc', '-O2', str(ROOT / 'tools/crlffix_step.c'), '-o', str(BUILD / 'step')], check=True)
    prepared = {}
    for arm in ('pre', 'post'):
        for ns in ('normal', 'db0'):
            dest = BUILD / (arm + '-' + ns)
            dest.mkdir(exist_ok=True)
            receipt = json.loads((ROOT / 'docs/flushfix2/counts' / f'{arm}-{ns}-build.json').read_text())
            compile_cmd = receipt['compile'].copy()
            compile_cmd[compile_cmd.index('-c') + 1] = str(fixture)
            compile_cmd[compile_cmd.index('-o') + 1] = str(dest / 'probe.o')
            link = receipt['link'].copy()
            link[-1] = str(dest / 'probe.o')
            link[link.index('-o') + 1] = str(dest / 'probe')
            with (OUT / f'{arm}-{ns}-build.log').open('w') as log:
                subprocess.run(compile_cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
                subprocess.run(link, stdout=log, stderr=subprocess.STDOUT, check=True)
            (OUT / f'{arm}-{ns}-build.json').write_text(json.dumps(dict(
                compile=compile_cmd, link=link, fixture_sha256=hashlib.sha256(source.encode()).hexdigest()), indent=2)+'\n')
            prepared[arm, ns] = counts.fast.prepare(arm, ns)
    cases = [(arm, ns, 'MGET', mode, 1, 1, -1) for arm in ('pre', 'post')
             for ns in ('normal', 'db0') for mode in ('1s', '2s')]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda case: counts.run(case, prepared), cases))
    (OUT / 'results.json').write_text(json.dumps(rows, indent=2)+'\n')


if __name__ == '__main__':
    main()
