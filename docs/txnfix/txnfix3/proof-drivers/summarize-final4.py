import collections,hashlib,json,pathlib,re
root=pathlib.Path('docs/txnfix/txnfix3')
assert (root/'final4-controls/ALL-DONE').exists()
assert (root/'final4-frozen.json').exists()
main=json.loads((root/'final4-proof/runs.json').read_text())
extras=json.loads((root/'final4-extras/runs.json').read_text())
controls=json.loads((root/'final4-controls/runs.json').read_text())
barrier=json.loads((root/'final4-barrier-control/proof/runs.json').read_text())
cross=json.loads((root/'final4-cross-watch/runs.json').read_text())
families={}
def family(label, rows, count, positive=True):
 assert len(rows)==count,(label,len(rows),count)
 r=dict(rows=count,passed=sum(x['exit_code']==0 for x in rows),failed=[dict(name=x['name'],exit_code=x['exit_code']) for x in rows if x['exit_code']],names=[x['name'] for x in rows])
 if positive:assert not r['failed'],(label,r['failed'])
 families[label]=r
select=lambda p:[r for r in main if p(r['name'])]
assert len(main)==154
family('txniso',select(lambda n:n.startswith('txniso-') and '-aof-' not in n),8)
family('txniso AOF',select(lambda n:n.startswith('txniso-aof-')),4)
family('EXEC NX',select(lambda n:n.startswith('nx-') and not n.startswith('nx-bare-')),4)
family('bare NX',select(lambda n:n.startswith('nx-bare-')),2)
for r in select(lambda n:n.startswith('nx-')):
 line=next(l for l in (root/'final4-proof'/r['name']/'test.log').read_text().splitlines() if l.startswith('{"transactional"'))
 data=json.loads(line);assert data['completed']==8192 and data['failures']==0 and not data['errors'] and not data['threads_alive']
family('movers',select(lambda n:n.startswith('movers-')),2)
family('G5 standalone',select(lambda n:n.startswith('G5-')),2)
family('txngroup',select(lambda n:n.startswith('txngroup-') and not n.startswith('txngroup-aof-')),4)
for r in select(lambda n:n.startswith('txngroup-') and not n.startswith('txngroup-aof-')):
 log=(root/'final4-proof'/r['name']/'test.log').read_text()
 assert all('PASS '+case in log for case in ['G1','G2','G3','G4','G5','G6','GX'])
family('txngroup AOF',select(lambda n:n.startswith('txngroup-aof-')),2)
family('Redis matrix',select(lambda n:n.startswith('differ-')),2)
for n,count in [('split',56),('armed-fused',58)]:
 log=(root/f'final4-proof/differ-{n}/test.log').read_text()
 assert f'DIFFER FOCUSED PROOF: pass={count} fail=0' in log
family('original EXEC POST',select(lambda n:n.startswith('original-post/')),28)
family('original EXEC PRE',select(lambda n:n.startswith('original-pre/')),28,False)
for r in select(lambda n:n.startswith('original-pre/')):
 if r['exit_code']:
  log=(root/'final4-proof'/r['name']/'test.log').read_text()
  assert any(t in log for t in ['AssertionError: acknowledged INCR lost','AssertionError: (\'acknowledged INCR lost\'','AssertionError: lost or duplicated INCR','AssertionError: queue accounting'])
family('Stage B',select(lambda n:n.startswith('stage-b/')),20)
family('broad',select(lambda n:n.startswith('broad-')),38,False)
assert {r['name'] for r in families['broad']['failed']} <= {'broad-1s/execatomic','broad-1s/atomic_torn'}
family('WATCH fresh boots',select(lambda n:n.startswith('watchlive-')),2)
family('directed units',select(lambda n:n.startswith('unit-')),4)
family('writer AOF snapshot FLIP',[r for r in extras if not r['name'].startswith('pre-')],15)
family('PRE txniso controls',[r for r in extras if r['name'].startswith('pre-')],4,False)
assert families['PRE txniso controls']['passed']==0
family('crossed WATCH POST',[r for r in cross if r['name'].startswith('post-')],4)
family('crossed WATCH PRE',[r for r in cross if r['name'].startswith('pre-')],4,False)
family('barrier removed',barrier,4,False)
assert families['barrier removed']['passed']==0
for r in barrier:
 log=(root/'final4-barrier-control/proof'/r['name']/'test.log').read_text()
 witness='atomic_group_barriers=[0, 0]' if r['name'].startswith('multirace') else 'MSETNX dispatch barrier never ordered the pair'
 assert witness in log,(r['name'],witness)
for name,reason in [('unfenced','exclusive cannot pass an IO suspended between admission and open'),('undrained','acknowledged fence is not exclusive drain completion')]:
 log=(root/f'final4-controls/admission-{name}.log').read_text();assert reason in log
build=json.loads((root/'final4-build/runs.json').read_text());fresh=json.loads((root/'final4-build/freshness.json').read_text())
assert len(build)==3 and len(fresh)==30 and all(r['exit_code']==0 for r in build+fresh)
gates=next(r for r in main if r['name']=='gates-test');assert gates['exit_code']==0
assert 'Ran 66 tests' in (root/'final4-proof/gates-test/test.log').read_text()
identity=json.loads((root/'identity-final4/full/summary.json').read_text());assert identity['hot_equal']==identity['hot']==1208
paths=json.loads((root/'final4-path-counts.json').read_text());assert paths['cases']==264 and not paths['invalid'] and not paths['cases_with_increases'] and not paths['cases_entering_group_helpers']
sha=hashlib.sha256(pathlib.Path('build/tomokv').read_bytes()).hexdigest();assert sha=='1c808efda63159b31e45e7e960053052b8ac6cd3345049dc23e857bd3da845cc'
assert all(r['sha256']==sha for r in main if r['arm']=='post')
result=dict(runtime_source='e904cd285',post_sha256=sha,acceptance='NOT ACCEPTED: universal ordinary-path instruction-sequence identity remains unproven; quiet-box null unmeasured; existing broad failures retained.',families=families,build_targets=29,freshness=30,gates_test=66,redis_comparison_legs=112,redis_armed_witnesses=2,watch_fresh_boots=60,nx_repeats_per_cell=8192,selected_hot=1208,lbstall={'normal':601,'db0':603},scatter_count_pairs=264,full_inventory={k:identity[k] for k in ['total','equal','changed']},other_main_nonzero=[dict(name=r['name'],exit_code=r['exit_code']) for r in main if r['exit_code'] and not r['name'].startswith(('original-pre/','broad-'))],baseline_controls=controls,proof_cpus='112-127',server_cpus='112-119',ports='22600-22699',gate_rows=dict(txnfix3_DQ=0,txnfix3_DF=0,branch_DQ=10,branch_DF=10,owner_counts=[635,652],protected_counts=[625,642]))
(root/'final4-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print('Final proof receipt verified; universal static acceptance remains open.')
for name,f in families.items():print(name,f['passed'],'/',f['rows'])
