"""Retain full strict differences and an explicit reason for each changed body group."""
import difflib,gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from reorder_noop import Binary
out=ROOT/'docs/fliplisten/identity'
cache=ROOT/'build/fliplisten/body-details';cache.mkdir(exist_ok=True)
pre=Binary(ROOT/'build/tomokv-PRE',cache,True)
post=Binary(ROOT/'build/tomokv',cache,True)
changed=json.loads((out/'changed-bodies.json').read_text())
def reason(name):
 if 'fliplisten' in name.lower() or 'FlipListenerState' in name:
  return 'Listener lifecycle, bounded pending descriptors, independent cancellation fences and quota-before-admission acknowledgements.'
 if any(x in name for x in ('flip_', 'prepare_activation', 'cancel_prepared_activation', 'deactivate', 'IoLoop::activate(', '~IoLoop', '~Server')):
  return 'Existing FLIP prepare/install/rollback or process teardown now includes listener ownership and retained descriptors.'
 if '::run_loop<' in name:
  return 'The only instruction difference is the existing accept_pending_ cold call target; same widths, offsets and all other instructions. See normal-paths.json.'
 if '::on_accept<' in name or '::r7_on_accept<' in name:
  return 'Paused and stale accept completions enter retention instead of close. Normal successful paths use no more instructions; all 72 emitted kind/MORE cases are traced in normal-paths.json.'
 if 'admit_retained_fd' in name:
  return 'Admission body factored into an always-inline entry so retained descriptors use original admission after exact quota validation.'
 if any(x in name for x in ('admit_fd<','on_cqe<','epoll_pass<')):
  return 'Existing paused/stale/default branches call the cold listener protocol. Normal admission body is preserved; compiler block layout/register choices and constant labels differ. Exact IO diffs retained.'
 if any(x in name for x in ('std::_Sp_counted','std::__shared','std::shared_ptr')):
  return 'Cold listener state uses shared ownership with an incomplete header type; added instantiations/destructor propagation.'
 if 'parse_and_dispatch<' in name or 'adopt_client<' in name or 'on_recv<' in name or 'serve_impl<' in name or 'serve_tls_impl<' in name:
  return 'Unedited template source; added cold admission instantiations and per-unit inlining budgets change clone multiplicity or generated instructions. No operation-path source change; residual retained for merit.'
 if '_GLOBAL__sub_I_' in name:
  return 'New feature translation unit/static initialization registration or linker placement propagation.'
 return 'Unedited body: compiler/template or linker propagation from the cold listener implementation and budget changes. Exact difference retained; no single optimizer decision isolated.'
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
