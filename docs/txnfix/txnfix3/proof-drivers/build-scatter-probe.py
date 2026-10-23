import pathlib,subprocess,shlex,json,concurrent.futures
root=pathlib.Path.cwd();out=root/'build/txnfix3/scatter-probe';out.mkdir(exist_ok=True)
receipt=root/'docs/txnfix/txnfix3/scatter-trace'
pre=root/'build/txnfix2/pre/tomokv'
old=next(l for l in (root/'build/txnfix2/pre-build.log').read_text().splitlines() if ' -o '+str(pre)+' ' in l)
new=next(l for l in subprocess.check_output(['make','-n','-W','src/main.cc','all'],text=True).replace('\\\n',' ').splitlines() if ' -o build/tomokv ' in l)
def run(item):
 arm,recipe=item;folder=out/arm;folder.mkdir(exist_ok=True)
 include=root/('build/txnfix2/pre-source' if arm=='pre' else '.')
 cmd=['taskset','-c','112-127','g++','-std=c++20','-O2','-g','-march=native','-pthread','-DTOMO_JEMALLOC','-I'+str(include),'-c',str(receipt/'probe.cc'),'-o',str(folder/'probe.o')]
 link=shlex.split(recipe)
 found=[i for i,x in enumerate(link) if x.endswith('/src/main.o') and '/db0/' not in x];assert len(found)==1
 link[found[0]]=str(folder/'probe.o');link=[x for x in link if not x.endswith('/src/main.o')];link[link.index('-o')+1]=str(folder/'probe');link=['taskset','-c','112-127',*link]
 with (receipt/(arm+'-build.log')).open('w') as log:
  a=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
  b=None if a else subprocess.run(link,stdout=log,stderr=subprocess.STDOUT).returncode
 return dict(arm=arm,compile=cmd,compile_exit=a,link=link,link_exit=b)
with concurrent.futures.ThreadPoolExecutor(2) as pool:rows=list(pool.map(run,[('pre',old),('post',new)]))
(receipt/'build.json').write_text(json.dumps(rows,indent=2)+'\n');print([(r['arm'],r['compile_exit'],r['link_exit']) for r in rows])
