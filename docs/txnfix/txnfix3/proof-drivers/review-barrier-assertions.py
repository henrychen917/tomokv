import ast,collections,json,pathlib,subprocess
root=pathlib.Path('docs/txnfix/txnfix3')
result={}
for name in ('multirace.py','multires.py'):
 path='tests/'+name
 old=subprocess.check_output(['git','show','b452303fd:'+path],text=True);new=pathlib.Path(path).read_text()
 def collect(source):
  out={};parents={};tree=ast.parse(source)
  for n in ast.walk(tree):
   for c in ast.iter_child_nodes(n):parents[c]=n
  for n in ast.walk(tree):
   if not isinstance(n,ast.Assert):continue
   p=n
   while p in parents and not isinstance(p,(ast.FunctionDef,ast.AsyncFunctionDef)):p=parents[p]
   fn=p.name if isinstance(p,(ast.FunctionDef,ast.AsyncFunctionDef)) else '<module>'
   key=(fn,ast.dump(n,include_attributes=False));out[key]=dict(function=fn,line=n.lineno,source=ast.get_source_segment(source,n))
  return out
 a,b=collect(old),collect(new)
 result[path]=dict(base='b452303fd',unchanged_assertions=len(a.keys()&b.keys()),removed=[a[k] for k in a.keys()-b.keys()],added=[b[k] for k in b.keys()-a.keys()],scope='This inventory covers Python assert statements; explicit raise/data conditions remain visible in the full source diff. Only MSETNX ordering-witness expressions and debug arming may differ. Reply/data/lost-write/stale-read/late-order checks retain their source. Full diffs remain in the commits.')
(root/'barrier-assertion-review.json').write_text(json.dumps(result,indent=2)+'\n')
for k,v in result.items():
 print(k,'unchanged',v['unchanged_assertions'])
 for n in ('removed','added'):
  for a in v[n]:print(n,a['function'],a['source'])
