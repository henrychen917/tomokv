#!/usr/bin/env python3
"""Finite command-scope instruction counts; no listener, PMU, load or rate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import wave13_counts as census

p = argparse.ArgumentParser()
p.add_argument('arm'); p.add_argument('--source', type=Path, required=True)
p.add_argument('--objects', type=Path, required=True)
p.add_argument('--no-build', action='store_true')
p.add_argument('--maxmemory', action='store_true')
p.add_argument('--set-insert', action='store_true')
p.add_argument('--only', default='GET,SET,INCR,MGET,MSET')
p.add_argument('--screen', action='store_true', help='one split, atomic-off call per command')
a = p.parse_args()
assert os.sched_getaffinity(0) <= set(range(16, 24))
os.environ['LC_ALL'] = 'C'
census.BUILD = census.ROOT/'build/storefix5/counts'
census.DOC = census.ROOT/'docs/storefix5/counts'
census.BUILD.mkdir(parents=True, exist_ok=True)
tracer = census.BUILD/'trace'
if not tracer.exists():
    subprocess.run(['g++', '-std=c++20', '-O2', '-g', 'tools/scriptfix3_trace.cc',
                    '-o', str(tracer)], check=True)
source, objects = a.source.resolve(), a.objects.resolve()
fixture = 'tests/blockfix4_scope.cc'
if a.maxmemory or a.set_insert:
    original = (census.ROOT/fixture).read_text()
    updated = original
    if a.maxmemory:
        marker = '  need(server.init(cfg));command_bind_server(&server);'
        assert updated.count(marker) == 1
        updated = updated.replace(marker,
            '  cfg.maxmemory = 1ull << 30; cfg.maxmemory_policy = MaxmemoryPolicy::AllKeysLru;\n'+marker)
    if a.set_insert:
        marker = '   for(unsigned i=0;i<n;i++){\n    auto* op=client.rob().template acquire<false>();need(op);'
        assert updated.count(marker) == 1
        setup = '''   std::vector<std::string> insert_keys;
   if(command=="SET") for(unsigned k=0;insert_keys.size()<n;k++){
    std::string key="storefix5-fresh:"+std::to_string(k);Slice s(key.data(),key.size());
    if(server.router().shard_of(FlatStore::hash_key(s))==0)insert_keys.push_back(key);
   }
'''
        updated = updated.replace(marker, setup+marker)
        marker = '    need(op->push_arg({keys[0].data(),uint32_t(keys[0].size())}));'
        assert updated.count(marker) == 1
        updated = updated.replace(marker,
            '    const auto& chosen = command=="SET"?insert_keys[i]:keys[0];\n'
            '    need(op->push_arg({chosen.data(),uint32_t(chosen.size())}));')
    generated = census.BUILD/(a.arm+'-scope.cc')
    generated.write_text(updated)
    fixture = str(generated.relative_to(census.ROOT))
rows = []
for namespace in ('normal', 'db0'):
    binary = (census.BUILD/'scopes'/(a.arm+'-'+namespace)/'probe' if a.no_build else
              census.build(a.arm, source, objects, namespace, fixture))
    prepared = census.prepare(binary, objects, namespace, 'complete')
    cases = [(verb, mode, batch, atomic) for verb in a.only.split(',')
             for mode in (('2s',) if a.screen else ('1s','2s'))
             for batch in ((1,) if a.screen else (1,32))
             for atomic in ((0,) if a.screen else (0,1))]
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows += list(pool.map(lambda case: census.trace(prepared, a.arm, namespace,
                                                        'complete', *case), cases))
census.save(census.DOC/a.arm/'counts.json', dict(rows=rows,
    server_sha256=census.sha(objects/'tomokv'), tracer_sha256=census.sha(tracer),
    maxmemory=1073741824 if a.maxmemory else 0, set_insert=a.set_insert))
