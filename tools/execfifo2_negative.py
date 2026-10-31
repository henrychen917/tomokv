#!/usr/bin/env python3
"""Serverless process-local breaks; no broken source or binary is published."""
import hashlib,itertools,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/execfifo2/negative'
def main():
    assert os.sched_getaffinity(0)<=set(range(32))
    OUT.mkdir(parents=True,exist_ok=True);rows=[]
    for ns,mode in itertools.product(('normal','db0'),('1s','2s')):
        prefix='tomo' if ns=='normal' else 'tomo_db0'
        suffix='' if ns=='normal' else '-db0'
        fused='true' if mode=='1s' else 'false'
        cases=[('fifo','txnorder-fifo', ['F1',mode,'1','uring'],prefix+'::multi_plain_write_probe', 'true','F1 older waiter FIFO-refuses W'),
               ('chain','txnorder-chain',['local',mode],prefix+f'::ExLoopT<{fused}>::service_multi_chain<false>', '0',"all same-owner fragments finish in the sibling's owner turn, without a poll pass"),
               ('boundary','txnorder-chain',['serve',mode],prefix+f'::ExLoopT<{fused}>::service_txn_boundary<false>', 'true','held claim refuses serve and closes chain')]
        for name,target,args,symbol,value,failure in cases:
            binary=ROOT/'build'/(target+suffix+'-unit');label=f'{name}-{ns}-{mode}'
            script=OUT/(label+'.gdb');log=OUT/(label+'.log')
            script.write_text('set pagination off\nset confirm off\nset breakpoint pending off\n'+
                f'break {symbol}\ncommands\nsilent\nprintf "CONTROL FIRED\\n"\nreturn {value}\ncontinue\nend\nrun\n'+
                'python\nprint("INFERIOR_EXIT", gdb.parse_and_eval("$_exitcode"))\nend\n')
            cmd=['gdb','-q','-batch','-x',str(script),'--args',str(binary),*args]
            with log.open('w') as stream:r=subprocess.run(cmd,cwd=ROOT,env=dict(os.environ,LC_ALL='C'),stdout=stream,stderr=subprocess.STDOUT,timeout=60)
            text=log.read_text();valid=r.returncode==0 and 'CONTROL FIRED' in text and 'FAIL: '+failure in text and 'INFERIOR_EXIT 1' in text
            rows.append(dict(case=label,binary=str(binary),sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),command=cmd,breakpoint=symbol,forced_return=value,expected_failure=failure,gdb_returncode=r.returncode,detected=valid))
            (OUT/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
            print(label,valid,flush=True)
            assert valid,log
if __name__=='__main__':main()
