#!/usr/bin/env python3
"""Run source-tool positives and broken-anchor controls in disposable source trees.

No server is started. --root points at a copied, optionally clang-formatted tree.
Every control restores its input in finally; the production checkout is refused.
"""
import argparse
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def cases():
    result = []
    def add(name, command, file, anchor):
        result.append((name, command, file, anchor))
    def python(code):
        return ['-c', "import sys;sys.path[:0]=['tests','tools'];from pathlib import Path;" + code]
    add('r7shadow_sync', ['tests/r7shadow_sync.py'], 'src/core/io_loop.h', 'TOMO_TOOL_FUNCTION parse_and_dispatch')
    add('reorder_sync', ['tools/reorder_sync.py'], 'src/core/ex_loop.h', 'TOMO_TOOL_FUNCTION fused_pass_impl')
    add('r7shadow_sync_test', ['tests/r7shadow_sync_test.py'], 'src/core/io_loop.h', 'TOMO_TOOL_FUNCTION run_loop')
    add('lottery', ['tools/lottery_build.py','build/proof/lottery'], 'src/cmd/scatter_engine.inc', 'TOMO_TOOL_ANCHOR lottery-read-fragment')
    add('make/climon-mask', ['tools/build_source_controls.py', 'climon-mask', 'src/core/climon_mask.h', 'build/proof/climon-mask.h'], 'src/core/climon_mask.h', 'TOMO_TOOL_FUNCTION climon-mask-word')
    add('make/prebuild-threshold', python("import subprocess;subprocess.run(['make','-s','--eval','a1-proof:;@echo $(L4PREBUILD_TEST_FLAGS)','a1-proof'],check=True)"), 'src/cmd/l4prebuild.cc', 'TOMO_TOOL_ANCHOR l4-prebuild-threshold')
    add('racefix', ['tools/racefix_build.py','build/proof/racefix'], 'src/core/server.h', 'climon_armed_.exchange')
    add('persistfmt', ['tools/persistfmt_schedule.py','src/persist/aof.cc','build/proof/persistfmt.cc'], 'src/persist/aof.cc', 'void AofManager::fail')
    add('storesize', ['tests/storesize_checks.py','src/cmd/multidb.cc','build/proof/storesize.cc'], 'src/cmd/multidb.cc', 'TOMO_TOOL_BIND multidb_size')
    add('rob_portable',['tests/rob_portable_control.py','--prepare-only'], 'src/net/rob.h', 'if (bits & read_local_slot_bit(local_mget_fence_id_)) local_mget_fence_id_ = UINT64_MAX;')
    add('netfix_idle',python("import netfix_idle_buffers as m,source_tokens as c;print(len(m.broken_policy(c.read('src/net/idle_buffers.h'))))"),'src/net/idle_buffers.h','std::max(kWbufInline, p.output[i] + 1)')
    add('racefix_reports',python("import racefix as m;print(m.tsan_reports(''))"),'src/core/io_loop.h','TOMO_TOOL_FUNCTION run_loop')
    for name in ('removed','wrongtype','slowlog','multi','counts','refusal'):
        add('blockfix2/'+name, python("import shutil,blockfix2_controls as m;p=Path('build/proof/blockfix2/"+name+"');shutil.copytree('src',p/'src',dirs_exist_ok=True);print(m.mutation('"+name+"',p))"),
            'src/cmd/t_server.cc' if name=='counts' else 'src/cmd/t_stream_groups.cc' if name=='multi' else 'src/cmd/blocking.inc',
            {'removed':'const bool group_error','wrongtype':'if (blocking_is_move(block->kind))',
             'slowlog':'SlowlogTiming timing','multi':'(void)stream_xreadgroup_execute(shard, op, false);',
             'counts':'blocking_key_counts','refusal':'remove_at_from_shard'}[name])
    for name in ('aoforder','notifycompat','trackfix'):
        anchor = 'TOMO_TOOL_ANCHOR aoforder-expiry' if name=='aoforder' else 'void IoLoop::tracking_handle_event'
        file = 'src/cmd/scatter_engine.inc' if name=='aoforder' else 'src/cmd/tracking.cc'
        add(name, [f'tools/{name}_schedule.py','--prepare-only','--objects','build/objects','--output',f'build/proof/{name}'],file,anchor)
    add('woundfix',['tools/woundfix_windows.py','build/proof/woundfix'], 'src/cmd/multi.inc','bool txn_wound')
    add('lbplanner_pad',python('import lbplanner_pad as m;print(m.source_proof())'), 'src/core/lbplanner.cc','TOMO_TOOL_BIND lb_controller_tick_pad')
    add('lbosc3_pad',python('import lbosc3_pad as m;print(m.source_proof())'), 'src/core/lbplanner.cc','TOMO_TOOL_ANCHOR lbosc3-admission')
    for control in ('no-publish','stale-flip','stale-lb','duplicate','copy-on-io','record-reuse','timing-lock','timing-late-pause','timing-budget'):
        file='src/core/io_loop.h' if control.startswith('timing') else 'src/core/lbplanner.cc'
        anchor='TOMO_TOOL_FUNCTION run_loop' if control.startswith('timing') else 'TOMO_TOOL_BIND lb_consume_plan'
        add('lbplanner/'+control,['tools/lbplanner_controls.py',control,f'build/proof/lb/{control}/source/src/core/io_loop.h' if control.startswith('timing') else f'build/proof/lb/{control}.cc'],file,anchor)
    for name in ('old-ack','old-close','no-refusal'):
        anchor={'old-ack':'bool AofManager::defer_completion','old-close':'void AofManager::worker_shutdown','no-refusal':'const uint64_t refused'}[name]
        add('persistfix/'+name,['tools/persistfix_controls.py',name,f'build/proof/{name}.cc'],'src/persist/aof.cc',anchor)
    add('wb_rule',python("import wb_rule_checks as m;[m.emit(n,Path('build/proof/wb')/n) for n in m.MUTANTS];print(len(m.MUTANTS))"),'src/core/wb_rule.h','TOMO_TOOL_BIND kSmallPipe')
    add('wbland', ['tests/wbland_checks.py','source'],'src/core/io_loop.h','TOMO_TOOL_FUNCTION flush_ready')
    add('wbland_emit',python("import wbland_checks as m;[m.emit(n,Path('build/proof/wbland')/n) for n in m.MUTANTS];print(len(m.MUTANTS))"),'src/core/wb_rule.h','TOMO_TOOL_BIND kSmallPipe')
    add('flushfix',python("import flushfix_checks as m;[m.emit_header(n,Path('build/proof/flush')/n) for n in m.SITES];print(len(m.SITES))"),'src/store/kvobj.h','TOMO_TOOL_BIND kvobj_init_raw_string')
    add('flushfix3',['tools/flushfix3_work_reference.py','--prepare-only','--namespace','normal','--cores','64-95','--output','build/proof/flushfix3'],'src/store/flush.cc','TOMO_TOOL_BIND atomic_flush_erase')
    add('rootcore',['tools/rootcore_inbox.py','--prepare-only','--output','build/proof/rootcore'],'src/core/thread.h','private:')
    add('splitlocal',['tests/splitlocal_checks.py','emit','build/proof/splitlocal.cc'],'src/core/io_loop.h','TOMO_TOOL_FUNCTION parse_and_dispatch')
    add('docs_drift',['tests/docs_drift.py'],'src/core/config.h','TOMO_TOOL_BIND settings')
    add('cmdmeta_coverage',['tests/cmdmeta_coverage.py'],'src/cmd/t_string.cc','TOMO_TOOL_BIND kTable')
    add('gen_cmdmeta',['tools/gen_cmdmeta.py','--redis-root','/tmp/claude-1000/redis74','--check','src/cmd/cmdmeta_generated.inc'],'src/cmd/t_string.cc','TOMO_TOOL_BIND kTable')
    add('gen_acl_categories',['tools/gen_acl_categories.py','--redis-root','/tmp/claude-1000/redis74','--check','src/cmd/acl_categories_generated.h'],'src/cmd/t_string.cc','TOMO_TOOL_BIND kTable')
    add('gen_cmddocs',['tools/gen_cmddocs.py','--redis-root','/tmp/claude-1000/redis74','--check'],'src/cmd/t_string.cc','TOMO_TOOL_BIND kTable')
    add('serverfix_config',python('import serverfix_config as m;print(len(m.inventory()))'),'src/cmd/t_server.cc','TOMO_TOOL_BIND init_config')
    add('mdbqsbr_live',python('import mdbqsbr_live as m;print(m.TICK)'),'src/net/uring.h','TOMO_TOOL_BIND kWaitTimeoutMs')
    add('acl',['tests/acl.py','--source-check'],'src/core/pubsub.inc','TOMO_TOOL_BIND pubsub_deliver_one')
    add('acl_categories',['tests/acl_categories.py','--source-check'],'src/cmd/acl_categories_generated.h','"keyspace"')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--only')
    a=p.parse_args();root=a.root.resolve()
    if root==ROOT or not root.is_relative_to(ROOT/'build'):
        raise ValueError('proof must use a disposable tree inside this worktree/build')
    sys.path.insert(0,str(ROOT/'tools'))
    import source_tokens as cpp
    rows=[];a.output.mkdir(parents=True,exist_ok=True)
    generated={};digests={}
    for name,command,file,anchor in cases():
        if a.only and a.only not in name:continue
        path=root/file;original=path.read_text()
        env=dict(os.environ,LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
        def run():return subprocess.run([sys.executable,*command],cwd=root,env=env,capture_output=True,text=True,timeout=90)
        started=time.time_ns()
        positive=run()
        row=dict(tool=name,command=command,positive=positive.returncode,stdout=positive.stdout,stderr=positive.stderr)
        if positive.returncode==0:
            # Capture outputs before a rejected patch can overwrite its scratch
            # copy. copy2 preserves input mtimes, so unchanged copied headers
            # need not be re-hashed for every control.
            emitted={}
            for directory in (root/'build/proof',root/'build/flushfix3/work-reference'):
                for output in directory.rglob('*'):
                    if output.suffix not in ('.cc','.h','.inc') or output.stat().st_mtime_ns < started:
                        continue
                    raw=output.read_text().replace(str(root), '$SCRATCH')
                    if raw not in digests:
                        code=cpp.Source(raw,cpp.source_aliases(root))
                        digests[raw]=hashlib.sha256(cpp.normalized(code).encode()).hexdigest()
                    emitted[str(output.relative_to(root))]=digests[raw]
            row['emitted_tokens']=emitted
            generated.update(emitted)
            try:
                # Marker text and code anchors have separate lexical treatment.
                if anchor.startswith('TOMO_TOOL_'):
                    if original.count(anchor)!=1:raise ValueError('nonunique proof marker '+anchor)
                    changed=original.replace(anchor,'BROKEN_A1_ANCHOR',1)
                else:
                    code=cpp.read(path)
                    spans=code.spans(anchor)
                    if not spans:raise ValueError('proof anchor absent '+anchor)
                    # A field name may occur at multiple uses: corrupt every occurrence.
                    changed=code.replace(anchor,'BROKEN_A1_ANCHOR',len(spans))
                path.write_text(changed)
                broken=run()
                row.update(negative=broken.returncode,negative_stdout=broken.stdout,negative_stderr=broken.stderr)
            finally:path.write_text(original)
        row['passed']=row['positive']==0 and row.get('negative',0)!=0
        rows.append(row)
        (a.output/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(('PASS' if row['passed'] else 'FAIL'),name,'positive',row['positive'],'negative',row.get('negative'),flush=True)
        if not row['passed']:print(row.get('stderr','')+row.get('negative_stdout','')+row.get('negative_stderr',''),flush=True)
    # Verify that formatting did not silently choose a different instrumentation
    # branch: compare every emitted C++ token stream between source shapes.
    (a.output/'generated-tokens.json').write_text(json.dumps(generated,indent=2)+'\n')
    return int(not rows or not all(r['passed'] for r in rows))


if __name__=='__main__':raise SystemExit(main())
