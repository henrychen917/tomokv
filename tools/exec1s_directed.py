#!/usr/bin/env python3
"""Re-prove X2 with production helpers and throwaway, discriminating controls."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/exec1s-evidence/directed'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def run(label,cmd,env=None):
    log=OUT/(label+'.log')
    with log.open('w') as stream:
        result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
    return dict(command=cmd,returncode=result.returncode,log=str(log),log_sha256=sha(log))

def main():
    assert os.sched_getaffinity(0)<=set(range(48,64))
    OUT.mkdir(parents=True,exist_ok=True)
    build=run('build',['make','-j16','build/exec1s-unit','build/exec1s-word-tsan'])
    assert build['returncode']==0
    recipe=subprocess.check_output(['make','-n','-W','tests/exec1s_unit.cc','build/exec1s-unit'],cwd=ROOT,text=True)
    command=shlex.split(next(line for line in recipe.splitlines() if ' -o build/exec1s-unit ' in line))
    overlay=OUT/'old-publication-source'
    if overlay.exists():shutil.rmtree(overlay)
    shutil.copytree(ROOT/'src',overlay/'src')
    header=overlay/'src/core/ex_loop.h'
    text=header.read_text()
    old='// Expiry/object-byte statistics may change while the key count stays fixed.\n        shard.publish_size();'
    new='// Throwaway exact old guard: leaves expiry/object-byte publications stale.\n        if (shard.store().size() != shard.published_size()) shard.publish_size();'
    assert text.count(old)==1;header.write_text(text.replace(old,new))
    negative=ROOT/'build/exec1s-unit-old-publication'
    broken=[str(negative) if x=='build/exec1s-unit' else x for x in command]
    broken[1:1]=['-I'+str(overlay)]
    built=run('old-publication-build',broken);assert built['returncode']==0
    original=ROOT/'build/exec1s-unit'
    positive=[];negative_rows=[];groups=[]
    for mode in ('1s','2s'):
        for atomic in ('0','1'):
            for name in ('publication','reclaim','floor'):
                row=run(f'{name}-{mode}-{atomic}', ['taskset','-c','48-55',str(original),name,mode,atomic])
                assert row['returncode']==0 and 'PASS exec1s '+name in Path(row['log']).read_text()
                (positive if name=='publication' else groups).append(row)
            row=run(f'old-publication-{mode}-{atomic}', ['taskset','-c','48-55',str(negative),'publication',mode,atomic])
            row['expected_failure']=row['returncode']==1 and 'standalone transaction task publishes non-size statistics' in Path(row['log']).read_text()
            assert row['expected_failure'];negative_rows.append(row)
    provenance=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    production_sha256=sha(ROOT/'build/exec1s-POST'),positive_unit_sha256=sha(original))
    publication=dict(**provenance,positive=positive,negative=negative_rows,
                     negative_unit_sha256=sha(negative),control_build=built,control_source_sha256=sha(header),
                     control='Restore only the old size-equality publication guard in a temporary source overlay.')
    (ROOT/'docs/exec1s/publication-negative.json').write_text(json.dumps(publication,indent=2)+'\n')
    control_log=OUT/'word-wide-control.log'
    env=dict(os.environ,TSAN_OPTIONS='halt_on_error=1:exitcode=66')
    word=run('word-tsan',['setarch','x86_64','-R','taskset','-c','48-55',str(ROOT/'build/exec1s-word-tsan'),'word',str(control_log)],env)
    assert word['returncode']==0 and 'PASS exec1s word' in Path(word['log']).read_text()
    assert 'ThreadSanitizer: data race' in control_log.read_text()
    word.update(**provenance,unit_sha256=sha(ROOT/'build/exec1s-word-tsan'),
                production_helper_source_sha256=sha(ROOT/'src/store/atomic_mvcc.h'),
                negative_log_sha256=sha(control_log),negative_expected_exit=66,
                actual_group_wrap_and_floor_checks=groups,passed=True)
    (ROOT/'docs/exec1s/word-tsan.json').write_text(json.dumps(word,indent=2)+'\n')
    shutil.rmtree(overlay);negative.unlink()
    print('PASS X2 publication (4 positives / 4 old-guard failures), TSAN wide-write control, wrap/floor (8)',flush=True)

if __name__=='__main__':main()
