import pathlib,subprocess,json,concurrent.futures
root=pathlib.Path.cwd();out=root/'build/txnfix3/prepare-release';out.mkdir(exist_ok=True)
receipt=root/'docs/txnfix/txnfix3/prepare-release';receipt.mkdir(exist_ok=True)
old=json.loads((root/'docs/txnfix/txnfix3/scatter-trace/build.json').read_text())
def run(case):
 arm,db0=case;label=arm+('-db0' if db0 else '-normal');folder=out/label;folder.mkdir(exist_ok=True)
 include=root/('build/txnfix2/pre-source' if arm=='pre' else '.')
 cmd=['taskset','-c','112-127','g++','-std=c++20','-O2','-g','-march=native','-pthread','-DTOMO_JEMALLOC','-I'+str(include)]
 if db0:cmd+=['-DTOMO_SINGLE_DATABASE=1','-Dtomo=tomo_db0']
 cmd+=['-c',str(root/'docs/txnfix/txnfix3/scatter-trace/probe-prepare.cc'),'-o',str(folder/'probe.o')]
 link=old[0 if arm=='pre' else 1]['link'].copy();link=[str(folder/'probe.o') if x.endswith('/probe.o') else x for x in link];link[link.index('-o')+1]=str(folder/'probe')
 with (receipt/(label+'-build.log')).open('w') as log:
  a=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
  b=None if a else subprocess.run(link,stdout=log,stderr=subprocess.STDOUT).returncode
 return dict(arm=label,compile=cmd,compile_exit=a,link=link,link_exit=b)
with concurrent.futures.ThreadPoolExecutor(4) as pool:rows=list(pool.map(run,[(a,d) for a in ['pre','post'] for d in [False,True]]))
(receipt/'build.json').write_text(json.dumps(rows,indent=2)+'\n');print([(r['arm'],r['compile_exit'],r['link_exit']) for r in rows])
