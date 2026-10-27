#!/usr/bin/env python3
"""Throwaway single-body RAII alternative, counted before choosing an implementation."""
import concurrent.futures,hashlib,json,subprocess
from pathlib import Path
import budgets,instructions as count
root=count.ROOT;overlay=root/'build/wave8b/optional-source'; overlay.mkdir(exist_ok=True)
for directory in (root/'src').iterdir():
    dest=overlay/directory.name
    if directory.name!='cmd' and not dest.exists():dest.symlink_to(directory,target_is_directory=directory.is_dir())
cmd=overlay/'cmd';cmd.mkdir(exist_ok=True)
for source in (root/'src/cmd').iterdir():
    dest=cmd/source.name
    if source.name!='multi.inc' and not dest.exists():dest.symlink_to(source)
s=(root/'src/cmd/multi.inc').read_text()
begin=s.index('struct MultiLatencyOff {');end=s.index('\ntemplate<bool Tracked>\nvoid assemble_ownerless_replies',begin)
s=s[:begin]+'''template<bool Tracked>
struct MultiLatencyPart {
    std::optional<LatencyTrackingPart> part;
    __attribute__((always_inline)) MultiLatencyPart(uint32_t owner, const Op* op) {
        if (__builtin_expect(command_server()->latency_tracking(), false)) part.emplace(owner, op);
    }
    __attribute__((always_inline)) void finish() { if (part) part->finish(); }
};
'''+s[end:]
begin=s.index('__attribute__((noinline, cold)) static\nMultiTaskResult multi_execute_task_tracked')
end=s.index('\nMultiTaskResult multi_execute_task(Server&',begin)
s=s[:begin]+s[end:]
begin=s.index('    if (__builtin_expect(server.latency_tracking(), false))\n        return multi_execute_task_tracked')
end=s.index('    constexpr bool Tracked = false;',begin)
s=s[:begin]+s[end:]
s=s.replace('__attribute__((always_inline)) inline ','')
(cmd/'multi.inc').write_text(s)
def build(ns):
    obj=('db0/' if ns=='db0' else '')+'src/cmd/xshard.o'
    args=budgets.recipe('post',obj)
    args[args.index('src/cmd/xshard.cc')]=str(cmd/'xshard.cc')
    # Compile the overlay file path rather than resolving its symlink.
    source=(root/'src/cmd/xshard.cc').read_text()
    (cmd/'xshard.cc').unlink(missing_ok=True);(cmd/'xshard.cc').write_text(source)
    dest=count.BUILD/('optional-'+ns);dest.mkdir(exist_ok=True)
    args[args.index('-o')+1]=str(dest/'xshard.o')
    with (dest/'compile.log').open('w') as log:subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,check=True)
    recipe=json.loads((count.OUT/('post-'+ns+'-build.json')).read_text())
    link=[str(dest/'xshard.o') if x==str(root/'build'/obj) else x for x in recipe['link']]
    link[link.index('-o')+1]=str(dest/'probe');subprocess.run(link,check=True,stdout=subprocess.DEVNULL)
    recipe.update(link=link,sha256=hashlib.sha256((dest/'probe').read_bytes()).hexdigest(),trial_compile=args)
    count.save(count.OUT/('optional-'+ns+'-build.json'),recipe)
for ns in ('normal','db0'):build(ns)
cases=[('optional',ns,shape,'2s',n,1,-1) for ns in ('normal','db0') for shape,n in [('EXEC-single',1),('EXEC-cross',4)]]
with concurrent.futures.ThreadPoolExecutor(4) as pool:rows=list(pool.map(count.trace,cases))
count.save(root/'docs/wave8b/optional-counts.json',rows)
