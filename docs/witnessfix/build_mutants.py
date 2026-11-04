from pathlib import Path
import sys,subprocess,shlex,difflib,json
sys.path.insert(0,str(Path('tools').resolve()))
from aclkeys3_controls import command
root=Path.cwd()
def list_link():
 lines = subprocess.check_output(['make', '-f', 'Makefile', '-f', 'tests/list_namespace.mk', '-n', '-B', 'build/list-namespace-unit'], text=True).splitlines()
 return next(shlex.split(line) for line in lines if line.startswith('g++ ') and 'tests/list_namespace_unit.cc' in line)

arms=[('histogram-empty','src/cmd/latency_tracking.cc','void latency_tracking_histogram(Op& op) {','void latency_tracking_histogram(Op& op) { reply_map_header(op.sink(), 0, op.resp3()); return;'),('cpu-zero','src/cmd/info_stats.cc','const auto seconds = [](timeval t) { return double(t.tv_sec) + double(t.tv_usec) / 1000000; };','const auto seconds = [](timeval) { return 0.0; };')]
arms += [
 ('config-error', 'src/cmd/t_server.cc', 'error = "can\'t set immutable config";', 'error = "planted unrelated CONFIG error";'),
 ('flip-freeze', 'src/core/fliplisten.cc', 'bool IoLoop::fliplisten_prepare() {',
  'bool IoLoop::fliplisten_prepare() { static std::atomic<bool> frozen{false}; if (srv_->flip_stage() != FlipStage::Idle && !frozen.exchange(true)) { std::fprintf(stderr, "WITNESSFIX freeze-hit=1 stage=%u\\n", unsigned(srv_->flip_stage())); ::usleep(5000000); }'),
]
for name, indent in (('list-new-namespace', '        '), ('list-existing-namespace', '    ')):
 old = indent + 'if (shard.has_blocking_waiters()) blocking_publish_key(shard, hash, key.p, key.n, key.ns);\n' + indent + 'return XshardElementResult::Ok;'
 arms.append((name, 'src/cmd/t_list.cc', old, old.replace('key.n, key.ns', 'key.n, 0')))
movers = Path('src/cmd/xshard_movers.inc').read_text()
private = 'if (!state.multi_child) store.atomic_set_read_context(UINT64_MAX, state.origin_conn_id);'
assert movers.count(private) == 1
arms.append(('exec-private-view', 'src/cmd/xshard.cc', '#include "xshard_movers.inc"',
             movers.replace(private, 'store.atomic_set_read_context(UINT64_MAX, state.origin_conn_id); // planted lost EXEC overlay')))
mpop = Path('src/cmd/xshard_commands.inc').read_text()
assert mpop.count('ERR numkeys should be greater than 0') == 1
arms.append(('mpop-error-suffix', 'src/cmd/xshard.cc', '#include "xshard_commands.inc"',
             mpop.replace('ERR numkeys should be greater than 0',
                          'ERR numkeys planted unrelated suffix')))
arms.append(('geo-count-order', 'src/cmd/geo.cc',
             'if (options.count && options.order == GeoOrder::None && !options.any)\n        options.order = GeoOrder::Asc;',
             '// planted defect: COUNT no longer supplies implicit nearest-first order'))
arms.append(('geo-order-reversed', 'src/cmd/geo.cc',
             'return options.order == GeoOrder::Desc ? a.distance_m > b.distance_m',
             'return options.order == GeoOrder::Asc ? a.distance_m > b.distance_m'))
selected = set(sys.argv[1:]) or {name for name, *_ in arms}
assert selected <= {name for name, *_ in arms}, selected
for name,source,old,new in arms:
 if name not in selected: continue
 folder=root/'build/witnessfix/mutants'/name;folder.mkdir(parents=True,exist_ok=True)
 original=Path(source).read_text();assert original.count(old)==1
 mutated=original.replace(old,new);copy=folder/Path(source).name;copy.write_text(mutated)
 patch=''.join(difflib.unified_diff(original.splitlines(True),mutated.splitlines(True),fromfile=source,tofile=str(copy)))
 (folder/'defect.patch').write_text(patch)
 replacements={};cmds=[]
 for namespace in (('src',) if name.startswith('list-') else ('src','db0/src')):
  obj='build/'+source.replace('src/',namespace+'/',1).removesuffix('.cc')+'.o'
  cmd=command(Path(obj),'-c '+source+' ')
  output=folder/(namespace.replace('/','-')+'.o');cmd[cmd.index('-c')+1]=str(copy);cmd[cmd.index('-o')+1]=str(output);cmd+=['-iquote',str(Path(source).parent)]
  cmds.append(cmd)
  with (folder/(namespace.replace('/','-')+'.log')).open('w') as log: subprocess.run(['taskset','-c','80-95',*cmd],stdout=log,stderr=subprocess.STDOUT,check=True)
  replacements[obj]=str(output)
 link=(list_link() if name.startswith('list-') else command(Path('build/tomokv'),'-Wl,--wrap=main'));link=[replacements.get(x,x) for x in link];link[link.index('-o')+1]=str(folder/'tomokv');cmds.append(link)
 with (folder/'link.log').open('w') as log: subprocess.run(['taskset','-c','80-95',*link],stdout=log,stderr=subprocess.STDOUT,check=True)
 (folder/'commands.json').write_text(json.dumps(cmds,indent=2)+'\n')
 print('BUILT',name,flush=True)
