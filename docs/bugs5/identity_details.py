"""Retain full strict differences and an explicit reason for each changed body group."""
import difflib,gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from reorder_noop import Binary
out=ROOT/'docs/bugs5/identity'
cache=ROOT/'build/bugs5/body-details';cache.mkdir(exist_ok=True)
pre=Binary(ROOT/'build/tomokv-PRE',cache,True)
post=Binary(ROOT/'build/tomokv',cache,True)
changed=json.loads((out/'changed-bodies.json').read_text())
def reason(name):
 if 'slowlog' in name.lower() or 'Slowlog' in name or 'directory' in name:
  return 'SV4.3: immutable identity versions, capture before Done, retained entry ownership, or their container/destructor code.'
 if 'std::_Hashtable' in name or 'std::__detail::_Map_base' in name:
  return 'SV4.3: client directory changes from inline string pairs to shared immutable identity pointers; old/new map instantiations.'
 if 'cmd_hscan' in name:
  return 'CD4.2: compact scan finishes in one call; corresponding exception cleanup and inline callees follow the new body.'
 if 'exec_batch_timed' in name:
  return 'SV4.3: cold per-operation stack reference retains identity across execute/Done and passes it to recording.'
 if 'ExLoopT' in name and 'init(' in name:
  return 'RL4.1: replace XOR with an assigned nonzero per-thread seed; unchanged function size.'
 if any(x in name for x in ('hash_get','hash_set','hash_read_visit','hash_snapshot_read','hash_collect','HashFieldMap::','CollectionRef::','CompactView::','generic_getall','FlatStore::hash_key')):
  return 'Unedited helper in hash translation unit: HSCAN changes GCC inlining/clone allocation. Per-unit budget trials retained; no helper source change.'
 if any(x in name for x in ('IoLoop::on_cqe','IoLoop::epoll_pass','scan_home','FlipController::','_GLOBAL__sub_I_')):
  return 'Unedited body with equal size: linked address/literal-label or template propagation changes strict normalization; see exact instruction diff. Not waived as identical.'
 if 'IoLoop::parse_and_dispatch' in name or 'r7_adopt_client' in name or 'snapshot_control_pass' in name:
  return 'Unedited template body: compiler propagation in rebuilt executor/IO units after cold slowlog signature and seed changes. Budget trials retained; merit input.'
 return 'Unedited source body: compiler/link propagation from hash or slowlog/seed changes; exact difference retained, no single optimizer decision isolated.'
with gzip.open(out/'instruction-differences.txt.gz','wt') as f:
 for r in changed:
  r['reason']=reason(r['name'])
  left=pre.groups.get(r['name'],[]);right=post.groups.get(r['name'],[])
  f.write('\nFUNCTION '+r['name']+'\nREASON '+r['reason']+'\n')
  for i in range(max(len(left),len(right))):
   a=left[i] if i<len(left) else None;b=right[i] if i<len(right) else None
   f.write(f'CLONE {i} PRE {hex(a["addr"]) if a else "absent"} POST {hex(b["addr"]) if b else "absent"}\n')
   aa=[x+' | '+y for x,y in zip(a['ins'],a['encodings'])] if a else []
   bb=[x+' | '+y for x,y in zip(b['ins'],b['encodings'])] if b else []
   f.write('\n'.join(difflib.unified_diff(aa,bb,fromfile='PRE',tofile='POST',n=2))+'\n')
(out/'changed-bodies.json').write_text(json.dumps(changed,indent=2)+'\n')
with gzip.open(out/'all-bodies.json.gz','rt') as f:all_rows=json.load(f)
reasons={r['name']:r['reason'] for r in changed}
for r in all_rows:
 if r['name'] in reasons:r['reason']=reasons[r['name']]
with gzip.open(out/'all-bodies.json.gz','wt') as f:json.dump(all_rows,f)
s=json.loads((out/'summary.json').read_text());s['changed_hot']=[r for r in changed if r['hot']]
(out/'summary.json').write_text(json.dumps(s,indent=2)+'\n')
(out/'changed-bodies.md').write_text('\n'.join([
 '# Every changed linked body', '',
 'Strict gate normalization, including local clone multiplicity. No source-line immediate is masked. Identity is a proxy; the maintainer decides merit.', '',
 '| Function | PRE sizes | POST sizes | Reason |','|---|---|---|---|',
 *[f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in changed]])+'\n')
print(len(changed),'groups annotated; exact normalized instruction and encoding differences retained')
